"""Media library manager for filesystem-based storage."""

import asyncio
import json
import logging
import re
from pathlib import Path
from uuid import uuid4

import aiofiles

from app.library.models import (
    Episode,
    Genre,
    MediaType,
    Movie,
    Series,
    VideoQuality,
)

logger = logging.getLogger(__name__)


class LibraryManager:
    """Manages the filesystem-based media library."""

    def __init__(self, library_path: Path):
        """Initialize the library manager.

        Args:
            library_path: Root path for the media library
        """
        self.library_path = library_path
        self.movies_path = library_path / "movies"
        self.series_path = library_path / "series"

        # Create directories
        self.movies_path.mkdir(parents=True, exist_ok=True)
        self.series_path.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._movies_cache: dict[str, Movie] = {}
        self._series_cache: dict[str, Series] = {}
        self._cache_loaded = False

    async def scan_library(self) -> tuple[int, int]:
        """Scan the library and load all media.

        Returns:
            Tuple of (movies_count, series_count)
        """
        await asyncio.gather(self._scan_movies(), self._scan_series())
        self._cache_loaded = True
        return len(self._movies_cache), len(self._series_cache)

    async def _scan_movies(self):
        """Scan movies directory and load metadata."""
        self._movies_cache.clear()

        for movie_dir in self.movies_path.iterdir():
            if not movie_dir.is_dir():
                continue

            metadata_file = movie_dir / "metadata.json"
            if not metadata_file.exists():
                # Try to create metadata from folder structure
                movie = await self._create_movie_from_folder(movie_dir)
                if movie:
                    await self._save_movie_metadata(movie)
                    self._movies_cache[movie.id] = movie
                continue

            try:
                async with aiofiles.open(metadata_file, encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)

                    # Update file_path to current location
                    video_file = self._find_video_file(movie_dir)
                    if video_file:
                        data["file_path"] = str(video_file)

                    movie = Movie(**data)
                    self._movies_cache[movie.id] = movie
            except Exception as e:
                print(f"Error loading movie metadata from {metadata_file}: {e}")

    async def _scan_series(self):
        """Scan series directory and load metadata."""
        self._series_cache.clear()

        for series_dir in self.series_path.iterdir():
            if not series_dir.is_dir():
                continue

            metadata_file = series_dir / "series_metadata.json"
            if not metadata_file.exists():
                # Create basic metadata
                series = await self._create_series_from_folder(series_dir)
                if series:
                    await self._save_series_metadata(series)
                    self._series_cache[series.id] = series
                continue

            try:
                async with aiofiles.open(metadata_file, encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)
                    series = Series(**data)

                    # Scan for episodes
                    series.episodes = await self._scan_episodes(series_dir, series.id)
                    series.total_episodes = len(series.episodes)

                    self._series_cache[series.id] = series
            except Exception as e:
                print(f"Error loading series metadata from {metadata_file}: {e}")

    async def _scan_episodes(self, series_dir: Path, series_id: str) -> list[Episode]:
        """Scan series directory for episodes.

        Args:
            series_dir: Path to series directory
            series_id: Series ID

        Returns:
            List of episodes
        """
        episodes = []

        for season_dir in series_dir.iterdir():
            if not season_dir.is_dir() or not season_dir.name.startswith("Season"):
                continue

            # Extract season number
            season_match = re.search(r"Season\s+(\d+)", season_dir.name, re.IGNORECASE)
            if not season_match:
                continue
            season_num = int(season_match.group(1))

            # Find episode files
            for episode_file in season_dir.iterdir():
                if episode_file.suffix.lower() not in [".mp4", ".mkv", ".avi", ".mov"]:
                    continue

                # Try to parse episode number from filename
                episode_match = re.search(r"[SE](\d+)[E](\d+)", episode_file.stem, re.IGNORECASE)
                if episode_match:
                    episode_num = int(episode_match.group(2))
                else:
                    # Try other patterns
                    episode_match = re.search(r"[Ee]pisode\s+(\d+)", episode_file.stem)
                    if episode_match:
                        episode_num = int(episode_match.group(1))
                    else:
                        continue

                # Check for episode metadata
                metadata_file = episode_file.with_suffix(".json")
                if metadata_file.exists():
                    try:
                        async with aiofiles.open(metadata_file, encoding="utf-8") as f:
                            content = await f.read()
                            data = json.loads(content)
                            data["file_path"] = str(episode_file)
                            episode = Episode(**data)
                            episodes.append(episode)
                            continue
                    except Exception as e:
                        print(f"Error loading episode metadata: {e}")

                # Create basic episode metadata
                episode = Episode(
                    id=f"{series_id}_s{season_num:02d}e{episode_num:02d}",
                    title=episode_file.stem,
                    series_id=series_id,
                    season_number=season_num,
                    episode_number=episode_num,
                    media_type=MediaType.EPISODE,
                    file_path=episode_file,
                    file_size=episode_file.stat().st_size,
                    quality=self._detect_quality(episode_file.stem),
                )
                episodes.append(episode)

        return sorted(episodes, key=lambda e: (e.season_number, e.episode_number))

    async def add_movie(
        self,
        title: str,
        file_path: Path,
        year: int | None = None,
        genres: list[Genre] | None = None,
        description: str | None = None,
        **kwargs,
    ) -> Movie:
        """Add a movie to the library.

        Args:
            title: Movie title
            file_path: Path to video file
            year: Release year
            genres: List of genres
            description: Movie description
            **kwargs: Additional metadata

        Returns:
            Movie object
        """
        movie_id = str(uuid4())
        movie_folder = self.movies_path / f"{title} ({year or 'Unknown'})"
        movie_folder.mkdir(exist_ok=True)

        # Move file to library
        new_file_path = movie_folder / file_path.name
        if file_path != new_file_path and file_path.exists():
            import shutil

            try:
                # Move the file to the library
                shutil.move(str(file_path), str(new_file_path))
                logger.info(f"Moved {file_path.name} to library at {new_file_path}")

                # Clean up empty parent directory if it exists
                if file_path.parent.exists() and not any(file_path.parent.iterdir()):
                    file_path.parent.rmdir()
            except Exception as e:
                logger.error(f"Error moving file to library: {e}")
                # If move fails, reference the original location
                new_file_path = file_path

        movie = Movie(
            id=movie_id,
            title=title,
            year=year,
            genres=genres or [],
            description=description,
            media_type=MediaType.MOVIE,
            file_path=new_file_path,
            file_size=file_path.stat().st_size if file_path.exists() else None,
            quality=self._detect_quality(title),
            **kwargs,
        )

        await self._save_movie_metadata(movie)
        self._movies_cache[movie_id] = movie

        return movie

    async def add_series(
        self,
        title: str,
        year: int | None = None,
        genres: list[Genre] | None = None,
        description: str | None = None,
        **kwargs,
    ) -> Series:
        """Add a series to the library.

        Args:
            title: Series title
            year: First air year
            genres: List of genres
            description: Series description
            **kwargs: Additional metadata

        Returns:
            Series object
        """
        series_id = str(uuid4())
        series_folder = self.series_path / title
        series_folder.mkdir(exist_ok=True)

        series = Series(
            id=series_id,
            title=title,
            year=year,
            genres=genres or [],
            description=description,
            episodes=[],
            **kwargs,
        )

        await self._save_series_metadata(series)
        self._series_cache[series_id] = series

        return series

    async def search(
        self,
        query: str,
        media_type: MediaType | None = None,
        genre: Genre | None = None,
    ) -> list[Movie | Series]:
        """Search for media in the library.

        Args:
            query: Search query
            media_type: Filter by media type
            genre: Filter by genre

        Returns:
            List of matching media items
        """
        if not self._cache_loaded:
            await self.scan_library()

        results = []
        query_lower = query.lower()

        # Search movies
        if media_type is None or media_type == MediaType.MOVIE:
            for movie in self._movies_cache.values():
                if query_lower in movie.title.lower() and (genre is None or genre in movie.genres):
                    results.append(movie)

        # Search series
        if media_type is None or media_type == MediaType.SERIES:
            for series in self._series_cache.values():
                if query_lower in series.title.lower() and (
                    genre is None or genre in series.genres
                ):
                    results.append(series)

        return results

    async def get_movie(self, movie_id: str) -> Movie | None:
        """Get a movie by ID.

        Args:
            movie_id: Movie ID

        Returns:
            Movie object or None
        """
        if not self._cache_loaded:
            await self.scan_library()
        return self._movies_cache.get(movie_id)

    async def get_series(self, series_id: str) -> Series | None:
        """Get a series by ID.

        Args:
            series_id: Series ID

        Returns:
            Series object or None
        """
        if not self._cache_loaded:
            await self.scan_library()
        return self._series_cache.get(series_id)

    async def get_all_movies(self) -> list[Movie]:
        """Get all movies in the library."""
        if not self._cache_loaded:
            await self.scan_library()
        return list(self._movies_cache.values())

    async def get_all_series(self) -> list[Series]:
        """Get all series in the library."""
        if not self._cache_loaded:
            await self.scan_library()
        return list(self._series_cache.values())

    async def get_recommendations(self, limit: int = 10) -> list[Movie | Series]:
        """Get media recommendations.

        Args:
            limit: Maximum number of recommendations

        Returns:
            List of recommended media items
        """
        if not self._cache_loaded:
            await self.scan_library()

        # Simple recommendation: return recently added items
        all_media = list(self._movies_cache.values()) + list(self._series_cache.values())
        all_media.sort(key=lambda x: x.added_date, reverse=True)
        return all_media[:limit]

    async def _save_movie_metadata(self, movie: Movie):
        """Save movie metadata to JSON file."""
        movie_folder = self.movies_path / f"{movie.title} ({movie.year or 'Unknown'})"
        movie_folder.mkdir(exist_ok=True)
        metadata_file = movie_folder / "metadata.json"

        data = movie.model_dump(mode="json")
        # Convert Path to string for JSON serialization
        if data.get("file_path"):
            data["file_path"] = str(data["file_path"])
        if data.get("poster_path"):
            data["poster_path"] = str(data["poster_path"])

        async with aiofiles.open(metadata_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

    async def _save_series_metadata(self, series: Series):
        """Save series metadata to JSON file."""
        series_folder = self.series_path / series.title
        series_folder.mkdir(exist_ok=True)
        metadata_file = series_folder / "series_metadata.json"

        data = series.model_dump(mode="json")
        # Convert Path to string
        if data.get("poster_path"):
            data["poster_path"] = str(data["poster_path"])

        # Don't save episodes in series metadata (too large)
        data["episodes"] = []

        async with aiofiles.open(metadata_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

    async def _create_movie_from_folder(self, movie_dir: Path) -> Movie | None:
        """Create movie metadata from folder name and contents."""
        video_file = self._find_video_file(movie_dir)
        if not video_file:
            return None

        # Try to parse title and year from folder name
        title = movie_dir.name
        year = None
        year_match = re.search(r"\((\d{4})\)", title)
        if year_match:
            year = int(year_match.group(1))
            title = title.replace(f"({year})", "").strip()

        return Movie(
            id=str(uuid4()),
            title=title,
            year=year,
            media_type=MediaType.MOVIE,
            file_path=video_file,
            file_size=video_file.stat().st_size,
            quality=self._detect_quality(video_file.stem),
        )

    async def _create_series_from_folder(self, series_dir: Path) -> Series | None:
        """Create series metadata from folder name."""
        title = series_dir.name

        # Count seasons
        seasons = [
            d for d in series_dir.iterdir() if d.is_dir() and d.name.lower().startswith("season")
        ]

        series_id = str(uuid4())

        series = Series(
            id=series_id,
            title=title,
            total_seasons=len(seasons),
        )

        # Scan episodes
        series.episodes = await self._scan_episodes(series_dir, series_id)
        series.total_episodes = len(series.episodes)

        return series

    def _find_video_file(self, directory: Path) -> Path | None:
        """Find the first video file in a directory."""
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"}
        for file in directory.iterdir():
            if file.is_file() and file.suffix.lower() in video_extensions:
                return file
        return None

    def _detect_quality(self, filename: str) -> VideoQuality:
        """Detect video quality from filename."""
        filename_lower = filename.lower()
        if "2160p" in filename_lower or "4k" in filename_lower:
            return VideoQuality.UHD_4K
        elif "1080p" in filename_lower:
            return VideoQuality.HD_1080
        elif "720p" in filename_lower:
            return VideoQuality.HD_720
        elif "480p" in filename_lower or "sd" in filename_lower:
            return VideoQuality.SD
        return VideoQuality.UNKNOWN

    async def import_from_download(self, download_path: Path, torrent_name: str) -> Movie | None:
        """Import a completed download into the library.

        Args:
            download_path: Path to the downloaded file/folder
            torrent_name: Name of the torrent

        Returns:
            Movie object if successfully imported, None otherwise
        """
        try:
            # Find the video file
            if download_path.is_file():
                video_file = download_path
            elif download_path.is_dir():
                video_file = self._find_video_file(download_path)
                if not video_file:
                    logger.error(f"No video file found in {download_path}")
                    return None
            else:
                logger.error(f"Download path does not exist: {download_path}")
                return None

            # Parse title and year from torrent name
            # Common patterns: "Movie Title (2024) [720p]", "Movie.Title.2024.720p.BluRay"
            title = torrent_name
            year = None

            # Try to extract year
            year_match = re.search(r"\((\d{4})\)|\b(\d{4})\b", torrent_name)
            if year_match:
                year = int(year_match.group(1) or year_match.group(2))
                # Remove year and quality tags from title
                title = re.sub(r"\(\d{4}\)", "", title)
                title = re.sub(r"\b\d{4}\b", "", title)

            # Remove quality and release info
            title = re.sub(r"\[.*?\]", "", title)  # Remove [720p], [YTS.AG], etc.
            title = re.sub(
                r"\.(720p|1080p|2160p|BluRay|WEB-DL|HDTV).*", "", title, flags=re.IGNORECASE
            )
            title = title.replace(".", " ").replace("_", " ")
            title = re.sub(r"\s+", " ", title).strip()

            logger.info(f"Importing movie: '{title}' ({year}) from {video_file.name}")

            # Add to library
            movie = await self.add_movie(
                title=title,
                file_path=video_file,
                year=year,
            )

            logger.info(f"Successfully imported movie to library: {movie.title}")
            return movie

        except Exception as e:
            logger.error(f"Error importing download to library: {e}", exc_info=True)
            return None
