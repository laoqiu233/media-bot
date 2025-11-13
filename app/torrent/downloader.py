"""Torrent downloader using libtorrent."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiofiles
from pydantic import BaseModel, Field

try:
    import libtorrent as lt
except ImportError:
    lt = None

from app.config import Config
from app.library.models import MatchedTorrentFiles
from app.torrent.searcher import TorrentSearchResult

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"


class DownloadStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class PersistentDownloadState(BaseModel):
    """Serializable download state for persistence."""

    task_id: str = Field(..., description="Unique task identifier")
    name: str = Field(..., description="Download name")
    created_at: datetime = Field(..., description="Creation timestamp")
    status: str = Field(..., description="Download status")

    # Torrent info for resuming
    magnet_link: str | None = Field(None, description="Magnet link if available")
    torrent_file_path: str | None = Field(None, description="Path to torrent file")

    # Validation result for file priorities
    file_priorities: list[int] = Field(..., description="File priority list")

    # Metadata for completion callback (as JSON-serializable dicts)
    torrent_metadata: dict = Field(..., description="Serialized TorrentSearchResult")
    validation_metadata: dict = Field(..., description="Serialized MatchedTorrentFiles")

    class Config:
        use_enum_values = True


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

    def __init__(self, config: Config):
        """Initialize torrent downloader.

        Args:
            download_path: Directory for downloading torrents
        """
        self.config = config
        self.download_path = config.media_library.library_path / DOWNLOAD_DIR
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.download_path.joinpath("torrents").mkdir(exist_ok=True)

        # Path for persistent state
        data_dir = config.media_library.library_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = data_dir / "downloads.json"

        # Initialize libtorrent session with settings
        try:
            # Try the newer API (libtorrent 2.x)
            settings = lt.session_params()
            settings.settings.user_agent = "MediaBot/1.0"
            # Enable DHT, LSD, UPnP for better peer discovery
            settings.settings.enable_dht = True
            settings.settings.enable_lsd = True
            settings.settings.enable_upnp = True
            settings.settings.enable_natpmp = True
            self.session = lt.session(settings)
        except (AttributeError, TypeError):
            # Fall back to older API (libtorrent 1.x)
            self.session = lt.session()
            from contextlib import suppress

            with suppress(AttributeError):
                # Even older API
                self.session.listen_on(6881, 6891)
            
            # Try to enable DHT and other discovery for older API
            try:
                self.session.set_settings({
                    "enable_dht": True,
                    "enable_lsd": True,
                    "enable_upnp": True,
                    "enable_natpmp": True,
                })
            except (AttributeError, TypeError):
                logger.warning("Could not configure DHT settings for libtorrent 1.x")

        # Add DHT routers
        try:
            self.session.add_dht_router("router.bittorrent.com", 6881)
            self.session.add_dht_router("router.utorrent.com", 6881)
            self.session.add_dht_router("dht.transmissionbt.com", 6881)
            self.session.add_dht_router("dht.libtorrent.org", 25401)
            logger.info("DHT routers configured")
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

    def _serialize_torrent_result(self, torrent: TorrentSearchResult) -> dict:
        """Serialize TorrentSearchResult to dict.

        Args:
            torrent: TorrentSearchResult to serialize

        Returns:
            Dictionary representation
        """
        return {
            "title": torrent.title,
            "magnet_link": torrent.magnet_link,
            "torrent_file_link": torrent.torrent_file_link,
            "size": torrent.size,
            "seeders": torrent.seeders,
            "leechers": torrent.leechers,
            "source": torrent.source,
            "quality": torrent.quality.value,
        }

    def _serialize_validation_result(self, validation: MatchedTorrentFiles) -> dict:
        """Serialize MatchedTorrentFiles to dict.

        Args:
            validation: MatchedTorrentFiles to serialize

        Returns:
            Dictionary representation
        """
        return {
            "has_all_requested_content": validation.has_all_requested_content,
            "matched_files": [asdict(f) for f in validation.matched_files],
            "missing_content": validation.missing_content,
            "warnings": validation.warnings,
            "download_metadata": asdict(validation.download_metadata),
            "total_files": validation.total_files,
        }

    def _deserialize_download_metadata(self, metadata_dict: dict):
        """Deserialize download metadata from dict to proper dataclass.

        Args:
            metadata_dict: Dictionary representation of DownloadIMDbMetadata

        Returns:
            Reconstructed DownloadMovie/Series/Season/Episode object
        """
        from app.library.imdb_client import IMDbEpisode, IMDbSeason, IMDbTitle
        from app.library.models import (
            DownloadEpisode,
            DownloadMovie,
            DownloadSeason,
            DownloadSeries,
        )

        # Determine type by checking which fields exist
        if "episode" in metadata_dict:
            # DownloadEpisode
            return DownloadEpisode(
                series=IMDbTitle(**metadata_dict["series"]),
                season=IMDbSeason(**metadata_dict["season"]),
                episode=IMDbEpisode(**metadata_dict["episode"]),
            )
        elif "season" in metadata_dict:
            # DownloadSeason
            return DownloadSeason(
                series=IMDbTitle(**metadata_dict["series"]),
                season=IMDbSeason(**metadata_dict["season"]),
            )
        elif "series" in metadata_dict:
            # DownloadSeries
            return DownloadSeries(series=IMDbTitle(**metadata_dict["series"]))
        elif "movie" in metadata_dict:
            # DownloadMovie
            return DownloadMovie(movie=IMDbTitle(**metadata_dict["movie"]))
        else:
            raise ValueError(f"Unknown download metadata structure: {metadata_dict.keys()}")

    async def _save_download_state(self, task_id: str, state: DownloadState) -> None:
        """Save download state to persistent storage.

        Args:
            task_id: Task ID
            state: Download state to save
        """
        try:
            # Load existing states
            existing_states = {}
            if self.state_file.exists():
                async with aiofiles.open(self.state_file) as f:
                    content = await f.read()
                    if content:
                        existing_states = json.loads(content)

            # Get torrent file path if available
            torrent_file_path = None
            if state.torrent.torrent_file_link is not None:
                try:
                    torrent_file = await state.torrent.fetch_torrent_file()
                    torrent_file_path = str(torrent_file)
                except Exception as e:
                    logger.warning(f"Could not fetch torrent file for persistence: {e}")

            # Create persistent state
            file_priorities = [0] * state.validation_result.total_files
            for file in state.validation_result.matched_files:
                file_priorities[file.file_index] = 1

            persistent_state = PersistentDownloadState(
                task_id=task_id,
                name=state.name,
                created_at=state.created_at,
                status=state.status.value,
                magnet_link=state.torrent.magnet_link,
                torrent_file_path=torrent_file_path,
                file_priorities=file_priorities,
                torrent_metadata=self._serialize_torrent_result(state.torrent),
                validation_metadata=self._serialize_validation_result(state.validation_result),
            )

            # Add to states
            existing_states[task_id] = json.loads(persistent_state.model_dump_json())

            # Save to file
            async with aiofiles.open(self.state_file, "w") as f:
                await f.write(json.dumps(existing_states, indent=2, default=str))

            logger.debug(f"Saved download state: {task_id}")

        except Exception as e:
            logger.error(f"Error saving download state {task_id}: {e}")

    async def _remove_download_state(self, task_id: str) -> None:
        """Remove download state from persistent storage.

        Args:
            task_id: Task ID to remove
        """
        try:
            if not self.state_file.exists():
                return

            # Load existing states
            async with aiofiles.open(self.state_file) as f:
                content = await f.read()
                if not content:
                    return
                states = json.loads(content)

            # Remove state
            if task_id in states:
                del states[task_id]

                # Save updated states
                async with aiofiles.open(self.state_file, "w") as f:
                    await f.write(json.dumps(states, indent=2, default=str))

                logger.debug(f"Removed download state: {task_id}")

        except Exception as e:
            logger.error(f"Error removing download state {task_id}: {e}")

    async def _load_download_states(self) -> dict[str, PersistentDownloadState]:
        """Load all download states from persistent storage.

        Returns:
            Dictionary of task_id -> PersistentDownloadState
        """
        try:
            if not self.state_file.exists():
                return {}

            async with aiofiles.open(self.state_file) as f:
                content = await f.read()
                if not content:
                    return {}

                states_dict = json.loads(content)
                states = {}

                for task_id, state_data in states_dict.items():
                    try:
                        states[task_id] = PersistentDownloadState(**state_data)
                    except Exception as e:
                        logger.warning(f"Failed to parse state for {task_id}: {e}")
                        continue

                return states

        except Exception as e:
            logger.error(f"Error loading download states: {e}")
            return {}

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
                # Set file priorities using attribute assignment (not item assignment)
                params.file_priorities = file_priorities
            else:
                torrent_file_path = await torrent.fetch_torrent_file()
                # Parse torrent info to set file priorities
                torrent_info = lt.torrent_info(str(torrent_file_path))
                params = {
                    "save_path": str(self.download_path),
                    "ti": torrent_info,
                    "file_priorities": file_priorities,
                }
            handle = self.session.add_torrent(params)

            # Store download state
            download_state = DownloadState(
                task_id=task_id,
                handle=handle,
                name=name,
                torrent=torrent,
                validation_result=validation_result,
                created_at=datetime.now(),
            )
            self.downloads[task_id] = download_state

            # Save to persistent storage
            await self._save_download_state(task_id, download_state)

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

                        # Remove from persistent storage
                        await self._remove_download_state(task_id)

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

    async def get_task_status(self, task_id: str) -> DownloadState | None:
        """Get status of a specific download task.

        Args:
            task_id: Task ID

        Returns:
            DownloadState if found, None otherwise
        """
        return self.downloads.get(task_id)

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

            # Remove from persistent storage
            await self._remove_download_state(task_id)

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

    async def load_and_resume_downloads(self) -> int:
        """Load and resume all persisted downloads on startup.

        Returns:
            Number of downloads resumed
        """
        try:
            states = await self._load_download_states()

            if not states:
                logger.info("No persisted downloads to resume")
                return 0

            resumed_count = 0

            for task_id, persistent_state in states.items():
                try:
                    logger.info(f"Resuming download: {persistent_state.name} (ID: {task_id})")

                    # Reconstruct torrent search result (we need a minimal version)
                    # Note: We can't fully reconstruct the TorrentSearchResult object since it may
                    # have custom subclasses (like RuTrackerTorrentSearchResult), so we create
                    # a basic version
                    from app.library.models import VideoQuality

                    torrent_metadata = persistent_state.torrent_metadata
                    torrent = TorrentSearchResult(
                        title=torrent_metadata.get("title", ""),
                        magnet_link=persistent_state.magnet_link,
                        torrent_file_link=torrent_metadata.get("torrent_file_link"),
                        size=torrent_metadata.get("size", ""),
                        seeders=torrent_metadata.get("seeders", 0),
                        leechers=torrent_metadata.get("leechers", 0),
                        source=torrent_metadata.get("source", ""),
                        quality=VideoQuality(torrent_metadata.get("quality", "unknown")),
                    )

                    # Reconstruct validation result properly from serialized data
                    validation_metadata = persistent_state.validation_metadata

                    # Reconstruct download_metadata from dict
                    download_metadata = self._deserialize_download_metadata(
                        validation_metadata.get("download_metadata", {})
                    )

                    # Reconstruct matched_files
                    from app.library.imdb_client import IMDbEpisode, IMDbTitle
                    from app.library.models import FileMatch

                    matched_files = []
                    for file_dict in validation_metadata.get("matched_files", []):
                        file_match = FileMatch(
                            file_index=file_dict["file_index"],
                            file_path=file_dict["file_path"],
                            episode=(
                                IMDbEpisode(**file_dict["episode"])
                                if file_dict.get("episode")
                                else None
                            ),
                            movie=(
                                IMDbTitle(**file_dict["movie"]) if file_dict.get("movie") else None
                            ),
                        )
                        matched_files.append(file_match)

                    # Create fully reconstructed MatchedTorrentFiles
                    validation_result = MatchedTorrentFiles(
                        has_all_requested_content=validation_metadata.get(
                            "has_all_requested_content", True
                        ),
                        matched_files=matched_files,
                        missing_content=validation_metadata.get("missing_content", []),
                        warnings=validation_metadata.get("warnings", []),
                        download_metadata=download_metadata,
                        total_files=validation_metadata.get("total_files", 0),
                    )

                    # Re-add to libtorrent session
                    if persistent_state.magnet_link is not None:
                        params = lt.parse_magnet_uri(persistent_state.magnet_link)
                        params.save_path = str(self.download_path)
                        # Set file priorities using attribute assignment (not item assignment)
                        params.file_priorities = persistent_state.file_priorities
                        
                        # Check for fastresume data
                        fastresume_path = self.download_path / "torrents" / f"{task_id}.fastresume"
                        if fastresume_path.exists():
                            try:
                                with open(fastresume_path, "rb") as f:
                                    resume_data = f.read()
                                params.resume_data = resume_data
                                logger.debug(f"Loaded fastresume data for {task_id}")
                            except Exception as e:
                                logger.warning(f"Failed to load fastresume data for {task_id}: {e}")
                    elif persistent_state.torrent_file_path is not None:
                        torrent_file = Path(persistent_state.torrent_file_path)
                        if not torrent_file.exists():
                            logger.warning(f"Torrent file not found for {task_id}: {torrent_file}")
                            # Clean up state for missing file
                            await self._remove_download_state(task_id)
                            continue

                        torrent_info = lt.torrent_info(str(torrent_file))
                        params = {
                            "save_path": str(self.download_path),
                            "ti": torrent_info,
                            "file_priorities": persistent_state.file_priorities,
                        }
                        
                        # Check for fastresume data (for dict-based params)
                        fastresume_path = self.download_path / "torrents" / f"{task_id}.fastresume"
                        if fastresume_path.exists():
                            try:
                                with open(fastresume_path, "rb") as f:
                                    resume_data = f.read()
                                params["resume_data"] = resume_data
                                logger.debug(f"Loaded fastresume data for {task_id}")
                            except Exception as e:
                                logger.warning(f"Failed to load fastresume data for {task_id}: {e}")
                    else:
                        logger.warning(f"No torrent source for {task_id}, skipping")
                        await self._remove_download_state(task_id)
                        continue

                    handle = self.session.add_torrent(params)

                    # If it was paused, pause it again
                    if persistent_state.status == DownloadStatus.PAUSED.value:
                        handle.pause()

                    # Recreate DownloadState in memory
                    self.downloads[task_id] = DownloadState(
                        task_id=task_id,
                        handle=handle,
                        name=persistent_state.name,
                        torrent=torrent,
                        validation_result=validation_result,
                        created_at=persistent_state.created_at,
                        status=DownloadStatus(persistent_state.status),
                    )

                    resumed_count += 1
                    logger.info(f"Successfully resumed download: {persistent_state.name}")

                except Exception as e:
                    logger.error(f"Failed to resume download {task_id}: {e}", exc_info=True)
                    # Clean up failed state
                    await self._remove_download_state(task_id)
                    continue

            if resumed_count > 0:
                logger.info(f"Resumed {resumed_count} download(s)")
                # Start monitoring for resumed downloads
                self.start_monitoring()

            return resumed_count

        except Exception as e:
            logger.error(f"Error loading and resuming downloads: {e}", exc_info=True)
            return 0

    def shutdown(self):
        """Shutdown the downloader."""
        self.stop_monitoring()

        # Save resume data for all torrents
        outstanding_resume = []
        for task_id, state in self.downloads.items():
            try:
                if state.handle.is_valid():
                    state.handle.save_resume_data()
                    outstanding_resume.append(task_id)
            except Exception as e:
                logger.error(f"Error saving resume data for {task_id}: {e}")

        # Wait for resume data alerts
        if outstanding_resume:
            import time

            deadline = time.time() + 5  # Wait up to 5 seconds

            while outstanding_resume and time.time() < deadline:
                alerts = self.session.pop_alerts()
                for alert in alerts:
                    # Check for save_resume_data_alert
                    alert_type = type(alert).__name__

                    if alert_type == "save_resume_data_alert":
                        # Save the resume data to a file
                        try:
                            task_id = None
                            # Find task_id by matching handle
                            for tid, state in self.downloads.items():
                                if state.handle == alert.handle:
                                    task_id = tid
                                    break

                            if task_id:
                                fastresume_path = (
                                    self.download_path / "torrents" / f"{task_id}.fastresume"
                                )
                                # Get the resume data from the alert
                                # Different libtorrent versions have different ways to access this
                                try:
                                    # Try libtorrent 2.x API - params is a dict that needs encoding
                                    if hasattr(alert, "params"):
                                        # Use libtorrent's bencode function
                                        resume_data = lt.bencode(alert.params)
                                    # Try libtorrent 1.x API - resume_data is already bytes
                                    elif hasattr(alert, "resume_data"):
                                        resume_data = alert.resume_data
                                    else:
                                        logger.debug(
                                            f"Skipping fastresume for {task_id}: "
                                            f"unknown alert format"
                                        )
                                        if task_id in outstanding_resume:
                                            outstanding_resume.remove(task_id)
                                        continue

                                    # Write resume data to file (should be bytes now)
                                    with open(fastresume_path, "wb") as f:
                                        if isinstance(resume_data, bytes):
                                            f.write(resume_data)
                                        else:
                                            logger.debug(
                                                f"Skipping fastresume for {task_id}: "
                                                f"unexpected data type {type(resume_data)}"
                                            )
                                            if task_id in outstanding_resume:
                                                outstanding_resume.remove(task_id)
                                            continue

                                    logger.debug(f"Saved fastresume data for {task_id}")
                                    if task_id in outstanding_resume:
                                        outstanding_resume.remove(task_id)
                                except AttributeError as e:
                                    # libtorrent.bencode might not exist in some versions
                                    logger.debug(
                                        f"Skipping fastresume for {task_id}: bencode not available ({e})"
                                    )
                                    if task_id in outstanding_resume:
                                        outstanding_resume.remove(task_id)
                                except Exception as e:
                                    logger.warning(
                                        f"Error saving fastresume data for {task_id}: {e}"
                                    )
                                    if task_id in outstanding_resume:
                                        outstanding_resume.remove(task_id)
                        except Exception as e:
                            logger.error(f"Error writing fastresume data: {e}")

                    elif alert_type == "save_resume_data_failed_alert":
                        logger.warning(f"Failed to save resume data: {alert.message()}")

                time.sleep(0.1)

        logger.info("Torrent downloader shut down")
