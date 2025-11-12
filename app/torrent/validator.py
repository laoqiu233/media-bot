"""Torrent validation service."""

import logging

try:
    import libtorrent as lt
except ImportError:
    lt = None

from app.library.imdb_client import IMDbClient
from app.library.models import (
    DownloadEpisode,
    DownloadIMDbMetadata,
    DownloadMovie,
    DownloadSeason,
    DownloadSeries,
    FileMatch,
    IMDbEpisode,
    MatchedTorrentFiles,
    VideoQuality,
)
from app.torrent.file_utils import is_video_file, parse_episode_info
from app.torrent.metadata_fetcher import TorrentMetadataFetcher
from app.torrent.searcher import TorrentSearchResult

logger = logging.getLogger(__name__)


class TorrentValidator:
    """Service for validating torrent content against download metadata."""

    def __init__(self, metadata_fetcher: TorrentMetadataFetcher, imdb_client: IMDbClient):
        self.metadata_fetcher = metadata_fetcher
        self.imdb_client = imdb_client

    async def validate_torrent(
        self, torrent: TorrentSearchResult, download_imdb_metadata: DownloadIMDbMetadata
    ) -> MatchedTorrentFiles:
        """Validate torrent content against requested download metadata.

        Args:
            magnet_or_file: Magnet link, URL, or path to torrent file
            download_metadata: Download metadata with IMDb info
            requires_auth: Whether the torrent source requires authentication

        Returns:
            ValidationResult with matched files and warnings

        Raises:
            Exception: If validation fails
        """
        logger.info("Validating torrent content...")

        torrent_file_path = None
        try:
            # Fetch torrent metadata
            if torrent.magnet_link:
                torrent_info = await self.metadata_fetcher.fetch_from_magnet(torrent.magnet_link)
            else:
                torrent_file_path = await torrent.fetch_torrent_file()
                torrent_info = await self.metadata_fetcher.fetch_from_file(torrent_file_path)

            # Extract files from torrent
            files = self._extract_files_from_torrent(torrent_info)
            logger.info(f"Found {len(files)} files in torrent {torrent.title}")
            for file in files:
                logger.info(f"File {file['index']}: {file['path']} - {file['size']}")

            # Route to appropriate validation method
            if isinstance(download_imdb_metadata, DownloadMovie):
                result = await self._validate_movie(files, download_imdb_metadata)
            elif isinstance(download_imdb_metadata, DownloadEpisode):
                result = await self._validate_episode(files, download_imdb_metadata)
            elif isinstance(download_imdb_metadata, DownloadSeason):
                result = await self._validate_season(files, download_imdb_metadata)
            elif isinstance(download_imdb_metadata, DownloadSeries):
                result = await self._validate_series(files, download_imdb_metadata)

            return result

        except Exception as e:
            logger.error(f"Validation error: {e}")
            raise

    def _extract_files_from_torrent(self, torrent_info) -> list[dict]:
        """Extract file list from torrent info.

        Args:
            torrent_info: libtorrent torrent_info object

        Returns:
            List of dicts with keys: index, path, size
        """
        files = []

        try:
            # Try modern API first (libtorrent 2.x)
            file_storage = torrent_info.files()
            num_files = file_storage.num_files()

            for i in range(num_files):
                file_entry = file_storage.at(i)
                files.append({"index": i, "path": file_entry.path, "size": file_entry.size})

        except AttributeError:
            # Fall back to older API (libtorrent 1.x)
            try:
                for i in range(torrent_info.num_files()):
                    file = torrent_info.files().at(i)
                    files.append({"index": i, "path": file.path, "size": file.size})
            except Exception as e:
                logger.error(f"Error extracting files: {e}")
                # Last resort - try to get file info differently
                pass

        return files

    def _filter_video_files(self, files: list[dict]) -> list[dict]:
        """Filter list to only video files.

        Args:
            files: List of file dicts

        Returns:
            Filtered list of video files
        """
        return [f for f in files if is_video_file(f["path"])]

    async def _validate_movie(
        self, files: list[dict], download_movie: DownloadMovie
    ) -> MatchedTorrentFiles:
        """
        Validate files for DownloadMovie.
        For movies, find the largest file and consider it as the main match.

        Args:
            files: List of file dicts
            download_movie: DownloadMovie instance

        Returns:
            MatchedTorrentFiles
        """

        video_files = self._filter_video_files(files)
        matched_files = []
        missing_content = []
        warnings = []

        if video_files:
            largest_file = max(video_files, key=lambda f: f["size"])
            matched_files.append(
                FileMatch(
                    file_index=largest_file["index"],
                    file_path=largest_file["path"],
                    movie=download_movie.movie,
                )
            )
        else:
            missing_content.append("Movie video file")
            warnings.append("No video files found in the torrent.")

        return MatchedTorrentFiles(
            matched_files=matched_files,
            missing_content=missing_content,
            warnings=warnings,
            has_all_requested_content=len(matched_files) > 0,
            download_metadata=download_movie,
            total_files=len(files)
        )

    async def _validate_series(
        self, files: list[dict], download_series: DownloadSeries
    ) -> MatchedTorrentFiles:
        """
        Validate files for DownloadSeries.
        Matches all video files (for the series as a whole).

        Args:
            files: List of file dicts
            download_series: DownloadSeries instance

        Returns:
            MatchedTorrentFiles
        """

        logger.info(f"Fetching all episodes for series {download_series.series.id}")
        episodes = await self.imdb_client.get_series_episodes(download_series.series.id)
        return await self._validate_episodes(files, episodes, download_series)

    async def _validate_season(
        self, files: list[dict], download_season: DownloadSeason
    ) -> MatchedTorrentFiles:
        """
        Validate files for DownloadSeason.
        Finds all video files matching the season number. If no matches, returns empty.

        Args:
            files: List of file dicts
            download_season: DownloadSeason instance

        Returns:
            MatchedTorrentFiles
        """

        logger.info(
            f"Fetching episodes for series {download_season.series.id} "
            f"season {download_season.season.season}"
        )
        episodes = await self.imdb_client.get_series_episodes(
            download_season.series.id, download_season.season.season
        )
        return await self._validate_episodes(files, episodes, download_season)

    async def _validate_episode(
        self, files: list[dict], download_episode: DownloadEpisode
    ) -> MatchedTorrentFiles:
        """
        Validate files for DownloadEpisode.
        Finds the file matching the right SxxExx tag.

        Args:
            files: List of file dicts
            download_episode: DownloadEpisode instance

        Returns:
            MatchedTorrentFiles
        """
        logger.info(
            f"Validating single episode: S{download_episode.season.season}E{download_episode.episode.episodeNumber}"
        )
        # For single episode, create a list with just that episode
        episodes = [download_episode.episode]
        return await self._validate_episodes(files, episodes, download_episode)

    async def _validate_episodes(
        self,
        files: list[dict],
        episodes: list[IMDbEpisode],
        download_imdb_metadata: DownloadIMDbMetadata,
    ) -> MatchedTorrentFiles:
        """Match torrent files to episodes.

        Args:
            files: List of file dicts from torrent
            episodes: List of IMDb episodes to match against
            download_imdb_metadata: The download metadata for creating result

        Returns:
            MatchedTorrentFiles with matched files and validation results
        """
        video_files = self._filter_video_files(files)
        matched_files = []
        warnings = []

        # Create a set of expected episode numbers for tracking
        expected_episodes = {
            (int(ep.season) if ep.season else 0, ep.episodeNumber)
            for ep in episodes
            if ep.episodeNumber
        }
        found_episodes = set()

        logger.info(f"Matching {len(video_files)} video files against {len(episodes)} episodes")

        # Match each video file to an episode
        for file_info in video_files:
            file_path = file_info["path"]
            parsed = parse_episode_info(file_path)

            if not parsed:
                warnings.append(f"Could not parse episode info from: {file_path}")
                continue

            season_str, episode_str = parsed
            try:
                season_num = int(season_str)
                episode_num = int(episode_str)
            except ValueError:
                warnings.append(f"Invalid episode numbers in: {file_path}")
                continue

            # Find matching episode in the expected list
            matching_episode = None
            for ep in episodes:
                ep_season = int(ep.season) if ep.season else 0
                if ep_season == season_num and ep.episodeNumber == episode_num:
                    matching_episode = ep
                    break

            if matching_episode:
                matched_files.append(
                    FileMatch(
                        file_index=file_info["index"],
                        file_path=file_path,
                        episode=matching_episode,
                    )
                )
                found_episodes.add((season_num, episode_num))
                logger.info(
                    f"Matched file {file_path} to S{season_num:02d}E{episode_num:02d} "
                    f"({matching_episode.title})"
                )
            else:
                warnings.append(
                    f"File {file_path} (S{season_num:02d}E{episode_num:02d}) "
                    f"doesn't match any expected episodes"
                )

        # Identify missing episodes
        missing_episodes = expected_episodes - found_episodes
        missing_content = [
            f"S{season:02d}E{episode:02d}" for season, episode in sorted(missing_episodes)
        ]

        if missing_content:
            logger.warning(f"Missing episodes: {', '.join(missing_content)}")

        has_all = len(missing_content) == 0 and len(matched_files) > 0

        return MatchedTorrentFiles(
            has_all_requested_content=has_all,
            matched_files=matched_files,
            missing_content=missing_content,
            warnings=warnings,
            download_metadata=download_imdb_metadata,
            total_files=len(files)
        )
