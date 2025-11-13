"""Torrent metadata fetcher service."""

import asyncio
import logging
from pathlib import Path

try:
    import libtorrent as lt
except ImportError:
    lt = None

logger = logging.getLogger(__name__)


class TorrentMetadataFetcher:
    """Service for fetching torrent metadata from various sources."""

    def __init__(self, session):
        """Initialize metadata fetcher.

        Args:
            session: libtorrent session object
        """
        self.session = session
        self.timeout = 30  # seconds

    async def fetch_from_magnet(self, magnet_link: str):
        """Fetch torrent metadata from a magnet link.

        Args:
            magnet_link: Magnet URI

        Returns:
            libtorrent torrent_info object

        Raises:
            TimeoutError: If metadata fetch times out
            Exception: If fetch fails
        """
        logger.info("Fetching metadata from magnet link...")

        try:
            # Parse magnet link
            params = lt.parse_magnet_uri(magnet_link)
            params.save_path = "/tmp"

            # Add torrent in paused state (metadata only)
            params.flags = lt.torrent_flags.paused | lt.torrent_flags.upload_mode

            handle = self.session.add_torrent(params)

            # Wait for metadata with timeout
            start_time = asyncio.get_event_loop().time()
            while not handle.has_metadata():
                await asyncio.sleep(0.1)
                elapsed = asyncio.get_event_loop().time() - start_time

                if elapsed > self.timeout:
                    self.session.remove_torrent(handle)
                    raise TimeoutError(f"Metadata fetch timed out after {self.timeout}s")

            # Get torrent info
            torrent_info = handle.torrent_file()

            # Clean up - remove torrent
            self.session.remove_torrent(handle)

            logger.info("Successfully fetched metadata from magnet link")
            return torrent_info

        except TimeoutError:
            raise
        except Exception as e:
            logger.error(f"Error fetching metadata from magnet: {e}")
            raise

    async def fetch_from_file(self, torrent_file_path: Path):
        """Fetch torrent metadata from a .torrent file.

        Args:
            torrent_file_path: Path to .torrent file

        Returns:
            libtorrent torrent_info object

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: If parsing fails
        """
        logger.info(f"Fetching metadata from torrent file: {torrent_file_path}")

        try:
            if not torrent_file_path.exists():
                raise FileNotFoundError(f"Torrent file not found: {torrent_file_path}")

            # Parse torrent file
            torrent_info = lt.torrent_info(str(torrent_file_path))

            logger.info("Successfully parsed torrent file")
            return torrent_info

        except Exception as e:
            logger.error(f"Error parsing torrent file: {e}")
            raise
