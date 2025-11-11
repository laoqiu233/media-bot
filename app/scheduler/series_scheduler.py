"""Series scheduler for tracking watched episodes and recommendations."""

import json
import logging
from datetime import datetime
from pathlib import Path

import aiofiles

from app.library.models import Episode, Series, UserWatchProgress

logger = logging.getLogger(__name__)


class SeriesScheduler:
    """Manages series watching progress and recommendations."""

    def __init__(self, data_dir: Path):
        """Initialize series scheduler.

        Args:
            data_dir: Directory for storing user progress data
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.progress_file = self.data_dir / "watch_progress.json"

        # In-memory storage
        self._user_progress: dict[int, dict[str, UserWatchProgress]] = {}
        self._loaded = False

    async def load_progress(self):
        """Load watch progress from file."""
        if not self.progress_file.exists():
            self._loaded = True
            return

        try:
            async with aiofiles.open(self.progress_file, encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)

                for user_id_str, media_progress in data.items():
                    user_id = int(user_id_str)
                    self._user_progress[user_id] = {}

                    for media_id, progress_data in media_progress.items():
                        progress = UserWatchProgress(**progress_data)
                        self._user_progress[user_id][media_id] = progress

            self._loaded = True
            logger.info(f"Loaded watch progress for {len(self._user_progress)} users")

        except Exception as e:
            logger.error(f"Error loading watch progress: {e}")
            self._loaded = True

    async def save_progress(self):
        """Save watch progress to file."""
        try:
            data = {}

            for user_id, media_progress in self._user_progress.items():
                data[str(user_id)] = {}
                for media_id, progress in media_progress.items():
                    data[str(user_id)][media_id] = progress.model_dump(mode="json")

            async with aiofiles.open(self.progress_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))

            logger.debug("Saved watch progress")

        except Exception as e:
            logger.error(f"Error saving watch progress: {e}")

    async def update_progress(
        self,
        user_id: int,
        media_id: str,
        position: int,
        duration: int,
        completed: bool = False,
    ):
        """Update watch progress for a user.

        Args:
            user_id: Telegram user ID
            media_id: Media item ID
            position: Current position in seconds
            duration: Total duration in seconds
            completed: Whether the media was completed
        """
        if not self._loaded:
            await self.load_progress()

        if user_id not in self._user_progress:
            self._user_progress[user_id] = {}

        progress = UserWatchProgress(
            user_id=user_id,
            media_id=media_id,
            position=position,
            duration=duration,
            completed=completed,
        )

        self._user_progress[user_id][media_id] = progress

        # Save to file
        await self.save_progress()

        logger.info(
            f"Updated progress for user {user_id}, media {media_id}: "
            f"{progress.progress_percentage:.1f}%"
        )

    async def get_progress(self, user_id: int, media_id: str) -> UserWatchProgress | None:
        """Get watch progress for a specific media item.

        Args:
            user_id: Telegram user ID
            media_id: Media item ID

        Returns:
            UserWatchProgress or None
        """
        if not self._loaded:
            await self.load_progress()

        return self._user_progress.get(user_id, {}).get(media_id)

    async def get_user_progress(self, user_id: int) -> list[UserWatchProgress]:
        """Get all watch progress for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of UserWatchProgress
        """
        if not self._loaded:
            await self.load_progress()

        user_progress = self._user_progress.get(user_id, {})
        return list(user_progress.values())

    async def get_next_episode(self, user_id: int, series: Series) -> Episode | None:
        """Get the next episode to watch for a series.

        Args:
            user_id: Telegram user ID
            series: Series object

        Returns:
            Next episode or None
        """
        if not series.episodes:
            return None

        if not self._loaded:
            await self.load_progress()

        # Find the last watched episode
        last_watched_episode: Episode | None = None
        last_season = 0
        last_episode = 0

        for episode in series.episodes:
            progress = await self.get_progress(user_id, episode.id)
            if (
                progress
                and progress.completed
                and (
                    episode.season_number > last_season
                    or episode.season_number == last_season
                    and episode.episode_number > last_episode
                )
            ):
                last_watched_episode = episode
                last_season = episode.season_number
                last_episode = episode.episode_number

        # If no episodes watched, return first episode
        if last_watched_episode is None:
            return series.episodes[0] if series.episodes else None

        # Find next episode
        for episode in series.episodes:
            if (
                episode.season_number > last_season
                or episode.season_number == last_season
                and episode.episode_number > last_episode
            ):
                return episode

        # All episodes watched
        return None

    async def get_continue_watching(self, user_id: int) -> list[UserWatchProgress]:
        """Get list of media items to continue watching.

        Args:
            user_id: Telegram user ID

        Returns:
            List of in-progress media items
        """
        if not self._loaded:
            await self.load_progress()

        progress_list = await self.get_user_progress(user_id)

        # Filter for items that are in progress (not completed, and have some progress)
        continue_watching = [
            p for p in progress_list if not p.completed and p.progress_percentage > 5
        ]

        # Sort by last watched time
        continue_watching.sort(key=lambda x: x.last_watched, reverse=True)

        return continue_watching

    async def mark_episode_watched(self, user_id: int, episode: Episode):
        """Mark an episode as watched.

        Args:
            user_id: Telegram user ID
            episode: Episode object
        """
        duration = episode.duration or 0
        await self.update_progress(
            user_id=user_id,
            media_id=episode.id,
            position=duration,
            duration=duration,
            completed=True,
        )

        logger.info(f"Marked episode as watched: {episode.title} (user: {user_id})")

    async def get_series_progress(self, user_id: int, series: Series) -> dict[str, any]:
        """Get overall progress for a series.

        Args:
            user_id: Telegram user ID
            series: Series object

        Returns:
            Dictionary with series progress information
        """
        if not series.episodes:
            return {
                "total_episodes": 0,
                "watched_episodes": 0,
                "progress_percentage": 0.0,
                "next_episode": None,
            }

        watched_count = 0
        for episode in series.episodes:
            progress = await self.get_progress(user_id, episode.id)
            if progress and progress.completed:
                watched_count += 1

        next_episode = await self.get_next_episode(user_id, series)

        return {
            "total_episodes": len(series.episodes),
            "watched_episodes": watched_count,
            "progress_percentage": (watched_count / len(series.episodes)) * 100,
            "next_episode": next_episode,
        }

    async def get_watching_series(self, user_id: int) -> list[str]:
        """Get list of series IDs that user is currently watching.

        Args:
            user_id: Telegram user ID

        Returns:
            List of series IDs
        """
        progress_list = await self.get_user_progress(user_id)

        # Extract unique series IDs from episode IDs
        series_ids = set()
        for progress in progress_list:
            if (
                not progress.completed
                and progress.progress_percentage > 0
                and "_s" in progress.media_id
            ):
                # Episode IDs are formatted as: {series_id}_s{season}e{episode}
                series_id = progress.media_id.split("_s")[0]
                series_ids.add(series_id)

        return list(series_ids)

    async def schedule_reminder(self, user_id: int, series_id: str, reminder_time: datetime):
        """Schedule a reminder for new episodes.

        Args:
            user_id: Telegram user ID
            series_id: Series ID
            reminder_time: When to send reminder

        Note:
            This is a placeholder for future implementation with telegram job_queue
        """
        # TODO: Implement with telegram job_queue
        logger.info(f"Reminder scheduled for user {user_id}, series {series_id} at {reminder_time}")

    async def get_recommendations_for_user(
        self, user_id: int, all_series: list[Series], limit: int = 5
    ) -> list[Series]:
        """Get series recommendations based on watch history.

        Args:
            user_id: Telegram user ID
            all_series: List of all available series
            limit: Maximum recommendations

        Returns:
            List of recommended series
        """
        # Simple recommendation: suggest series with similar genres
        watched_series_ids = await self.get_watching_series(user_id)

        if not watched_series_ids:
            # No watch history, return popular/recent series
            return all_series[:limit]

        # Get genres from watched series
        watched_genres = set()
        for series in all_series:
            if series.id in watched_series_ids:
                watched_genres.update(series.genres)

        # Find series with matching genres that user hasn't watched
        recommendations = []
        for series in all_series:
            if series.id not in watched_series_ids:
                # Calculate genre overlap
                overlap = len(set(series.genres) & watched_genres)
                if overlap > 0:
                    recommendations.append((series, overlap))

        # Sort by genre overlap
        recommendations.sort(key=lambda x: x[1], reverse=True)

        return [series for series, _ in recommendations[:limit]]


# Global scheduler instance
scheduler: SeriesScheduler | None = None


def get_scheduler(data_dir: Path) -> SeriesScheduler:
    """Get or create the global scheduler instance.

    Args:
        data_dir: Data directory path

    Returns:
        SeriesScheduler instance
    """
    global scheduler
    if scheduler is None:
        scheduler = SeriesScheduler(data_dir)
    return scheduler
