"""IMDb API client for fetching movie metadata."""

import logging

import aiohttp
from pydantic import ValidationError

from app.library.models import (
    IMDbEpisode,
    IMDbEpisodesResponse,
    IMDbSearchResponse,
    IMDbSeason,
    IMDbSeasonsResponse,
    IMDbTitle,
)

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

    async def search_titles(self, query: str, limit: int = 20) -> list[IMDbTitle]:
        """Search for titles using a query string.

        Args:
            query: Search query string
            limit: Maximum number of results (max 50 per API)

        Returns:
            List of IMDbTitle objects
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

                # Parse response using Pydantic model
                try:
                    search_response = IMDbSearchResponse(**data)
                    logger.info(f"Found {len(search_response.titles)} results from IMDb")
                    return search_response.titles
                except ValidationError as e:
                    logger.error(f"Failed to parse IMDb search response: {e}")
                    return []

        except aiohttp.ClientError as e:
            logger.error(f"Network error searching IMDb: {e}")
            return []
        except Exception as e:
            logger.error(f"Error searching IMDb: {e}")
            return []

    async def get_title(self, title_id: str) -> IMDbTitle | None:
        """Get detailed information about a specific title.

        Args:
            title_id: IMDb title ID (e.g., "tt1234567")

        Returns:
            IMDbTitle object or None if not found
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

                # Parse response using Pydantic model
                try:
                    return IMDbTitle(**data)
                except ValidationError as e:
                    logger.error(f"Failed to parse IMDb title response: {e}")
                    return None

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching IMDb title: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching IMDb title: {e}")
            return None

    async def get_titles_batch(self, title_ids: list[str]) -> list[IMDbTitle]:
        """Get detailed information about multiple titles.

        Automatically batches requests in chunks of 5 (API limit) and makes multiple
        requests if necessary. Preserves the order of input IDs.

        Args:
            title_ids: List of IMDb title IDs (e.g., ["tt1234567", "tt7654321"])

        Returns:
            List of IMDbTitle objects in the same order as input IDs
            (only includes titles that were successfully fetched)
        """
        # Validate input
        if not title_ids:
            logger.warning("get_titles_batch called with empty list")
            return []

        # Use a dict to map title_id -> IMDbTitle for order preservation
        titles_map: dict[str, IMDbTitle] = {}
        batch_size = 5
        url = f"{self.BASE_URL}/titles:batchGet"

        # Process IDs in batches of 5
        for i in range(0, len(title_ids), batch_size):
            batch = title_ids[i : i + batch_size]
            # Pass titleIds as array query parameter (e.g., ?titleIds=tt1234567&titleIds=tt7654321)
            params = {"titleIds": batch}

            logger.info(f"Fetching batch {i // batch_size + 1} with {len(batch)} IMDb titles")

            try:
                async with (
                    aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                    session.get(url, params=params) as response,
                ):
                    if response.status != 200:
                        logger.error(f"IMDb API returned status {response.status} for batch")
                        continue

                    data = await response.json()

                    # API returns an object with "titles" key containing list of title objects
                    if not isinstance(data, dict) or "titles" not in data:
                        logger.error(f"Expected dict with 'titles' key, got: {type(data)}")
                        continue

                    titles_data = data["titles"]
                    if not isinstance(titles_data, list):
                        logger.error(f"Expected 'titles' to be a list, got: {type(titles_data)}")
                        continue

                    # Parse each title using Pydantic model and store in map
                    for item in titles_data:
                        try:
                            title = IMDbTitle(**item)
                            titles_map[title.id] = title
                        except ValidationError as e:
                            logger.error(f"Failed to parse IMDb title in batch response: {e}")
                            continue

                    logger.info(f"Successfully parsed {len(titles_data)} titles from batch")

            except aiohttp.ClientError as e:
                logger.error(f"Network error fetching batch IMDb titles: {e}")
                continue
            except Exception as e:
                logger.error(f"Error fetching batch IMDb titles: {e}")
                continue

        # Return titles in the same order as input IDs
        ordered_titles = [titles_map[tid] for tid in title_ids if tid in titles_map]
        logger.info(f"Total titles fetched: {len(ordered_titles)}/{len(title_ids)}")
        return ordered_titles

    async def get_series_details(self, series_id: str) -> IMDbTitle | None:
        """Get detailed information about a TV series.

        Args:
            series_id: IMDb series ID (e.g., "tt1234567")

        Returns:
            IMDbTitle object or None if not found or not a series
        """
        # Use the same endpoint as get_title, but filter for series type
        title = await self.get_title(series_id)
        if title and title.is_series:
            return title
        return None

    async def get_series_seasons(self, series_id: str) -> list[IMDbSeason]:
        """Get list of seasons for a TV series.

        Args:
            series_id: IMDb series ID (e.g., "tt1234567")

        Returns:
            List of IMDbSeason objects
        """
        url = f"{self.BASE_URL}/titles/{series_id}/seasons"

        logger.info(f"Fetching seasons for series: {series_id}")

        try:
            async with (
                aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                session.get(url) as response,
            ):
                if response.status != 200:
                    logger.error(f"IMDb API returned status {response.status}")
                    return []

                data = await response.json()

                # Parse response using Pydantic model
                try:
                    seasons_response = IMDbSeasonsResponse(**data)
                    logger.info(
                        f"Found {len(seasons_response.seasons)} seasons for series {series_id}"
                    )
                    seasons = seasons_response.seasons
                    seasons.sort(key=lambda x: int(x.season) if x.season.isdecimal() else 0)
                    return seasons
                except ValidationError as e:
                    logger.error(f"Failed to parse IMDb seasons response: {e}")
                    return []

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching series seasons: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching series seasons: {e}")
            return []

    async def get_series_episodes(
        self, series_id: str, season: str | None = None, limit: int | None = None
    ) -> list[IMDbEpisode]:
        """Get list of episodes for a TV series.

        Args:
            series_id: IMDb series ID (e.g., "tt1234567")
            limit: Optional limit on number of episodes to fetch (None = all)

        Returns:
            List of IMDbEpisode objects
        """
        url = f"{self.BASE_URL}/titles/{series_id}/episodes"
        all_episodes: list[IMDbEpisode] = []
        page_token: str | None = None

        logger.info(f"Fetching episodes for series: {series_id} season: {season}")

        try:
            while True:
                params: dict[str, str] = {}
                if season:
                    params["season"] = season
                if page_token:
                    params["pageToken"] = page_token
                if limit and len(all_episodes) >= limit:
                    break

                async with (
                    aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session,
                    session.get(url, params=params) as response,
                ):
                    if response.status != 200:
                        logger.error(f"IMDb API returned status {response.status}")
                        break

                    data = await response.json()

                    # Parse response using Pydantic model
                    try:
                        episodes_response = IMDbEpisodesResponse(**data)
                        all_episodes.extend(episodes_response.episodes)
                        page_token = episodes_response.nextPageToken

                        if not page_token:
                            break

                        logger.debug(
                            f"Fetched {len(episodes_response.episodes)} episodes for series {series_id} season {season}"
                            f"(total: {len(all_episodes)}), continuing with pagination"
                        )
                    except ValidationError as e:
                        logger.error(f"Failed to parse IMDb episodes response: {e}")
                        break

            logger.info(
                f"Found {len(all_episodes)} total episodes for series {series_id} season {season}"
            )

            # Apply limit if specified
            if limit:
                all_episodes = all_episodes[:limit]
            all_episodes.sort(key=lambda x: x.episodeNumber if x.episodeNumber is not None else 0)

            return all_episodes

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching series episodes: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching series episodes: {e}")
            return []
