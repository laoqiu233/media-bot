"""Series updater for detecting new episodes and monitoring downloads."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.library.models import MediaEntity, MediaType

logger = logging.getLogger(__name__)


class SeriesUpdater:
    """Manages automatic detection of new series episodes and download monitoring."""

    def __init__(
        self,
        library_manager: LibraryManager,
        imdb_client: IMDbClient,
        download_path: Path,
        bot_instance: Any | None = None,
    ):
        """Initialize series updater.

        Args:
            library_manager: Library manager instance
            imdb_client: IMDb client instance
            download_path: Path to download directory for monitoring
            bot_instance: Optional bot instance for sending notifications
        """
        self.library_manager = library_manager
        self.imdb_client = imdb_client
        self.download_path = download_path
        self.bot_instance = bot_instance

        # Background tasks
        self._imdb_polling_task: asyncio.Task | None = None
        self._download_monitor_task: asyncio.Task | None = None
        self._running = False

    def start(self):
        """Start background tasks."""
        if self._running:
            logger.warning("SeriesUpdater is already running")
            return

        self._running = True
        self._imdb_polling_task = asyncio.create_task(self._imdb_polling_loop())
        self._download_monitor_task = asyncio.create_task(self._download_monitor_loop())
        logger.info("SeriesUpdater started")

    def stop(self):
        """Stop background tasks."""
        self._running = False

        if self._imdb_polling_task and not self._imdb_polling_task.done():
            self._imdb_polling_task.cancel()

        if self._download_monitor_task and not self._download_monitor_task.done():
            self._download_monitor_task.cancel()

        logger.info("SeriesUpdater stopped")

    async def _imdb_polling_loop(self):
        """Poll IMDb API for new episodes every 6 hours."""
        while self._running:
            try:
                await asyncio.sleep(6 * 60 * 60)  # 6 hours
                await self._check_for_new_episodes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in IMDb polling loop: {e}", exc_info=True)
                # Wait a bit before retrying
                await asyncio.sleep(60)

    async def _check_for_new_episodes(self):
        """Check all ongoing series for new episodes."""
        logger.info("Checking for new episodes...")

        # Get all series entities
        all_entities = await self.library_manager.get_all_media_entities()
        ongoing_series = []

        for e in all_entities:
            if e.media_type != MediaType.SERIES:
                continue

            # Check if series is ongoing:
            # - If status is explicitly "ongoing" or "continuing"
            # - If status is None/empty and endYear is None (series hasn't ended)
            is_ongoing = e.status.lower() in ["ongoing", "continuing"] if e.status else True

            if is_ongoing:
                ongoing_series.append(e)

        logger.info(f"Found {len(ongoing_series)} ongoing series to check")

        for series in ongoing_series:
            try:
                await self._check_series_for_new_episodes(series)
            except Exception as e:
                logger.error(f"Error checking series {series.title}: {e}", exc_info=True)

    async def _check_series_for_new_episodes(self, series: MediaEntity):
        """Check a specific series for new episodes.

        Uses the seasons endpoint first for efficient checking, then fetches
        episodes only if there are potential changes.

        Args:
            series: Series MediaEntity
        """
        if not series.imdb_id:
            logger.warning(f"Series {series.title} has no IMDb ID, skipping")
            return

        # Step 1: Fetch seasons overview (lightweight check)
        imdb_seasons_data = await self.imdb_client.get_series_seasons(series.imdb_id)

        if not imdb_seasons_data:
            logger.debug(f"No season data available for {series.title}")
            return

        # Get existing seasons and episodes from library
        existing_seasons = await self.library_manager.get_series_seasons(series.id)
        existing_seasons_by_num: dict[int, MediaEntity] = {
            s.season_number or 0: s for s in existing_seasons
        }
        existing_episodes_by_season: dict[int, list[MediaEntity]] = {}

        for season in existing_seasons:
            episodes = await self.library_manager.get_season_episodes(season.id)
            existing_episodes_by_season[season.season_number or 0] = episodes

        # Step 2: Compare seasons to identify which ones might have new episodes
        seasons_to_check: list[int] = []
        imdb_seasons_by_num: dict[int, int] = {}  # season_num -> episode_count

        for season_data in imdb_seasons_data:
            try:
                season_num = season_data.season_number
                episode_count = season_data.episodeCount
                imdb_seasons_by_num[season_num] = episode_count

                # Check if this season needs investigation
                existing_season = existing_seasons_by_num.get(season_num)
                existing_episode_count = len(existing_episodes_by_season.get(season_num, []))

                # Need to check if:
                # - Season doesn't exist in library (new season)
                # - Episode count differs (might have new episodes)
                if not existing_season or existing_episode_count < episode_count:
                    seasons_to_check.append(season_num)
                    logger.debug(
                        f"Season {season_num} needs checking: "
                        f"existing={existing_episode_count}, imdb={episode_count}"
                    )
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Invalid season data: {season_data}, error: {e}")
                continue

        # If no seasons need checking, we're done
        if not seasons_to_check:
            logger.debug(f"No new episodes detected for {series.title} (all seasons up to date)")
            return

        # Step 3: Fetch episodes only for seasons that might have changes
        logger.info(
            f"Fetching episodes for {series.title} - checking {len(seasons_to_check)} season(s)"
        )
        episodes_data = await self.imdb_client.get_series_episodes(series.imdb_id)

        if not episodes_data:
            logger.debug(f"No episode data available for {series.title}")
            return

        # Step 4: Process episodes and identify new ones
        new_episodes = []

        for episode_data in episodes_data:
            # Get season and episode numbers from IMDbEpisode object
            season_num = episode_data.season
            episode_num = episode_data.episode

            if season_num is None or episode_num is None:
                logger.debug(
                    f"Skipping episode with missing season/episode number: {episode_data.id}"
                )
                continue

            # Only process episodes from seasons we're checking
            if season_num not in seasons_to_check:
                continue

            # Check if episode exists
            existing_episodes = existing_episodes_by_season.get(season_num, [])
            episode_exists = any(e.episode_number == episode_num for e in existing_episodes)

            if not episode_exists:
                # New episode detected
                new_episodes.append(
                    {
                        "season_num": season_num,
                        "episode_num": episode_num,
                        "title": episode_data.primaryTitle or "",
                        "release_date": None,  # IMDbEpisode doesn't have releaseDate
                        "episode_id": episode_data.id,
                    }
                )

        # Step 5: Create episode entities for new episodes
        for ep_data in new_episodes:
            await self._create_new_episode_entity(series, ep_data)

        if new_episodes:
            logger.info(
                f"Found {len(new_episodes)} new episodes for {series.title}, "
                f"sending notifications"
            )
            await self._notify_new_episodes(series, new_episodes)
        else:
            logger.debug(
                f"No new episodes found for {series.title} "
                f"(episode counts matched but episodes may have been reordered)"
            )

    async def _create_new_episode_entity(self, series: MediaEntity, ep_data: dict):
        """Create a new episode entity in the library.

        Args:
            series: Series MediaEntity
            ep_data: Episode data dict
        """
        # Get or create season
        seasons = await self.library_manager.get_series_seasons(series.id)
        season = next((s for s in seasons if s.season_number == ep_data["season_num"]), None)

        if not season:
            season = await self.library_manager.add_season(series.id, ep_data["season_num"])

        # Parse air date if available
        air_date = None
        release_date = ep_data.get("release_date")
        if release_date:
            try:
                # Handle releaseDate object with year, month, day
                if isinstance(release_date, dict):
                    year = release_date.get("year")
                    month = release_date.get("month", 1)
                    day = release_date.get("day", 1)
                    if year:
                        air_date = datetime(year=year, month=month, day=day)
                # Fallback: try parsing as ISO string
                elif isinstance(release_date, str):
                    air_date = datetime.fromisoformat(release_date.replace("Z", "+00:00"))
            except Exception as e:
                logger.debug(f"Could not parse release date: {release_date}, error: {e}")

        # Create episode entity
        await self.library_manager.add_episode(
            season.id,
            ep_data["episode_num"],
            episode_title=ep_data.get("title"),
            air_date=air_date,
        )

    async def _notify_new_episodes(self, series: MediaEntity, new_episodes: list[dict]):
        """Send notifications about new episodes.

        Args:
            series: Series MediaEntity
            new_episodes: List of new episode data dicts
        """
        # For now, just log - can be extended to send Telegram notifications
        # if bot_instance is provided
        for ep_data in new_episodes:
            logger.info(
                f"New episode: {series.title} "
                f"S{ep_data['season_num']:02d}E{ep_data['episode_num']:02d} - "
                f"{ep_data.get('title', 'Untitled')}"
            )

        # TODO: Send Telegram notification if bot_instance is available
        # This would require storing user preferences for which series to notify about

    async def _download_monitor_loop(self):
        """Monitor download directory for completed episode downloads every 5 minutes."""
        while self._running:
            try:
                await asyncio.sleep(5 * 60)  # 5 minutes
                await self._scan_downloads_for_episodes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in download monitor loop: {e}", exc_info=True)
                # Wait a bit before retrying
                await asyncio.sleep(60)

    async def _scan_downloads_for_episodes(self):
        """Scan download directory for episode files and match them to series."""
        if not self.download_path.exists():
            return

        logger.debug("Scanning downloads for episode files...")

        # Get all series
        all_entities = await self.library_manager.get_all_media_entities()
        series_list = [e for e in all_entities if e.media_type == MediaType.SERIES]

        # Scan download directory
        for item in self.download_path.iterdir():
            if not item.is_file():
                continue

            # Check if filename matches episode pattern
            episode_match = self._parse_episode_filename(item.name)
            if not episode_match:
                continue

            # Try to match to a series by checking if series title appears in filename
            matched_series = None
            for series in series_list:
                if series.title.lower() in item.name.lower():
                    matched_series = series
                    break

            if not matched_series:
                logger.debug(f"Could not match episode file to series: {item.name}")
                continue

            # Import the episode
            try:
                await self.library_manager.import_from_download(
                    download_path=item,
                    torrent_name=item.name,
                    metadata={
                        "series_imdb_id": matched_series.imdb_id,
                        "episode_title": None,  # Could be extracted from filename
                    },
                )
                logger.info(
                    f"Auto-imported episode: {matched_series.title} "
                    f"S{episode_match['season_num']:02d}E{episode_match['episode_num']:02d}"
                )
            except Exception as e:
                logger.error(f"Error importing episode file {item.name}: {e}")

    def _parse_episode_filename(self, filename: str) -> dict | None:
        """Parse episode information from filename.

        Args:
            filename: Filename to parse

        Returns:
            Dict with season_num and episode_num, or None if not an episode
        """
        # Common patterns: S01E01, s01e01, S1E1, 1x01, etc.
        patterns = [
            r"[Ss](\d+)[Ee](\d+)",  # S01E01
            r"(\d+)[Xx](\d+)",  # 1x01
            r"Season\s+(\d+).*Episode\s+(\d+)",  # Season 1 Episode 1
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return {"season_num": int(match.group(1)), "episode_num": int(match.group(2))}

        return None
