"""Torrent search functionality using public APIs and web scrapers."""

import asyncio
import logging
from pathlib import Path
import re
from urllib.parse import quote

import aiohttp
from py_rutracker import AsyncRuTrackerClient

from app.config import Config
from app.library.models import VideoQuality, DownloadIMDbMetadata

from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TorrentSearchResult:
    """Torrent search result model."""

    title: str
    magnet_link: str | None
    torrent_file_link: str | None
    size: str
    seeders: int
    leechers: int
    source: str
    quality: VideoQuality

    async def fetch_torrent_file(self) -> Path:
        raise NotImplementedError("Subclasses must implement this method")


class RuTrackerTorrentSearchResult(TorrentSearchResult):
    def __init__(self, config: Config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.downloaded_torrent_file_path: Path | None = None

    async def fetch_torrent_file(self) -> Path:
        if self.downloaded_torrent_file_path is not None:
            return self.downloaded_torrent_file_path

        if self.torrent_file_link is None:
            raise ValueError("Torrent file link is not set")

        if (
            self.config.tracker.username is None
            or self.config.tracker.password is None
        ):
            raise ValueError("RuTracker credentials are not set")

        async with AsyncRuTrackerClient(
            self.config.tracker.username,
            self.config.tracker.password,
            self.config.tracker.proxy or "",
        ) as client:
            content = await client.download(self.torrent_file_link)
            temp_dir = Path("/tmp")
            temp_file = temp_dir / f"torrent_search_{hash(self.torrent_file_link)}.torrent"
            temp_file.write_bytes(content)
            self.downloaded_torrent_file_path = temp_file
            return temp_file


class TorrentSearcher:
    """Search for torrents from various public sources."""

    def __init__(self, config: Config):
        """Initialize torrent searcher."""
        self.config = config
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def search(self, provider: str, query: DownloadIMDbMetadata, limit: int = 20) -> list[TorrentSearchResult]:
        """Search for torrents across multiple sources.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of torrent search results
        """
        logger.info(f"Searching torrents for: {query}")

        # Search multiple sources in parallel
        tasks = []
        if provider == "yts":
            tasks.append(self._search_yts(query, limit))
        elif provider == "rutracker":
            tasks.append(self._search_tracker(query, limit))

        results = []
        try:
            search_results = await asyncio.gather(*tasks, return_exceptions=True)

            for source_results in search_results:
                if isinstance(source_results, Exception):
                    raise source_results
                if isinstance(source_results, list):
                    results.extend(source_results)

        except Exception as e:
            logger.error(f"Error during search: {e}")
            raise

        # Sort by seeders (descending) and return top results
        results.sort(key=lambda x: x.seeders, reverse=True)
        return results[:limit]

    async def _search_yts(self, query: DownloadIMDbMetadata, limit: int) -> list[TorrentSearchResult]:
        """Search YTS.mx using their API.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        results = []
        encoded_query = quote(str(query))
        url = f"https://yts.mx/api/v2/list_movies.json?query_term={encoded_query}&limit={limit}"

        try:
            async with (
                aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                session.get(url) as response,
            ):
                if response.status != 200:
                    logger.warning(f"YTS returned status {response.status}")
                    return results

                data = await response.json()

                # Check if we got valid data
                if data.get("status") != "ok":
                    logger.warning("YTS API returned error status")
                    return results

                movies = data.get("data", {}).get("movies", [])
                if not movies:
                    logger.info("No results found on YTS")
                    return results

                for movie in movies:
                    try:
                        title_base = movie.get("title", "Unknown")
                        year = movie.get("year", "")

                        # YTS provides multiple torrents per movie (different qualities)
                        torrents = movie.get("torrents", [])

                        for torrent in torrents:
                            quality = torrent.get("quality", "Unknown")
                            size = torrent.get("size", "Unknown")
                            seeds = torrent.get("seeds", 0)
                            peers = torrent.get("peers", 0)
                            hash_code = torrent.get("hash", "")

                            # Construct magnet link
                            if not hash_code:
                                continue

                            title = f"{title_base} ({year}) [{quality}]"
                            magnet = f"magnet:?xt=urn:btih:{hash_code}&dn={quote(title)}&tr=udp://open.demonii.com:1337/announce&tr=udp://tracker.openbittorrent.com:80&tr=udp://tracker.coppersurfer.tk:6969&tr=udp://glotorrents.pw:6969/announce&tr=udp://tracker.opentrackr.org:1337/announce&tr=udp://torrent.gresille.org:80/announce&tr=udp://p4p.arenabg.com:1337&tr=udp://tracker.leechers-paradise.org:6969"

                            result = TorrentSearchResult(
                                title=title,
                                torrent_file_link=None,
                                magnet_link=magnet,
                                size=size,
                                seeders=seeds,
                                leechers=peers,
                                source="YTS",
                                quality=self._map_yts_quality(quality),
                            )
                            results.append(result)

                    except Exception as e:
                        logger.debug(f"Error parsing YTS movie: {e}")
                        continue

        except Exception as e:
            logger.error(f"Error searching YTS: {e}")
            raise

        logger.info(f"Found {len(results)} results from YTS")
        return results

    def _map_yts_quality(self, yts_quality: str) -> VideoQuality:
        """Map YTS quality string to VideoQuality enum.

        Args:
            yts_quality: YTS quality string (e.g., "720p", "1080p", "2160p")

        Returns:
            Video quality enum
        """
        quality_map = {
            "2160p": VideoQuality.UHD_4K,
            "1080p": VideoQuality.HD_1080,
            "720p": VideoQuality.HD_720,
            "480p": VideoQuality.SD,
        }
        return quality_map.get(yts_quality, VideoQuality.UNKNOWN)

    def _generate_russian_query(self, query: DownloadIMDbMetadata) -> str:
        """Generate Russian query by replacing English keywords with Russian equivalents.

        Args:
            query: Download metadata object

        Returns:
            Query string with Russian keywords
        """
        # Convert query to string using its __str__ method
        query_str = str(query)

        # Replace English keywords with Russian equivalents
        query_str = query_str.replace(" season ", " сезон ")
        query_str = query_str.replace(" episode ", " серия ")

        return query_str

    async def _search_tracker(self, query: DownloadIMDbMetadata, limit: int) -> list[TorrentSearchResult]:
        results = []

        # Generate Russian query for RuTracker (replace English keywords with Russian)
        search_query = self._generate_russian_query(query)
        logger.info(f"Generated Russian query for RuTracker: {search_query}")

        try:
            # Check environment variables directly in case credentials were updated
            import os
            username = self.config.tracker.username or os.getenv("TRACKER_USERNAME")
            password = self.config.tracker.password or os.getenv("TRACKER_PASSWORD")
            proxy = self.config.tracker.proxy or os.getenv("TRACKER_PROXY")
            
            if not username or not password:
                logger.error("RuTracker credentials not configured. Please set TRACKER_USERNAME and TRACKER_PASSWORD.")
                return results
            
            async with AsyncRuTrackerClient(
                username,
                password,
                self.config.tracker.proxy or "",
            ) as client:
                raw_results = await client.search_all_pages(search_query)

                for result in raw_results:
                    results.append(
                        RuTrackerTorrentSearchResult(
                            config=self.config,
                            title=result.title,
                            magnet_link=None,
                            torrent_file_link=result.download_url,
                            size=f"{result.size} {result.unit}",
                            seeders=result.seedmed,
                            leechers=result.leechmed,
                            source="RuTracker",
                            quality=self._detect_quality(result.title),
                        )
                    )

        except Exception as e:
            logger.error(f"Error searching RuTracker: {e}")
            raise
        logger.info(f"Found {len(results)} results from RuTracker")
        return results

    def _detect_quality(self, title: str) -> VideoQuality:
        """Detect video quality from title.

        Args:
            title: Torrent title

        Returns:
            Video quality
        """
        title_lower = title.lower()

        if "2160p" in title_lower or "4k" in title_lower:
            return VideoQuality.UHD_4K
        elif "1080p" in title_lower:
            return VideoQuality.HD_1080
        elif "720p" in title_lower:
            return VideoQuality.HD_720
        elif "480p" in title_lower or "sd" in title_lower:
            return VideoQuality.SD

        return VideoQuality.UNKNOWN
