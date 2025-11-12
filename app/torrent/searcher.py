"""Torrent search functionality using public APIs and web scrapers."""

import asyncio
import logging
import re
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from app.config import Config
from app.library.models import TorrentSearchResult, VideoQuality
from py_rutracker import AsyncRuTrackerClient

logger = logging.getLogger(__name__)


class TorrentSearcher:
    """Search for torrents from various public sources."""

    def __init__(self, config: Config):
        """Initialize torrent searcher."""
        self.config = config
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def search(self, provider: str, query: str, limit: int = 20) -> list[TorrentSearchResult]:
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
        if provider == 'yts':
            tasks.append(self._search_yts(query, limit))
        elif provider == 'rutracker':
            tasks.append(self._search_tracker(query, limit))

        results = []
        try:
            search_results = await asyncio.gather(*tasks, return_exceptions=True)

            for source_results in search_results:
                if isinstance(source_results, Exception):
                    logger.error(f"Search error: {source_results}")
                    continue
                if isinstance(source_results, list):
                    results.extend(source_results)

        except Exception as e:
            logger.error(f"Error during parallel search: {e}")

        # Sort by seeders (descending) and return top results
        results.sort(key=lambda x: x.seeders, reverse=True)
        return results[:limit]

    async def _search_yts(self, query: str, limit: int) -> list[TorrentSearchResult]:
        """Search YTS.mx using their API.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        results = []
        encoded_query = quote(query)
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

    async def _search_tracker(self, query: str, limit: int) -> list[TorrentSearchResult]:
        results = []
        try:
            # Check environment variables directly in case credentials were updated
            import os
            username = self.config.tracker.username or os.getenv("TRACKER_USERNAME")
            password = self.config.tracker.password or os.getenv("TRACKER_PASSWORD")
            proxy = self.config.tracker.proxy or os.getenv("TRACKER_PROXY")
            
            if not username or not password:
                logger.error("RuTracker credentials not configured. Please set TRACKER_USERNAME and TRACKER_PASSWORD.")
                return results
            
            async with AsyncRuTrackerClient(username, password, proxy) as client:
                raw_results = await client.search_all_pages(query)
                
                for result in raw_results:
                    results.append(TorrentSearchResult(
                        title=result.title,
                        magnet_link=None,
                        torrent_file_link=result.download_url,
                        size=f"{result.size} {result.unit}",
                        seeders=result.seedmed,
                        leechers=result.leechmed,
                        upload_date=result.added,
                        source='RuTracker',
                        quality=self._detect_quality(result.title),
                    ))
                    
        except Exception as e:
            logger.error(f"Error searching RuTracker: {e}")
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

    def _parse_size_to_bytes(self, size_str: str) -> int | None:
        """Parse size string to bytes.

        Args:
            size_str: Size string (e.g., "1.5 GB", "700 MB")

        Returns:
            Size in bytes or None
        """
        try:
            match = re.match(r"([\d.]+)\s*([KMGT])i?B", size_str, re.IGNORECASE)
            if not match:
                return None

            value = float(match.group(1))
            unit = match.group(2).upper()

            multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

            return int(value * multipliers.get(unit, 1))

        except Exception:
            return None

