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
        self.timeout = 60  # seconds - increased for slower magnet links
        # Note: Session is already configured by TorrentDownloader with DHT, LSD, etc.

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

        handle = None
        try:
            # For metadata fetching, we use add_magnet_uri which is simpler
            # DON'T pause - we need it active to connect to peers and fetch metadata

            # Parse magnet URI to get add_torrent_params
            logger.info("Parsing magnet URI...")
            params = lt.parse_magnet_uri(magnet_link)

            # Set save_path (required by libtorrent) using attribute assignment
            logger.info("Setting save_path to /tmp...")
            try:
                params.save_path = "/tmp"
                logger.info("save_path set successfully")
            except Exception as e:
                logger.error(f"Failed to set save_path on parsed params: {e}", exc_info=True)
                raise

            # Add torrent to session (will be active to connect to peers for metadata)
            logger.info("Adding torrent to session...")
            try:
                handle = self.session.add_torrent(params)
                logger.info("Torrent added successfully")
            except Exception as e:
                logger.error(f"Failed to add torrent to session: {e}", exc_info=True)
                raise

            if not handle:
                raise Exception("Failed to add torrent - all API methods failed")

            logger.info(f"Added magnet link, waiting for metadata (timeout: {self.timeout}s)...")

            # Wait for metadata with timeout and progress logging
            start_time = asyncio.get_event_loop().time()
            last_log_time = start_time

            while not handle.has_metadata():
                await asyncio.sleep(0.5)  # Check every 0.5 seconds
                elapsed = asyncio.get_event_loop().time() - start_time

                # Log progress every 5 seconds
                if elapsed - (last_log_time - start_time) >= 5:
                    status = handle.status()
                    logger.info(
                        f"Waiting for metadata... ({int(elapsed)}s elapsed, "
                        f"peers: {status.num_peers}, seeds: {status.num_seeds})"
                    )
                    last_log_time = asyncio.get_event_loop().time()

                if elapsed > self.timeout:
                    status = handle.status()
                    error_msg = (
                        f"Metadata fetch timed out after {self.timeout}s. "
                        f"Final stats - peers: {status.num_peers}, seeds: {status.num_seeds}"
                    )
                    logger.error(error_msg)
                    raise TimeoutError(error_msg)

            # Get torrent info
            torrent_info = handle.torrent_file()

            if not torrent_info:
                raise Exception("Failed to get torrent info from handle")

            logger.info(
                f"Successfully fetched metadata: {torrent_info.name()}, "
                f"{torrent_info.num_files()} files"
            )
            return torrent_info

        except TimeoutError:
            raise
        except Exception as e:
            logger.error(f"Error fetching metadata from magnet: {e}", exc_info=True)
            raise
        finally:
            # Clean up - remove torrent handle
            if handle is not None:
                try:
                    self.session.remove_torrent(handle)
                except Exception as e:
                    logger.warning(f"Error removing torrent handle: {e}")

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
