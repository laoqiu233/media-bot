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

    async def search(self, query: str, limit: int = 20) -> list[TorrentSearchResult]:
        """Search for torrents across multiple sources.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of torrent search results
        """
        logger.info(f"Searching torrents for: {query}")

        # Search multiple sources in parallel
        tasks = [
            self._search_tracker(query, limit),
        ]

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
            async with AsyncRuTrackerClient(self.config.tracker.username, self.config.tracker.password, self.config.tracker.proxy) as client:
                raw_results = await client.search_all_pages(query)
                
                for result in raw_results:
                    results.append(TorrentSearchResult(
                        title=result.title,
                        magnet_link=result.download_url,
                        size=str(result.size),
                        seeders=result.seedmed,
                        leechers=result.leechmed,
                        upload_date=result.added,
                        source='RuTracker',
                        quality=VideoQuality.UNKNOWN
                    ))
                    
        except Exception as e:
            logger.error(f"Error searching RuTracker: {e}")
        logger.info(f"Found {len(results)} results from RuTracker")
        return results

    async def _search_piratebay(self, query: str, limit: int) -> list[TorrentSearchResult]:
        """Search The Pirate Bay (using proxy/mirror).

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        results = []

        # Note: TPB is frequently blocked/down. Using a common mirror.
        # In production, you'd want to try multiple mirrors/proxies
        mirrors = [
            "https://thepiratebay.org",
            "https://tpb.party",
            "https://thepiratebay10.org",
        ]

        encoded_query = quote(query)

        for mirror in mirrors:
            try:
                url = f"{mirror}/search/{encoded_query}/1/99/0"

                async with (
                    aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                    session.get(url) as response,
                ):
                    if response.status != 200:
                        continue

                    html = await response.text()
                    soup = BeautifulSoup(html, "lxml")

                    # Find search results
                    rows = soup.find_all("tr")

                    for row in rows[:limit]:
                        try:
                            # Find torrent name
                            name_cell = row.find("a", class_="detLink")
                            if not name_cell:
                                continue

                            title = name_cell.text.strip()

                            # Find magnet link
                            magnet_link_elem = row.find("a", href=re.compile(r"^magnet:\?"))
                            if not magnet_link_elem:
                                continue

                            magnet = magnet_link_elem["href"]

                            # Find seeders/leechers
                            font_cells = row.find_all("td", align="right")
                            seeders = 0
                            leechers = 0
                            if len(font_cells) >= 2:
                                try:
                                    seeders = int(font_cells[0].text.strip())
                                    leechers = int(font_cells[1].text.strip())
                                except ValueError:
                                    pass

                            # Find size
                            desc_cell = row.find("font", class_="detDesc")
                            size = "Unknown"
                            if desc_cell:
                                size_match = re.search(
                                    r"Size\s+([\d.]+\s*[KMGT]iB)",
                                    desc_cell.text,
                                )
                                if size_match:
                                    size = size_match.group(1)

                            result = TorrentSearchResult(
                                title=title,
                                magnet_link=magnet,
                                size=size,
                                seeders=seeders,
                                leechers=leechers,
                                source="ThePirateBay",
                                quality=self._detect_quality(title),
                            )
                            results.append(result)

                        except Exception as e:
                            logger.debug(f"Error parsing TPB row: {e}")
                            continue

                    if results:
                        logger.info(f"Found {len(results)} results from TPB")
                        return results

            except Exception as e:
                logger.debug(f"Error searching TPB mirror {mirror}: {e}")
                continue

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

