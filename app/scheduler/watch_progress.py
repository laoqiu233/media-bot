"""Watch progress manager for tracking playback progress by file."""

import json
import logging
from datetime import datetime
from pathlib import Path

import aiofiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FileWatchProgress(BaseModel):
    """Watch progress for a specific file."""

    file_path: str = Field(..., description="Absolute path to the video file")
    position: float = Field(default=0.0, description="Last playback position in seconds")
    duration: float = Field(..., description="Total duration in seconds")
    last_watched: str = Field(
        default_factory=lambda: datetime.now().isoformat(), description="Last watch time"
    )

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.duration == 0:
            return 0.0
        return (self.position / self.duration) * 100

    @property
    def is_completed(self) -> bool:
        """Check if the file was watched to completion (>90%)."""
        return self.progress_percentage > 90.0

    @property
    def should_resume(self) -> bool:
        """Check if we should resume playback (between 5% and 90%)."""
        progress = self.progress_percentage
        return 5.0 < progress < 90.0


class WatchProgressManager:
    """Manages watch progress for video files."""

    def __init__(self, data_dir: Path):
        """Initialize watch progress manager.

        Args:
            data_dir: Directory for storing progress data
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.progress_file = self.data_dir / "file_watch_progress.json"

        # In-memory cache: {file_path: FileWatchProgress}
        self._progress_cache: dict[str, FileWatchProgress] = {}
        self._loaded = False

    async def load_progress(self):
        """Load watch progress from file."""
        if self._loaded:
            return

        if not self.progress_file.exists():
            self._loaded = True
            logger.info("No existing watch progress file, starting fresh")
            return

        try:
            async with aiofiles.open(self.progress_file, encoding="utf-8") as f:
                content = await f.read()
                data = json.loads(content)

                # Load progress cache
                for file_path, progress_data in data.items():
                    progress = FileWatchProgress(**progress_data)
                    self._progress_cache[file_path] = progress

            self._loaded = True
            logger.info(f"Loaded watch progress for {len(self._progress_cache)} files")

        except Exception as e:
            logger.error(f"Error loading watch progress: {e}")
            self._loaded = True

    async def save_progress(self):
        """Save watch progress to file."""
        if not self._loaded:
            return

        try:
            # Convert to JSON-serializable format
            data = {}
            for file_path, progress in self._progress_cache.items():
                data[file_path] = progress.model_dump(mode="json")

            async with aiofiles.open(self.progress_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))

            logger.debug("Saved watch progress to disk")

        except Exception as e:
            logger.error(f"Error saving watch progress: {e}")

    async def get_progress(self, file_path: Path | str) -> FileWatchProgress | None:
        """Get watch progress for a file.

        Args:
            file_path: Path to the video file

        Returns:
            FileWatchProgress or None if no progress saved
        """
        if not self._loaded:
            await self.load_progress()

        file_path_str = str(file_path)
        return self._progress_cache.get(file_path_str)

    async def update_progress(
        self,
        file_path: Path | str,
        position: float,
        duration: float,
    ):
        """Update watch progress for a file.

        Args:
            file_path: Path to the video file
            position: Current playback position in seconds
            duration: Total duration in seconds
        """
        if not self._loaded:
            await self.load_progress()

        file_path_str = str(file_path)

        # Create or update progress
        progress = FileWatchProgress(
            file_path=file_path_str,
            position=position,
            duration=duration,
        )

        self._progress_cache[file_path_str] = progress

        # Save to disk
        await self.save_progress()

        logger.info(
            f"Updated progress for file {Path(file_path).name}: "
            f"{progress.progress_percentage:.1f}% ({int(position)}s / {int(duration)}s)"
        )

    async def clear_progress(self, file_path: Path | str):
        """Clear watch progress for a file.

        Args:
            file_path: Path to the video file
        """
        if not self._loaded:
            await self.load_progress()

        file_path_str = str(file_path)

        if file_path_str in self._progress_cache:
            del self._progress_cache[file_path_str]
            await self.save_progress()
            logger.info(f"Cleared progress for file {Path(file_path).name}")

    async def get_recent_files(self, limit: int = 10) -> list[FileWatchProgress]:
        """Get recently watched files.

        Args:
            limit: Maximum number of files to return

        Returns:
            List of FileWatchProgress sorted by last_watched (most recent first)
        """
        if not self._loaded:
            await self.load_progress()

        all_progress = list(self._progress_cache.values())

        # Sort by last watched time (most recent first)
        all_progress.sort(key=lambda p: p.last_watched, reverse=True)

        return all_progress[:limit]


# Global instance
_watch_progress_manager: WatchProgressManager | None = None


def get_watch_progress_manager(data_dir: Path) -> WatchProgressManager:
    """Get or create the global watch progress manager instance.

    Args:
        data_dir: Data directory path

    Returns:
        WatchProgressManager instance
    """
    global _watch_progress_manager
    if _watch_progress_manager is None:
        _watch_progress_manager = WatchProgressManager(data_dir)
    return _watch_progress_manager

