"""Torrent downloader using libtorrent."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

try:
    import libtorrent as lt
except ImportError:
    lt = None

from app.library.models import DownloadTask

logger = logging.getLogger(__name__)


class TorrentDownloader:
    """Manages torrent downloads using libtorrent."""

    def __init__(self, download_path: Path):
        """Initialize torrent downloader.

        Args:
            download_path: Directory for downloading torrents
        """
        if lt is None:
            raise RuntimeError(
                "libtorrent is not installed. Please install it: pip install libtorrent"
            )

        self.download_path = download_path
        self.download_path.mkdir(parents=True, exist_ok=True)

        # Initialize libtorrent session with settings
        try:
            # Try the newer API (libtorrent 2.x)
            settings = lt.session_params()
            settings.settings.user_agent = "MediaBot/1.0"
            self.session = lt.session(settings)
        except (AttributeError, TypeError):
            # Fall back to older API (libtorrent 1.x)
            self.session = lt.session()
            try:
                self.session.listen_on(6881, 6891)
            except AttributeError:
                # Even older API
                pass

        # Add DHT routers
        try:
            self.session.add_dht_router("router.bittorrent.com", 6881)
            self.session.add_dht_router("router.utorrent.com", 6881)
            self.session.add_dht_router("dht.transmissionbt.com", 6881)
        except AttributeError:
            # DHT router methods not available in this version
            logger.warning("DHT router configuration not available in this libtorrent version")

        # Storage for active downloads
        self.downloads: Dict[str, Dict] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_download_complete = None  # Callback for completed downloads

    def set_completion_callback(self, callback):
        """Set callback to be called when a download completes.
        
        Args:
            callback: Async function(task_id, download_info)
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

    async def add_download(self, magnet_link: str, name: str) -> str:
        """Add a new torrent download.

        Args:
            magnet_link: Magnet link
            name: Display name for the download

        Returns:
            Download task ID
        """
        task_id = str(uuid4())

        try:
            # Parse magnet link
            params = lt.parse_magnet_uri(magnet_link)

            # Add torrent to session
            params.save_path = str(self.download_path)

            # Add the torrent
            handle = self.session.add_torrent(params)

            # Store download info
            self.downloads[task_id] = {
                "handle": handle,
                "name": name,
                "magnet_link": magnet_link,
                "created_at": datetime.now(),
            }

            logger.info(f"Added torrent download: {name} (ID: {task_id})")

            # Start monitoring if not already running
            self.start_monitoring()

            return task_id

        except Exception as e:
            logger.error(f"Error adding torrent download: {e}")
            raise

    async def _monitor_downloads(self):
        """Monitor all active downloads."""
        while True:
            try:
                await asyncio.sleep(2)  # Update every 2 seconds

                for task_id, download_info in list(self.downloads.items()):
                    handle = download_info["handle"]

                    if not handle.is_valid():
                        continue

                    status = handle.status()

                    # Update download status
                    download_info["status"] = self._get_status_string(status)
                    download_info["progress"] = status.progress * 100
                    download_info["download_rate"] = status.download_rate
                    download_info["upload_rate"] = status.upload_rate
                    download_info["num_seeds"] = status.num_seeds
                    download_info["num_peers"] = status.num_peers
                    download_info["total_done"] = status.total_done
                    download_info["total_wanted"] = status.total_wanted

                    # Calculate ETA
                    if status.download_rate > 0:
                        remaining = status.total_wanted - status.total_done
                        eta = remaining / status.download_rate
                        download_info["eta"] = int(eta)
                    else:
                        download_info["eta"] = None

                    # Check if completed
                    if status.is_seeding or status.progress >= 1.0:
                        # Only process once
                        if "completed_at" not in download_info:
                            logger.info(
                                f"Download completed: {download_info['name']} (ID: {task_id})"
                            )
                            download_info["completed_at"] = datetime.now()
                            
                            # Trigger callback if set
                            if hasattr(self, '_on_download_complete'):
                                try:
                                    await self._on_download_complete(task_id, download_info)
                                except Exception as e:
                                    logger.error(f"Error in download complete callback: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring downloads: {e}")

    def _get_status_string(self, status) -> str:
        """Get human-readable status string.

        Args:
            status: libtorrent status object

        Returns:
            Status string
        """
        if status.paused:
            return "paused"
        elif status.is_seeding:
            return "completed"
        elif status.state in [
            lt.torrent_status.downloading,
            lt.torrent_status.downloading_metadata,
        ]:
            return "downloading"
        elif status.state == lt.torrent_status.checking_files:
            return "checking"
        else:
            return "queued"

    async def get_task_status(self, task_id: str) -> Optional[DownloadTask]:
        """Get status of a download task.

        Args:
            task_id: Task ID

        Returns:
            DownloadTask or None
        """
        if task_id not in self.downloads:
            return None

        download_info = self.downloads[task_id]

        return DownloadTask(
            id=task_id,
            torrent_name=download_info["name"],
            magnet_link=download_info["magnet_link"],
            status=download_info.get("status", "queued"),
            progress=download_info.get("progress", 0.0),
            download_speed=download_info.get("download_rate", 0.0),
            upload_speed=download_info.get("upload_rate", 0.0),
            seeders=download_info.get("num_seeds", 0),
            peers=download_info.get("num_peers", 0),
            downloaded_bytes=download_info.get("total_done", 0),
            total_bytes=download_info.get("total_wanted", 0),
            eta=download_info.get("eta"),
            save_path=self.download_path,
            created_at=download_info["created_at"],
            completed_at=download_info.get("completed_at"),
        )

    async def get_all_tasks(self) -> List[DownloadTask]:
        """Get all download tasks.

        Returns:
            List of download tasks
        """
        tasks = []
        for task_id in self.downloads.keys():
            task = await self.get_task_status(task_id)
            if task:
                tasks.append(task)
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
            handle = self.downloads[task_id]["handle"]
            handle.pause()
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
            handle = self.downloads[task_id]["handle"]
            handle.resume()
            logger.info(f"Resumed download: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            return False

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
            handle = self.downloads[task_id]["handle"]

            # Remove from session
            if delete_files:
                self.session.remove_torrent(handle, lt.session.delete_files)
            else:
                self.session.remove_torrent(handle)

            # Remove from tracking
            del self.downloads[task_id]

            logger.info(f"Removed download: {task_id}")
            return True

        except Exception as e:
            logger.error(f"Error removing download: {e}")
            return False

    def get_download_path(self, task_id: str) -> Optional[Path]:
        """Get the download path for a completed task.

        Args:
            task_id: Task ID

        Returns:
            Path to downloaded files or None
        """
        if task_id not in self.downloads:
            return None

        try:
            handle = self.downloads[task_id]["handle"]
            torrent_info = handle.torrent_file()

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
        for download_info in self.downloads.values():
            try:
                handle = download_info["handle"]
                if handle.is_valid():
                    handle.save_resume_data()
            except Exception as e:
                logger.error(f"Error saving resume data: {e}")

        # Wait a bit for resume data to be saved
        # In production, you'd want to handle this more gracefully
        import time

        time.sleep(1)

        logger.info("Torrent downloader shut down")


# Global downloader instance
downloader: Optional[TorrentDownloader] = None


def get_downloader(download_path: Path) -> TorrentDownloader:
    """Get or create the global downloader instance.

    Args:
        download_path: Download directory path

    Returns:
        TorrentDownloader instance
    """
    global downloader
    if downloader is None:
        downloader = TorrentDownloader(download_path)
    return downloader

