"""IMDb API client for fetching movie metadata."""

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class IMDbClient:
    """Client for interacting with the IMDb API."""

    BASE_URL = "https://api.imdbapi.dev"

    def __init__(self):
        """Initialize IMDb client."""
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.headers = {
            "Accept": "application/json",
        }

    async def search_titles(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for titles using a query string.

        Args:
            query: Search query string
            limit: Maximum number of results (max 50 per API)

        Returns:
            List of title objects from IMDb API
        """
        # Ensure limit is within API bounds
        limit = min(limit, 50)

        url = f"{self.BASE_URL}/search/titles"
        params = {"query": query, "limit": limit}

        logger.info(f"Searching IMDb for: {query} (limit: {limit})")

        try:
            async with (
                aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                session.get(url, params=params) as response,
            ):
                if response.status != 200:
                    logger.error(f"IMDb API returned status {response.status}")
                    return []

                data = await response.json()

                # Extract titles from response
                titles = data.get("titles", [])
                logger.info(f"Found {len(titles)} results from IMDb")

                return titles

        except aiohttp.ClientError as e:
            logger.error(f"Network error searching IMDb: {e}")
            return []
        except Exception as e:
            logger.error(f"Error searching IMDb: {e}")
            return []

    async def get_title(self, title_id: str) -> dict[str, Any] | None:
        """Get detailed information about a specific title.

        Args:
            title_id: IMDb title ID (e.g., "tt1234567")

        Returns:
            Title object or None if not found
        """
        url = f"{self.BASE_URL}/titles/{title_id}"

        logger.info(f"Fetching IMDb title: {title_id}")

        try:
            async with (
                aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                session.get(url) as response,
            ):
                if response.status != 200:
                    logger.error(f"IMDb API returned status {response.status}")
                    return None

                data = await response.json()
                return data

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching IMDb title: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching IMDb title: {e}")
            return None
