"""Torrent import service for adding downloads to library."""

import logging
from pathlib import Path

from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.library.models import (
    DownloadEpisode,
    DownloadIMDbMetadata,
    DownloadMovie,
    DownloadSeason,
    DownloadSeries,
    FileMatch,
    MatchedTorrentFiles,
    create_episode_entity,
    create_movie_entity,
    create_season_entity,
    create_series_entity,
)
from app.library.models import VideoQuality

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
        imdb_metadata: DownloadIMDbMetadata,
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

        try:
            if isinstance(imdb_metadata, DownloadMovie):
                await self._import_movie(
                    download_path, imdb_metadata, validation_result.matched_files, quality=VideoQuality.UNKNOWN
                )
            elif isinstance(imdb_metadata, DownloadEpisode):
                await self._import_episode(
                    download_path, imdb_metadata, validation_result.matched_files, quality=VideoQuality.UNKNOWN
                )
            elif isinstance(imdb_metadata, DownloadSeason):
                await self._import_season(
                    download_path, imdb_metadata, validation_result.matched_files, quality=VideoQuality.UNKNOWN
                )
            elif isinstance(imdb_metadata, DownloadSeries):
                await self._import_series(
                    download_path, imdb_metadata, validation_result.matched_files, quality=VideoQuality.UNKNOWN
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
        download_movie: DownloadMovie,
        matched_files: list[FileMatch],
        quality: VideoQuality,
    ) -> None:
        """Import a movie download.

        Args:
            download_path: Download path
            download_movie: Movie metadata
            matched_files: Matched files from validation
            quality: Video quality
        """
        logger.info(f"Importing movie: {download_movie.movie.primaryTitle}")

        if not matched_files:
            raise ValueError("No matched files for movie import")

        # Get the movie file
        file_match = matched_files[0]
        file_path = self._find_file_in_download(download_path, file_match.file_path)

        if not file_path:
            raise FileNotFoundError(f"Movie file not found: {file_match.file_path}")

        # Create or get movie entity
        entity = await self.library.get_or_create_movie_entity(download_movie.movie)

        # Add downloaded file
        await self.library.add_downloaded_file(
            media_entity_id=entity.imdb_id,
            file_path=file_path,
            source=f"Torrent: {file_path.name}",
            quality=quality,
        )

        logger.info(f"Successfully imported movie: {entity.title}")

    async def _import_episode(
        self,
        download_path: Path,
        download_episode: DownloadEpisode,
        matched_files: list[FileMatch],
        quality: VideoQuality,
    ) -> None:
        """Import a single episode download.

        Args:
            download_path: Download path
            download_episode: Episode metadata
            matched_files: Matched files from validation
            quality: Video quality
        """
        logger.info(
            f"Importing episode: {download_episode.series.primaryTitle} S{download_episode.season.season}E{download_episode.episode.episodeNumber}"
        )

        if not matched_files:
            raise ValueError("No matched files for episode import")

        # Get series, season, episode from metadata
        series_imdb = download_episode.series
        season_imdb = download_episode.season
        episode_imdb = download_episode.episode

        # Fetch full episode details from IMDb
        episode_details = await self.imdb_client.get_title(episode_imdb.id)

        if not episode_details:
            raise ValueError(f"Could not fetch episode details: {episode_imdb.id}")

        # Get or create series
        series_entity = await self.library.get_or_create_series_entity(series_imdb)

        # Get or create season
        season_entity = await self.library.get_or_create_season_entity(
            series_entity.imdb_id, season_imdb
        )

        # Get or create episode
        episode_entity = await self.library.get_or_create_episode_entity(
            season_entity.imdb_id, episode_imdb, episode_details
        )

        # Find and add file
        file_match = matched_files[0]
        file_path = self._find_file_in_download(download_path, file_match.file_path)

        if not file_path:
            raise FileNotFoundError(f"Episode file not found: {file_match.file_path}")

        await self.library.add_downloaded_file(
            media_entity_id=episode_entity.imdb_id,
            file_path=file_path,
            source=f"Torrent: {file_path.name}",
            quality=quality,
        )

        logger.info(f"Successfully imported episode: {episode_entity.title}")

    async def _import_season(
        self,
        download_path: Path,
        download_season: DownloadSeason,
        matched_files: list[FileMatch],
        quality: VideoQuality,
    ) -> None:
        """Import a season download.

        Args:
            download_path: Download path
            download_season: Season metadata
            matched_files: Matched files from validation
            quality: Video quality
        """
        series_imdb = download_season.series
        season_imdb = download_season.season

        logger.info(f"Importing season: {series_imdb.primaryTitle} Season {season_imdb.season}")

        if not matched_files:
            raise ValueError("No matched files for season import")

        # Fetch all episodes for this season from IMDb
        episodes_list = await self.imdb_client.get_series_episodes(
            series_imdb.id, season_imdb.season
        )

        # Create a mapping of episode number -> IMDbEpisode
        episodes_map = {str(ep.episodeNumber): ep for ep in episodes_list if ep.episodeNumber}

        # Get or create series and season entities (once)
        series_entity = await self.library.get_or_create_series_entity(series_imdb)
        season_entity = await self.library.get_or_create_season_entity(
            series_entity.imdb_id, season_imdb
        )

        # Import each matched file
        imported_count = 0
        for file_match in matched_files:
            try:
                episode_num = file_match.episode_number

                if not episode_num or episode_num not in episodes_map:
                    logger.warning(
                        f"Episode {episode_num} not found in IMDb data, skipping file: {file_match.file_path}"
                    )
                    continue

                episode_imdb = episodes_map[episode_num]

                # Fetch full episode details
                episode_details = await self.imdb_client.get_title(episode_imdb.id)

                if not episode_details:
                    logger.warning(f"Could not fetch details for episode {episode_num}, skipping")
                    continue

                # Get or create episode entity
                episode_entity = await self.library.get_or_create_episode_entity(
                    season_entity.imdb_id, episode_imdb, episode_details
                )

                # Find and add file
                file_path = self._find_file_in_download(download_path, file_match.file_path)

                if not file_path:
                    logger.warning(f"File not found: {file_match.file_path}")
                    continue

                await self.library.add_downloaded_file(
                    media_entity_id=episode_entity.imdb_id,
                    file_path=file_path,
                    source=f"Torrent: {file_path.name}",
                    quality=quality,
                )

                imported_count += 1
                logger.info(f"Imported episode {episode_num}: {episode_entity.title}")

            except Exception as e:
                logger.error(f"Error importing file {file_match.file_path}: {e}")
                continue

        logger.info(
            f"Successfully imported {imported_count}/{len(matched_files)} episodes from season"
        )

    async def _import_series(
        self,
        download_path: Path,
        download_series: DownloadSeries,
        matched_files: list[FileMatch],
        quality: VideoQuality,
    ) -> None:
        """Import a complete series download.

        Args:
            download_path: Download path
            download_series: Series metadata
            matched_files: Matched files from validation
            quality: Video quality
        """
        series_imdb = download_series.series

        logger.info(f"Importing series: {series_imdb.primaryTitle}")

        if not matched_files:
            raise ValueError("No matched files for series import")

        # Group matched files by season
        files_by_season = self._group_matches_by_season(matched_files)

        # Fetch all seasons
        seasons_list = await self.imdb_client.get_series_seasons(series_imdb.id)
        seasons_map = {str(season.season): season for season in seasons_list}

        # Get or create series entity (once)
        series_entity = await self.library.get_or_create_series_entity(series_imdb)

        total_imported = 0

        # Process each season
        for season_num, season_files in files_by_season.items():
            try:
                logger.info(f"Processing season {season_num} with {len(season_files)} files")

                if season_num not in seasons_map:
                    logger.warning(f"Season {season_num} not found in IMDb data, skipping")
                    continue

                season_imdb = seasons_map[season_num]

                # Fetch episodes for this season
                episodes_list = await self.imdb_client.get_series_episodes(
                    series_imdb.id, season_num
                )
                episodes_map = {
                    str(ep.episodeNumber): ep for ep in episodes_list if ep.episodeNumber
                }

                # Get or create season entity
                season_entity = await self.library.get_or_create_season_entity(
                    series_entity.imdb_id, season_imdb
                )

                # Import each file in season
                for file_match in season_files:
                    try:
                        episode_num = file_match.episode_number

                        if not episode_num or episode_num not in episodes_map:
                            logger.warning(
                                f"Episode S{season_num}E{episode_num} not in IMDb data, skipping"
                            )
                            continue

                        episode_imdb = episodes_map[episode_num]

                        # Fetch full episode details
                        episode_details = await self.imdb_client.get_title(episode_imdb.id)

                        if not episode_details:
                            logger.warning(
                                f"Could not fetch details for S{season_num}E{episode_num}"
                            )
                            continue

                        # Get or create episode entity
                        episode_entity = await self.library.get_or_create_episode_entity(
                            season_entity.imdb_id, episode_imdb, episode_details
                        )

                        # Find and add file
                        file_path = self._find_file_in_download(download_path, file_match.file_path)

                        if not file_path:
                            logger.warning(f"File not found: {file_match.file_path}")
                            continue

                        await self.library.add_downloaded_file(
                            media_entity_id=episode_entity.imdb_id,
                            file_path=file_path,
                            source=f"Torrent: {file_path.name}",
                            quality=quality,
                        )

                        total_imported += 1

                    except Exception as e:
                        logger.error(
                            f"Error importing S{season_num}E{file_match.episode_number}: {e}"
                        )
                        continue

            except Exception as e:
                logger.error(f"Error processing season {season_num}: {e}")
                continue

        logger.info(
            f"Successfully imported {total_imported}/{len(matched_files)} episodes from series"
        )

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
            return full_path

        # Try just the filename (for single-file torrents)
        filename = Path(file_path).name
        if download_path.is_file() and download_path.name == filename:
            return download_path

        # Search in subdirectories
        for item in download_path.rglob(filename):
            if item.is_file():
                return item

        logger.warning(f"File not found: {file_path} in {download_path}")
        return None

    def _group_matches_by_season(
        self, matched_files: list[FileMatch]
    ) -> dict[str, list[FileMatch]]:
        """Group file matches by season number.

        Args:
            matched_files: List of file matches

        Returns:
            Dictionary mapping season number (str) to list of file matches
        """
        groups = {}

        for file_match in matched_files:
            season = file_match.season_number

            if season:
                if season not in groups:
                    groups[season] = []
                groups[season].append(file_match)

        return groups
