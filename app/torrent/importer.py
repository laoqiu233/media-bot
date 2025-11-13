"""Torrent import service for adding downloads to library."""

import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.library.models import (
    DownloadedFile,
    DownloadEpisode,
    DownloadMovie,
    DownloadSeason,
    DownloadSeries,
    FileMatch,
    IMDbEpisode,
    IMDbSeason,
    IMDbTitle,
    MatchedTorrentFiles,
    MediaEntity,
    create_episode_entity,
    create_movie_entity,
    create_season_entity,
    create_series_entity,
)
from app.torrent.searcher import TorrentSearchResult

logger = logging.getLogger(__name__)


class TorrentImporter:
    """Service for importing completed torrent downloads to library."""

    def __init__(self, library_manager: LibraryManager, imdb_client: IMDbClient):
        """Initialize importer.

        Args:
            library_manager: Library manager
            imdb_client: IMDb API client
        """
        self.library = library_manager
        self.imdb_client = imdb_client

    async def import_download(
        self,
        download_path: Path,
        torrent: TorrentSearchResult,
        validation_result: MatchedTorrentFiles,
    ) -> None:
        """Import a completed download to library.

        Args:
            download_path: Path to downloaded content
            metadata: Download metadata with IMDb info
            validation_result: Validation result with matched files

        Raises:
            Exception: If import fails
        """
        logger.info(f"Importing download from: {download_path}")

        imdb_metadata = validation_result.download_metadata

        try:
            if isinstance(imdb_metadata, DownloadMovie):
                await self._import_movie(
                    download_path,
                    imdb_metadata,
                    torrent,
                    validation_result.matched_files,
                )
            elif isinstance(imdb_metadata, DownloadEpisode):
                detailed_episode = await self.imdb_client.get_title(imdb_metadata.episode.id)
                if detailed_episode is None:
                    raise ValueError(f"Episode not found on IMDb: {imdb_metadata.episode.id}")
                await self._import_episode(
                    download_path,
                    imdb_metadata,
                    detailed_episode,
                    torrent,
                    validation_result.matched_files,
                    None,
                    None,
                )
            elif isinstance(imdb_metadata, DownloadSeason):
                await self._import_season(
                    download_path, imdb_metadata, torrent, validation_result.matched_files, None
                )
            elif isinstance(imdb_metadata, DownloadSeries):
                await self._import_series(
                    download_path, imdb_metadata, torrent, validation_result.matched_files
                )
            else:
                raise ValueError(f"Unknown metadata type: {type(imdb_metadata)}")

            logger.info("Import completed successfully")

        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            raise

    async def _import_movie(
        self,
        download_path: Path,
        imdb_metadata: DownloadMovie,
        torrent: TorrentSearchResult,
        matched_files: list[FileMatch],
    ):
        if not matched_files:
            raise ValueError("No matched files for movie import")
        matched_file = matched_files[0]
        downloaded_file_path = self._find_file_in_download(download_path, matched_file.file_path)
        if not downloaded_file_path:
            raise FileNotFoundError(f"Movie file not found: {matched_file.file_path}")
        entity = create_movie_entity(imdb_metadata.movie)
        await self.library.create_or_update_entity(entity)
        downloaded_file = DownloadedFile(
            id=uuid4().hex,
            media_entity_id=entity.imdb_id,
            file_name=downloaded_file_path.name,
            quality=torrent.quality,
            file_size=downloaded_file_path.stat().st_size,
            downloaded_date=datetime.now(),
            source=torrent.source,
        )
        await self.library._add_downloaded_file(entity, downloaded_file, downloaded_file_path)

    async def _import_series(
        self,
        download_path: Path,
        imdb_metadata: DownloadSeries,
        torrent: TorrentSearchResult,
        matched_files: list[FileMatch],
    ):
        if not matched_files:
            raise ValueError("No matched files for series import")
        series_entity = await self._create_or_update_series_entity(imdb_metadata.series)
        imdb_seasons = await self.imdb_client.get_series_seasons(imdb_metadata.series.id)

        for season in imdb_seasons:
            seasons_metadata = DownloadSeason(series=imdb_metadata.series, season=season)
            await self._import_season(
                download_path, seasons_metadata, torrent, matched_files, series_entity
            )

    async def _import_season(
        self,
        download_path: Path,
        imdb_metadata: DownloadSeason,
        torrent: TorrentSearchResult,
        matched_files: list[FileMatch],
        series_entity: MediaEntity | None,
    ):
        if not matched_files:
            raise ValueError("No matched files for season import")

        if series_entity is None:
            series_entity = await self._create_or_update_series_entity(imdb_metadata.series)

        season_entity = await self._create_or_update_season_entity(
            series_entity, imdb_metadata.season
        )
        episodes = await self.imdb_client.get_series_episodes(
            imdb_metadata.series.id, imdb_metadata.season.season
        )
        detailed_episodes = await self.imdb_client.get_titles_batch(
            [episode.id for episode in episodes]
        )

        for episode, detailed_episode in zip(episodes, detailed_episodes, strict=False):
            episodes_metadata = DownloadEpisode(
                series=imdb_metadata.series, season=imdb_metadata.season, episode=episode
            )
            await self._import_episode(
                download_path,
                episodes_metadata,
                detailed_episode,
                torrent,
                matched_files,
                series_entity,
                season_entity,
            )

    async def _import_episode(
        self,
        download_path: Path,
        imdb_metadata: DownloadEpisode,
        imdb_episode_detailed: IMDbTitle,
        torrent: TorrentSearchResult,
        matched_files: list[FileMatch],
        series_entity: MediaEntity | None,
        season_entity: MediaEntity | None,
    ):
        if not matched_files:
            raise ValueError("No matched files for episode import")

        if series_entity is None:
            series_entity = await self._create_or_update_series_entity(imdb_metadata.series)
        if season_entity is None:
            season_entity = await self._create_or_update_season_entity(
                series_entity, imdb_metadata.season
            )

        entity = await self._create_or_update_episode_entity(
            series_entity, season_entity, imdb_metadata.episode, imdb_episode_detailed
        )

        for file in matched_files:
            if file.episode is not None and file.episode.id == imdb_metadata.episode.id:
                match_file = file
                break
        else:
            raise ValueError(f"Episode file not found: {imdb_metadata.episode.id}")

        downloaded_file_path = self._find_file_in_download(download_path, match_file.file_path)
        if not downloaded_file_path:
            raise FileNotFoundError(f"Episode file not found: {match_file.file_path}")
        downloaded_file = DownloadedFile(
            id=uuid4().hex,
            media_entity_id=entity.imdb_id,
            file_name=downloaded_file_path.name,
            quality=torrent.quality,
            file_size=downloaded_file_path.stat().st_size,
            downloaded_date=datetime.now(),
            source=torrent.source,
        )
        await self.library._add_downloaded_file(entity, downloaded_file, downloaded_file_path)

    async def _create_or_update_series_entity(self, series: IMDbTitle) -> MediaEntity:
        series_entity = await self.library.get_entity(series.id)
        if (
            new_series_entity := create_series_entity(series)
        ) != series_entity or series_entity is None:
            await self.library.create_or_update_entity(new_series_entity)
            series_entity = new_series_entity
        return series_entity

    async def _create_or_update_season_entity(
        self, series: MediaEntity, season: IMDbSeason
    ) -> MediaEntity:
        new_season_entity = create_season_entity(series, season)
        season_entity = await self.library.get_entity(new_season_entity.imdb_id)
        if new_season_entity != season_entity or season_entity is None:
            await self.library.create_or_update_entity(new_season_entity)
            season_entity = new_season_entity
        return season_entity

    async def _create_or_update_episode_entity(
        self,
        series: MediaEntity,
        season: MediaEntity,
        episode: IMDbEpisode,
        imdb_episode_detailed: IMDbTitle,
    ) -> MediaEntity:
        new_episode_entity = create_episode_entity(series, season, episode, imdb_episode_detailed)
        episode_entity = await self.library.get_entity(new_episode_entity.imdb_id)
        if new_episode_entity != episode_entity or episode_entity is None:
            await self.library.create_or_update_entity(new_episode_entity)
            episode_entity = new_episode_entity
        return episode_entity

    def _find_file_in_download(self, download_path: Path, file_path: str) -> Path | None:
        """Find a file in the download directory.

        Args:
            download_path: Root download path
            file_path: Relative file path from torrent

        Returns:
            Full path to file, or None if not found
        """
        # Handle both single-file and multi-file torrents

        # Try direct path
        full_path = download_path / file_path
        if full_path.exists() and full_path.is_file():
            logger.debug(f"Found file at direct path: {full_path}")
            return full_path

        # Often the file_path includes the torrent name as a prefix directory
        # but download_path already points to that directory.
        # Try stripping the first directory component
        file_path_obj = Path(file_path)
        if len(file_path_obj.parts) > 1:
            stripped_path = Path(*file_path_obj.parts[1:])
            full_path = download_path / stripped_path
            if full_path.exists() and full_path.is_file():
                logger.debug(f"Found file at stripped path: {full_path}")
                return full_path

        # Try just the filename (for single-file torrents)
        filename = Path(file_path).name
        if download_path.is_file() and download_path.name == filename:
            logger.debug(f"Found single file: {download_path}")
            return download_path

        # Search in subdirectories
        logger.debug(f"Searching recursively for {filename} in {download_path}")
        for item in download_path.rglob(filename):
            if item.is_file():
                logger.debug(f"Found file via rglob: {item}")
                return item

        logger.warning(f"File not found: {file_path} in {download_path}")
        return None
