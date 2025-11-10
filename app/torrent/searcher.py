"""Torrent search functionality using public APIs and web scrapers."""

import asyncio
import logging
import re
from typing import List
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from app.library.models import TorrentSearchResult, VideoQuality

logger = logging.getLogger(__name__)


class TorrentSearcher:
    """Search for torrents from various public sources."""

    def __init__(self):
        """Initialize torrent searcher."""
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def search(self, query: str, limit: int = 20) -> List[TorrentSearchResult]:
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
            self._search_1337x(query, limit),
            self._search_piratebay(query, limit),
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

    async def _search_1337x(self, query: str, limit: int) -> List[TorrentSearchResult]:
        """Search 1337x.to.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results
        """
        results = []
        encoded_query = quote(query)
        url = f"https://1337x.to/search/{encoded_query}/1/"

        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self.headers
            ) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"1337x returned status {response.status}")
                        return results

                    html = await response.text()
                    soup = BeautifulSoup(html, "lxml")

                    # Find torrent table
                    table = soup.find("table", class_="table-list")
                    if not table:
                        logger.warning("Could not find torrent table on 1337x")
                        return results

                    rows = table.find("tbody").find_all("tr")

                    for row in rows[:limit]:
                        try:
                            # Extract data from row
                            name_cell = row.find("td", class_="coll-1")
                            seeds_cell = row.find("td", class_="coll-2")
                            leeches_cell = row.find("td", class_="coll-3")
                            size_cell = row.find("td", class_="coll-4")

                            if not all([name_cell, seeds_cell, size_cell]):
                                continue

                            title_link = name_cell.find("a", href=True)
                            if not title_link:
                                continue

                            title = title_link.text.strip()
                            detail_url = "https://1337x.to" + title_link["href"]

                            # Get magnet link from detail page
                            magnet = await self._get_1337x_magnet(
                                session, detail_url
                            )
                            if not magnet:
                                continue

                            seeders = int(seeds_cell.text.strip() or "0")
                            leechers = int(leeches_cell.text.strip() or "0")
                            size = size_cell.text.strip()

                            result = TorrentSearchResult(
                                title=title,
                                magnet_link=magnet,
                                size=size,
                                seeders=seeders,
                                leechers=leechers,
                                source="1337x",
                                quality=self._detect_quality(title),
                            )
                            results.append(result)

                        except Exception as e:
                            logger.debug(f"Error parsing 1337x row: {e}")
                            continue

        except Exception as e:
            logger.error(f"Error searching 1337x: {e}")

        logger.info(f"Found {len(results)} results from 1337x")
        return results

    async def _get_1337x_magnet(
        self, session: aiohttp.ClientSession, url: str
    ) -> str | None:
        """Get magnet link from 1337x detail page.

        Args:
            session: aiohttp session
            url: Detail page URL

        Returns:
            Magnet link or None
        """
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return None

                html = await response.text()
                soup = BeautifulSoup(html, "lxml")

                # Find magnet link
                magnet_link = soup.find("a", href=re.compile(r"^magnet:\?"))
                if magnet_link:
                    return magnet_link["href"]

        except Exception as e:
            logger.debug(f"Error getting 1337x magnet: {e}")

        return None

    async def _search_piratebay(
        self, query: str, limit: int
    ) -> List[TorrentSearchResult]:
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

                async with aiohttp.ClientSession(
                    timeout=self.timeout, headers=self.headers
                ) as session:
                    async with session.get(url) as response:
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
                                magnet_link_elem = row.find(
                                    "a", href=re.compile(r"^magnet:\?")
                                )
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


# Global searcher instance
searcher = TorrentSearcher()

