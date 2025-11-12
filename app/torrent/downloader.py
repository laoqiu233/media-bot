"""Torrent downloader using libtorrent."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from py_rutracker import AsyncRuTrackerClient

try:
    import libtorrent as lt
except ImportError:
    lt = None

from app.config import Config
from app.library.models import MatchedTorrentFiles
from app.torrent.searcher import TorrentSearchResult

from enum import Enum

logger = logging.getLogger(__name__)

class DownloadStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class DownloadState:
    """Internal download state including libtorrent handle."""

    # Core download info (required fields first)
    task_id: str
    handle: Any  # libtorrent handle object
    name: str
    created_at: datetime
    torrent: TorrentSearchResult
    validation_result: MatchedTorrentFiles

    # Runtime state (updated by monitoring loop)
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    download_rate: float = 0.0
    upload_rate: float = 0.0
    num_seeds: int = 0
    num_peers: int = 0
    total_done: int = 0
    total_wanted: int = 0
    eta: int | None = None
    completed_at: datetime | None = None


class TorrentDownloader:
    """Manages torrent downloads using libtorrent."""

    def __init__(self, config: Config, download_path: Path):
        """Initialize torrent downloader.

        Args:
            download_path: Directory for downloading torrents
        """
        self.config = config
        self.download_path = download_path
        self.download_path.mkdir(parents=True, exist_ok=True)
        download_path.joinpath("torrents").mkdir(exist_ok=True)

        # Initialize libtorrent session with settings
        try:
            # Try the newer API (libtorrent 2.x)
            settings = lt.session_params()
            settings.settings.user_agent = "MediaBot/1.0"
            self.session = lt.session(settings)
        except (AttributeError, TypeError):
            # Fall back to older API (libtorrent 1.x)
            self.session = lt.session()
            from contextlib import suppress

            with suppress(AttributeError):
                # Even older API
                self.session.listen_on(6881, 6891)

        # Add DHT routers
        try:
            self.session.add_dht_router("router.bittorrent.com", 6881)
            self.session.add_dht_router("router.utorrent.com", 6881)
            self.session.add_dht_router("dht.transmissionbt.com", 6881)
        except AttributeError:
            # DHT router methods not available in this version
            logger.warning("DHT router configuration not available in this libtorrent version")

        # Storage for active downloads
        self.downloads: dict[str, DownloadState] = {}
        self._monitor_task: asyncio.Task | None = None
        self._on_download_complete: Callable[[str, DownloadState], Awaitable[None]] | None = None

    def set_completion_callback(
        self, callback: Callable[[str, DownloadState], Awaitable[None]]
    ) -> None:
        """Set callback to be called when a download completes.

        Args:
            callback: Async function that takes (task_id: str, state: DownloadState)
        """
        self._on_download_complete = callback

    def start_monitoring(self):
        """Start monitoring downloads."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_downloads())
            logger.info("Download monitoring started")

    def stop_monitoring(self):
        """Stop monitoring downloads."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            logger.info("Download monitoring stopped")

    async def add_download(
        self,
        name: str,
        torrent: TorrentSearchResult,
        validation_result: MatchedTorrentFiles,
    ) -> str:
        task_id = str(uuid4())
        file_priorities = [0] * validation_result.total_files
        for file in validation_result.matched_files:
            file_priorities[file.file_index] = 1

        try:
            if torrent.magnet_link is not None:
                # Parse magnet link
                params = lt.parse_magnet_uri(torrent.magnet_link)
                params.save_path = str(self.download_path)
            else:
<<<<<<< HEAD
                try:
                    file_name = f"{torrent_file_link[-7:]}.torrent"
                    file_path = self.download_path.joinpath('torrents', file_name)
                    # Check environment variables directly in case credentials were updated
                    import os
                    username = self.config.tracker.username or os.getenv("TRACKER_USERNAME")
                    password = self.config.tracker.password or os.getenv("TRACKER_PASSWORD")
                    proxy = self.config.tracker.proxy or os.getenv("TRACKER_PROXY")
                    
                    if not username or not password:
                        logger.error("RuTracker credentials not configured. Please set TRACKER_USERNAME and TRACKER_PASSWORD.")
                        raise ValueError("RuTracker credentials not configured")
                    
                    async with AsyncRuTrackerClient(username, password, proxy) as client:
                        bytes = await client.download(torrent_file_link)
                        with open(file_path, mode='wb') as file:
                            file.write(bytes)
                    params = {
                        'save_path': str(self.download_path),
                        'ti': lt.torrent_info(str(file_path))
                    }
                    handle = self.session.add_torrent(params)
                except Exception as e:
                    logger.error(f"Error downloading from torrent file link: {e}")
                    raise
                        
=======
                torrent_file_path = await torrent.fetch_torrent_file()
                # Parse torrent info to set file priorities
                torrent_info = lt.torrent_info(str(torrent_file_path))
                params = {
                    "save_path": str(self.download_path),
                    "ti": torrent_info,
                }
            params["file_priorities"] = file_priorities
            handle = self.session.add_torrent(params)

>>>>>>> 08bf1eb (Added series downloading)
            # Store download state
            self.downloads[task_id] = DownloadState(
                task_id=task_id,
                handle=handle,
                name=name,
                torrent=torrent,
                validation_result=validation_result,
                created_at=datetime.now(),
            )

            logger.info(f"Added torrent download: {name} (ID: {task_id})")

            # Start monitoring if not already running
            self.start_monitoring()

            return task_id

        except Exception as e:
            logger.error(f"Error adding torrent download: {e}")
            raise
        return "todo"

    async def _monitor_downloads(self):
        """Monitor all active downloads."""
        while True:
            try:
                await asyncio.sleep(2)  # Update every 2 seconds

                for task_id, state in list(self.downloads.items()):
                    if not state.handle.is_valid():
                        continue

                    status = state.handle.status()

                    # Update download state
                    state.status = self._get_status_string(status)
                    state.progress = status.progress * 100
                    state.download_rate = status.download_rate
                    state.upload_rate = status.upload_rate
                    state.num_seeds = status.num_seeds
                    state.num_peers = status.num_peers
                    state.total_done = status.total_done
                    state.total_wanted = status.total_wanted

                    # Calculate ETA
                    if status.download_rate > 0:
                        remaining = status.total_wanted - status.total_done
                        eta = remaining / status.download_rate
                        state.eta = int(eta)
                    else:
                        state.eta = None

                    # Check if completed
                    if (status.is_seeding or status.progress >= 1.0) and state.completed_at is None:
                        logger.info(f"Download completed: {state.name} (ID: {task_id})")
                        state.completed_at = datetime.now()

                        # Trigger callback if set
                        if self._on_download_complete is not None:
                            try:
                                await self._on_download_complete(task_id, state)
                            except Exception as e:
                                logger.error(f"Error in download complete callback: {e}")

                        # Remove torrent to avoid seeding and free resources
                        try:
                            self.session.remove_torrent(state.handle)
                            del self.downloads[task_id]
                            logger.info(
                                f"Removed completed download from tracking: {state.name} (ID: {task_id})"
                            )
                        except Exception as e:
                            logger.error(f"Error removing completed torrent: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring downloads: {e}")

    def _get_status_string(self, status) -> DownloadStatus:
        """Get download status enum from libtorrent status.

        Args:
            status: libtorrent status object

        Returns:
            DownloadStatus enum value
        """
        if status.paused:
            return DownloadStatus.PAUSED
        elif status.is_seeding:
            return DownloadStatus.COMPLETED
        elif status.state in [
            lt.torrent_status.downloading,
            lt.torrent_status.downloading_metadata,
        ]:
            return DownloadStatus.DOWNLOADING
        elif status.state == lt.torrent_status.checking_files:
            return DownloadStatus.DOWNLOADING  # Checking is part of downloading
        else:
            return DownloadStatus.QUEUED

    async def get_all_tasks(self) -> list[DownloadState]:
        """Get all download tasks.

        Returns:
            List of download tasks
        """
        tasks = list(self.downloads.values())
        tasks.sort(key=lambda x: x.created_at)
        return tasks

    async def pause_download(self, task_id: str) -> bool:
        """Pause a download.

        Args:
            task_id: Task ID

        Returns:
            True if successful
        """
        if task_id not in self.downloads:
            return False

        try:
            state = self.downloads[task_id]
            state.handle.pause()
            logger.info(f"Paused download: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error pausing download: {e}")
            return False

    async def resume_download(self, task_id: str) -> bool:
        """Resume a paused download.

        Args:
            task_id: Task ID

        Returns:
            True if successful
        """
        if task_id not in self.downloads:
            return False

        try:
            state = self.downloads[task_id]
            state.handle.resume()
            logger.info(f"Resumed download: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            return False

    async def pause_all_downloads(self) -> int:
        """Pause all active downloads.

        Returns:
            Number of downloads paused
        """
        paused_count = 0
        for task_id, state in list(self.downloads.items()):
            try:
                if state.handle.is_valid():
                    state.handle.pause()
                    paused_count += 1
            except Exception as e:
                logger.error(f"Error pausing download {task_id}: {e}")

        if paused_count > 0:
            logger.info(f"Paused all downloads ({paused_count} downloads paused)")
        return paused_count

    async def resume_all_downloads(self) -> int:
        """Resume all paused downloads.

        Returns:
            Number of downloads resumed
        """
        resumed_count = 0
        for task_id, state in list(self.downloads.items()):
            try:
                if state.handle.is_valid():
                    state.handle.resume()
                    resumed_count += 1
            except Exception as e:
                logger.error(f"Error resuming download {task_id}: {e}")

        if resumed_count > 0:
            logger.info(f"Resumed all downloads ({resumed_count} downloads resumed)")
        return resumed_count

    async def remove_download(self, task_id: str, delete_files: bool = False) -> bool:
        """Remove a download.

        Args:
            task_id: Task ID
            delete_files: Whether to delete downloaded files

        Returns:
            True if successful
        """
        if task_id not in self.downloads:
            return False

        try:
            state = self.downloads[task_id]

            # Remove from session
            if delete_files:
                self.session.remove_torrent(state.handle, lt.session.delete_files)
            else:
                self.session.remove_torrent(state.handle)

            # Remove from tracking
            del self.downloads[task_id]

            logger.info(f"Removed download: {task_id}")
            return True

        except Exception as e:
            logger.error(f"Error removing download: {e}")
            return False

    def get_download_path(self, task_id: str) -> Path | None:
        """Get the download path for a completed task.

        Args:
            task_id: Task ID

        Returns:
            Path to downloaded files or None
        """
        if task_id not in self.downloads:
            return None

        try:
            state = self.downloads[task_id]
            torrent_info = state.handle.torrent_file()

            if torrent_info:
                # Get the name of the torrent
                name = torrent_info.name()
                return self.download_path / name

        except Exception as e:
            logger.error(f"Error getting download path: {e}")

        return None

    def shutdown(self):
        """Shutdown the downloader."""
        self.stop_monitoring()

        # Save resume data for all torrents
        for state in self.downloads.values():
            try:
                if state.handle.is_valid():
                    state.handle.save_resume_data()
            except Exception as e:
                logger.error(f"Error saving resume data: {e}")

        # Wait a bit for resume data to be saved
        # In production, you'd want to handle this more gracefully
        import time

        time.sleep(1)

        logger.info("Torrent downloader shut down")


# Global downloader instance
downloader: TorrentDownloader | None = None


def get_downloader(config: Config) -> TorrentDownloader:
    """Get or create the global downloader instance.

    Args:
        download_path: Download directory path

    Returns:
        TorrentDownloader instance
    """
    global downloader
    if downloader is None:
        downloader = TorrentDownloader(config, config.media_library.download_path)
    return downloader
