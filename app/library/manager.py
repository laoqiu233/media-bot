"""Media library manager for filesystem-based storage."""

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import aiofiles

from app.library.models import (
    DownloadedFile,
    Genre,
    IMDbEpisode,
    IMDbSeason,
    IMDbTitle,
    MediaEntity,
    MediaType,
    VideoQuality,
    create_episode_entity,
    create_movie_entity,
    create_season_entity,
    create_series_entity,
)

logger = logging.getLogger(__name__)


class LibraryManager:
    """Manages the filesystem-based media library using MediaEntity model."""

    def __init__(self, library_path: Path):
        """Initialize the library manager.

        Args:
            library_path: Root path for the media library
        """
        self.library_path = library_path
        self.entities_path = library_path / "media_entities"

        # Create directories
        self.entities_path.mkdir(parents=True, exist_ok=True)

        # In-memory cache: imdb_id -> MediaEntity
        self._entities_cache: dict[str, MediaEntity] = {}
        self._cache_loaded = False

    async def scan_library(self) -> tuple[int, int]:
        """Scan the library and load all media entities.

        Returns:
            Tuple of (movies_count, series_count)
        """
        await self._scan_entities()
        self._cache_loaded = True

        movies_count = sum(
            1 for e in self._entities_cache.values() if e.media_type == MediaType.MOVIE
        )
        series_count = sum(
            1 for e in self._entities_cache.values() if e.media_type == MediaType.SERIES
        )

        return movies_count, series_count

    async def _scan_entities(self):
        """Scan media_entities directory and load all entities."""
        self._entities_cache.clear()

        for entity_dir in self.entities_path.iterdir():
            if not entity_dir.is_dir():
                continue

            metadata_file = entity_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                async with aiofiles.open(metadata_file, encoding="utf-8") as f:
                    content = await f.read()
                    data = json.loads(content)

                    entity = MediaEntity(**data)

                    # Load downloaded files for movies
                    if entity.media_type == MediaType.MOVIE:
                        entity.downloaded_files = await self._load_downloaded_files(
                            entity_dir / "files", entity.id
                        )

                    # Load seasons and episodes for series
                    elif entity.media_type == MediaType.SERIES:
                        await self._load_series_hierarchy(entity_dir, entity)

                    self._entities_cache[entity.imdb_id] = entity

            except Exception as e:
                logger.error(f"Error loading entity from {metadata_file}: {e}")

    async def _load_series_hierarchy(self, series_dir: Path, series: MediaEntity):
        """Load seasons and episodes for a series.

        Args:
            series_dir: Path to series directory
            series: Series MediaEntity
        """
        seasons_path = series_dir / "seasons"
        if not seasons_path.exists():
            return

        for season_dir in seasons_path.iterdir():
            if not season_dir.is_dir() or not season_dir.name.startswith("S"):
                continue

            # Extract season number (S01, S02, etc.)
            season_match = re.match(r"S(\d+)", season_dir.name)
            if not season_match:
                continue

            season_num = int(season_match.group(1))
            season_metadata_file = season_dir / "metadata.json"

            if season_metadata_file.exists():
                try:
                    async with aiofiles.open(season_metadata_file, encoding="utf-8") as f:
                        content = await f.read()
                        data = json.loads(content)
                        season_entity = MediaEntity(**data)
                        self._entities_cache[season_entity.imdb_id] = season_entity
                except Exception as e:
                    logger.error(f"Error loading season metadata: {e}")
                    continue

            # Load episodes for this season
            episodes_path = season_dir / "episodes"
            if episodes_path.exists():
                await self._load_episodes(episodes_path, series.id, season_num)

    async def _load_episodes(self, episodes_path: Path, series_id: str, season_num: int):
        """Load episodes from episodes directory.

        Args:
            episodes_path: Path to episodes directory
            series_id: Series ID
            season_num: Season number
        """
        for episode_dir in episodes_path.iterdir():
            if not episode_dir.is_dir() or not episode_dir.name.startswith("E"):
                continue

            # Extract episode number (E01, E02, etc.)
            episode_match = re.match(r"E(\d+)", episode_dir.name)
            if not episode_match:
                continue

            episode_metadata_file = episode_dir / "metadata.json"

            if episode_metadata_file.exists():
                try:
                    async with aiofiles.open(episode_metadata_file, encoding="utf-8") as f:
                        content = await f.read()
                        data = json.loads(content)
                        episode_entity = MediaEntity(**data)
                        episode_entity.downloaded_files = await self._load_downloaded_files(
                            episode_dir / "files", episode_entity.id
                        )
                        self._entities_cache[episode_entity.imdb_id] = episode_entity
                except Exception as e:
                    logger.error(f"Error loading episode metadata: {e}")

    async def _load_downloaded_files(
        self, files_dir: Path, media_entity_id: str, source: str | None = None
    ) -> list[DownloadedFile]:
        """Load downloaded files from files directory.

        Args:
            files_dir: Path to files directory
            media_entity_id: MediaEntity ID

        Returns:
            List of DownloadedFile objects
        """
        files = []
        if not files_dir.exists():
            return files

        for file_path in files_dir.iterdir():
            if not file_path.is_file():
                continue

            # Check if it's a video file
            if file_path.suffix.lower() not in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"]:
                continue

            # Create DownloadedFile
            file_id = str(uuid4())
            file_size = file_path.stat().st_size if file_path.exists() else None
            quality = self._detect_quality(file_path.name)

            downloaded_file = DownloadedFile(
                id=file_id,
                media_entity_id=media_entity_id,
                file_path=file_path,
                quality=quality,
                file_size=file_size,
                source=source,
            )

            files.append(downloaded_file)

        return files

    async def get_media_entity(self, imdb_id: str) -> MediaEntity | None:
        """Get a media entity by IMDb ID.

        Args:
            imdb_id: IMDb ID

        Returns:
            MediaEntity or None
        """
        if not self._cache_loaded:
            await self.scan_library()
        return self._entities_cache.get(imdb_id)

    async def get_media_entity_by_id(self, entity_id: str) -> MediaEntity | None:
        """Get a media entity by internal ID.

        Args:
            entity_id: Entity ID (UUID)

        Returns:
            MediaEntity or None
        """
        if not self._cache_loaded:
            await self.scan_library()

        for entity in self._entities_cache.values():
            if entity.id == entity_id:
                return entity
        return None

    async def get_all_media_entities(
        self, media_type: MediaType | None = None
    ) -> list[MediaEntity]:
        """Get all media entities, optionally filtered by type.

        Args:
            media_type: Optional media type filter

        Returns:
            List of MediaEntity objects
        """
        if not self._cache_loaded:
            await self.scan_library()

        entities = list(self._entities_cache.values())

        if media_type:
            entities = [e for e in entities if e.media_type == media_type]

        return entities

    async def get_series_seasons(self, series_id: str) -> list[MediaEntity]:
        """Get all seasons for a series.

        Args:
            series_id: Series entity ID

        Returns:
            List of season MediaEntity objects
        """
        if not self._cache_loaded:
            await self.scan_library()

        series = await self.get_media_entity_by_id(series_id)
        if not series or series.media_type != MediaType.SERIES:
            return []

        # Find all seasons for this series
        seasons = []
        for entity in self._entities_cache.values():
            if entity.media_type == MediaType.SEASON and entity.series_id == series_id:
                seasons.append(entity)

        return sorted(seasons, key=lambda s: s.season_number or 0)

    async def get_season_episodes(self, season_id: str) -> list[MediaEntity]:
        """Get all episodes for a season.

        Args:
            season_id: Season entity ID

        Returns:
            List of episode MediaEntity objects
        """
        if not self._cache_loaded:
            await self.scan_library()

        season = await self.get_media_entity_by_id(season_id)
        if not season or season.media_type != MediaType.SEASON:
            return []

        # Find all episodes for this season
        episodes = []
        for entity in self._entities_cache.values():
            if entity.media_type == MediaType.EPISODE and entity.season_id == season_id:
                episodes.append(entity)

        return sorted(episodes, key=lambda e: e.episode_number or 0)

    async def get_episode_by_number(
        self, series_id: str, season_num: int, episode_num: int
    ) -> MediaEntity | None:
        """Get an episode by series, season, and episode number.

        Args:
            series_id: Series entity ID
            season_num: Season number
            episode_num: Episode number

        Returns:
            Episode MediaEntity or None
        """
        if not self._cache_loaded:
            await self.scan_library()

        for entity in self._entities_cache.values():
            if (
                entity.media_type == MediaType.EPISODE
                and entity.series_id == series_id
                and entity.season_number == season_num
                and entity.episode_number == episode_num
            ):
                return entity

        return None

    async def create_media_entity(
        self,
        imdb_id: str,
        title: str,
        media_type: MediaType,
        year: int | None = None,
        genres: list[Genre] | None = None,
        description: str | None = None,
        poster_url: str | None = None,
        rating: float | None = None,
        **kwargs,
    ) -> MediaEntity:
        """Create a new media entity.

        Args:
            imdb_id: IMDb ID (primary identifier)
            title: Title
            media_type: Media type
            year: Release year
            genres: List of genres
            description: Description
            poster_url: Poster URL
            rating: IMDb rating
            **kwargs: Additional fields (director, cast, status, etc.)

        Returns:
            Created MediaEntity
        """
        entity_id = str(uuid4())
        entity_dir = self.entities_path / imdb_id
        entity_dir.mkdir(parents=True, exist_ok=True)

        entity = MediaEntity(
            id=entity_id,
            imdb_id=imdb_id,
            title=title,
            media_type=media_type,
            year=year,
            genres=genres or [],
            description=description,
            poster_url=poster_url,
            rating=rating,
            **kwargs,
        )

        await self._save_entity_metadata(entity)
        self._entities_cache[imdb_id] = entity

        return entity

    async def add_season(
        self, series_id: str, season_number: int, imdb_id: str | None = None, **kwargs
    ) -> MediaEntity:
        """Add a season to a series.

        Args:
            series_id: Series entity ID
            season_number: Season number
            imdb_id: Optional IMDb ID for season (if not provided, generates one)

        Returns:
            Created season MediaEntity
        """
        series = await self.get_media_entity_by_id(series_id)
        if not series or series.media_type != MediaType.SERIES:
            raise ValueError(f"Series not found: {series_id}")

        if not imdb_id:
            # Generate IMDb ID: series_imdb_id_S{season_num}
            imdb_id = f"{series.imdb_id}_S{season_number:02d}"

        season_id = str(uuid4())
        series_dir = self.entities_path / series.imdb_id
        season_dir = series_dir / "seasons" / f"S{season_number:02d}"
        season_dir.mkdir(parents=True, exist_ok=True)

        season = MediaEntity(
            id=season_id,
            imdb_id=imdb_id,
            title=f"{series.title} - Season {season_number}",
            media_type=MediaType.SEASON,
            series_id=series_id,
            season_number=season_number,
            year=series.year,
            genres=series.genres,
            **kwargs,
        )

        await self._save_entity_metadata(season, season_dir / "metadata.json")
        self._entities_cache[imdb_id] = season

        return season

    async def add_episode(
        self,
        season_id: str,
        episode_number: int,
        episode_title: str | None = None,
        air_date: datetime | None = None,
        imdb_id: str | None = None,
        **kwargs,
    ) -> MediaEntity:
        """Add an episode to a season.

        Args:
            season_id: Season entity ID
            episode_number: Episode number
            episode_title: Episode title
            air_date: Air date
            imdb_id: Optional IMDb ID for episode

        Returns:
            Created episode MediaEntity
        """
        season = await self.get_media_entity_by_id(season_id)
        if not season or season.media_type != MediaType.SEASON:
            raise ValueError(f"Season not found: {season_id}")

        series = await self.get_media_entity_by_id(season.series_id or "")
        if not series:
            raise ValueError(f"Series not found for season: {season_id}")

        if not imdb_id:
            # Generate IMDb ID: series_imdb_id_S{season_num}E{episode_num}
            imdb_id = f"{series.imdb_id}_S{season.season_number:02d}E{episode_number:02d}"

        episode_id = str(uuid4())
        season_dir = (
            self.entities_path / series.imdb_id / "seasons" / f"S{season.season_number:02d}"
        )
        episode_dir = season_dir / "episodes" / f"E{episode_number:02d}"
        episode_dir.mkdir(parents=True, exist_ok=True)

        episode = MediaEntity(
            id=episode_id,
            imdb_id=imdb_id,
            title=episode_title
            or f"{series.title} S{season.season_number:02d}E{episode_number:02d}",
            media_type=MediaType.EPISODE,
            series_id=series.id,
            season_id=season_id,
            season_number=season.season_number,
            episode_number=episode_number,
            episode_title=episode_title,
            air_date=air_date,
            year=series.year,
            genres=series.genres,
            **kwargs,
        )

        await self._save_entity_metadata(episode, episode_dir / "metadata.json")
        self._entities_cache[imdb_id] = episode

        return episode

    async def add_downloaded_file(
        self,
        media_entity_id: str,
        file_path: Path,
        source: str | None = None,
        quality: VideoQuality | None = None,
    ) -> DownloadedFile:
        """Add a downloaded file to a media entity.

        Args:
            media_entity_id: MediaEntity ID
            file_path: Path to the video file
            source: Source torrent name
            quality: Video quality (auto-detected if not provided)

        Returns:
            Created DownloadedFile
        """
        entity = await self.get_media_entity_by_id(media_entity_id)
        if not entity:
            raise ValueError(f"MediaEntity not found: {media_entity_id}")

        # Determine target directory based on entity type
        if entity.media_type == MediaType.MOVIE:
            target_dir = self.entities_path / entity.imdb_id / "files"
        elif entity.media_type == MediaType.EPISODE:
            series = await self.get_media_entity_by_id(entity.series_id or "")
            if not series:
                raise ValueError(f"Series not found for episode: {media_entity_id}")

            season = await self.get_media_entity_by_id(entity.season_id or "")
            if not season:
                raise ValueError(f"Season not found for episode: {media_entity_id}")

            target_dir = (
                self.entities_path
                / series.imdb_id
                / "seasons"
                / f"S{season.season_number:02d}"
                / "episodes"
                / f"E{entity.episode_number:02d}"
                / "files"
            )
        else:
            raise ValueError(f"Cannot add files to entity type: {entity.media_type}")

        target_dir.mkdir(parents=True, exist_ok=True)

        # Move file to target directory
        target_file = target_dir / file_path.name
        if file_path != target_file and file_path.exists():
            try:
                shutil.move(str(file_path), str(target_file))
                logger.info(f"Moved {file_path.name} to library at {target_file}")
            except Exception as e:
                logger.error(f"Error moving file to library: {e}")
                target_file = file_path

        # Detect quality if not provided
        if quality is None:
            quality = self._detect_quality(file_path.name)

        # Get file size
        file_size = target_file.stat().st_size if target_file.exists() else None

        # Create DownloadedFile
        file_id = str(uuid4())
        downloaded_file = DownloadedFile(
            id=file_id,
            media_entity_id=media_entity_id,
            file_path=target_file,
            quality=quality,
            file_size=file_size,
            source=source,
        )

        # Add to entity
        entity.downloaded_files.append(downloaded_file)
        await self._save_entity_metadata(entity)

        return downloaded_file

    async def _save_entity_metadata(self, entity: MediaEntity, metadata_file: Path | None = None):
        """Save entity metadata to JSON file.

        Args:
            entity: MediaEntity to save
            metadata_file: Optional custom path (defaults to entity_dir/metadata.json)
        """
        if metadata_file is None:
            entity_dir = self.entities_path / entity.imdb_id
            metadata_file = entity_dir / "metadata.json"

        metadata_file.parent.mkdir(parents=True, exist_ok=True)

        data = entity.model_dump(mode="json")
        # Convert Path objects to strings
        if "downloaded_files" in data:
            for file_data in data["downloaded_files"]:
                if "file_path" in file_data:
                    file_data["file_path"] = str(file_data["file_path"])

        async with aiofiles.open(metadata_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))

    def _find_video_file(self, directory: Path) -> Path | None:
        """Find the first video file in a directory.

        Args:
            directory: Directory to search

        Returns:
            Path to video file or None
        """
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"}
        for file in directory.iterdir():
            if file.is_file() and file.suffix.lower() in video_extensions:
                return file
        return None

    def _detect_quality(self, filename: str) -> VideoQuality:
        """Detect video quality from filename.

        Args:
            filename: Filename to analyze

        Returns:
            VideoQuality enum value
        """
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

    async def import_from_download(
        self, download_path: Path, torrent_name: str, metadata: dict | None = None
    ) -> MediaEntity | None:
        """Import a completed download into the library.

        Args:
            download_path: Path to the downloaded file/folder
            torrent_name: Name of the torrent
            metadata: Optional metadata dict from IMDb (includes imdb_id, title, year, etc.)

        Returns:
            MediaEntity if successfully imported, None otherwise
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

            # Check if this is a series episode by filename pattern
            episode_match = self._parse_episode_filename(video_file.name)
            if episode_match:
                return await self._import_episode_download(
                    video_file, torrent_name, episode_match, metadata
                )

            # Otherwise, treat as movie
            return await self._import_movie_download(video_file, torrent_name, metadata)

        except Exception as e:
            logger.error(f"Error importing download to library: {e}", exc_info=True)
            return None

    def _parse_episode_filename(self, filename: str) -> dict | None:
        """Parse episode information from filename.

        Args:
            filename: Filename to parse

        Returns:
            Dict with season_num and episode_num, or None if not an episode
        """
        # Common patterns: S01E01, s01e01, S1E1, 1x01, etc.
        patterns = [
            r"[Ss](\d+)[Ee](\d+)",  # S01E01
            r"(\d+)[Xx](\d+)",  # 1x01
            r"Season\s+(\d+).*Episode\s+(\d+)",  # Season 1 Episode 1
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return {"season_num": int(match.group(1)), "episode_num": int(match.group(2))}

        return None

    async def _import_movie_download(
        self, video_file: Path, torrent_name: str, metadata: dict | None
    ) -> MediaEntity | None:
        """Import a movie download.

        Args:
            video_file: Path to video file
            torrent_name: Torrent name
            metadata: Optional metadata

        Returns:
            MediaEntity or None
        """
        # Extract metadata
        if metadata:
            imdb_id = metadata.get("imdb_id")
            title = metadata.get("title", torrent_name)
            year = metadata.get("year")
            genres = metadata.get("genres", [])
            description = metadata.get("description")
            rating = metadata.get("rating")
            director = metadata.get("director")
            cast = metadata.get("cast", [])
            poster_url = metadata.get("poster_url")
            quality_str = metadata.get("quality")
        else:
            # Parse from torrent name
            imdb_id = None
            title = torrent_name
            year = None
            genres = []
            description = None
            rating = None
            director = None
            cast = []
            poster_url = None
            quality_str = None

            # Try to extract year
            year_match = re.search(r"\((\d{4})\)|\b(\d{4})\b", torrent_name)
            if year_match:
                year = int(year_match.group(1) or year_match.group(2))

            # Clean title
            title = re.sub(r"\((\d{4})\)", "", title)
            title = re.sub(r"\[.*?\]", "", title)
            title = re.sub(
                r"\.(720p|1080p|2160p|BluRay|WEB-DL|HDTV).*", "", title, flags=re.IGNORECASE
            )
            title = title.replace(".", " ").replace("_", " ")
            title = re.sub(r"\s+", " ", title).strip()

        if not imdb_id:
            logger.warning(f"No IMDb ID for movie: {title}, skipping import")
            return None

        # Convert genres
        parsed_genres = []
        if genres:
            for genre_str in genres:
                try:
                    genre_upper = genre_str.upper().replace("-", "")
                    if genre_upper in Genre.__members__:
                        parsed_genres.append(Genre[genre_upper])
                    elif genre_str.lower() in [g.value for g in Genre]:
                        parsed_genres.append(Genre(genre_str.lower()))
                    else:
                        parsed_genres.append(Genre.OTHER)
                except (KeyError, ValueError):
                    parsed_genres.append(Genre.OTHER)

        # Convert quality
        quality = VideoQuality.UNKNOWN
        if quality_str:
            try:
                quality = VideoQuality(quality_str)
            except ValueError:
                quality = self._detect_quality(torrent_name)
        else:
            quality = self._detect_quality(torrent_name)

        # Check if entity exists
        entity = await self.get_media_entity(imdb_id)
        if not entity:
            # Create new entity
            entity = await self.create_media_entity(
                imdb_id=imdb_id,
                title=title,
                media_type=MediaType.MOVIE,
                year=year,
                genres=parsed_genres,
                description=description,
                poster_url=poster_url,
                rating=rating,
                director=director,
                cast=cast,
            )

        # Add downloaded file
        await self.add_downloaded_file(
            media_entity_id=entity.id,
            file_path=video_file,
            source=torrent_name,
            quality=quality,
        )

        logger.info(f"Successfully imported movie: {entity.title}")
        return entity

    async def _import_episode_download(
        self,
        video_file: Path,
        torrent_name: str,
        episode_match: dict,
        metadata: dict | None,
    ) -> MediaEntity | None:
        """Import an episode download.

        Args:
            video_file: Path to video file
            torrent_name: Torrent name
            episode_match: Parsed episode info (season_num, episode_num)
            metadata: Optional metadata

        Returns:
            MediaEntity or None
        """
        # For now, we need series imdb_id from metadata or user will need to match manually
        # This is a limitation - we'll improve this later
        if not metadata or not metadata.get("series_imdb_id"):
            logger.warning(
                f"Episode download detected but no series_imdb_id in metadata: {torrent_name}"
            )
            return None

        series_imdb_id = metadata.get("series_imdb_id")
        if not series_imdb_id or not isinstance(series_imdb_id, str):
            logger.warning(f"Invalid or missing series_imdb_id in metadata for {video_file}")
            return None

        season_num = episode_match["season_num"]
        episode_num = episode_match["episode_num"]

        # Get or create series
        series = await self.get_media_entity(series_imdb_id)
        if not series:
            logger.warning(f"Series not found: {series_imdb_id}, cannot import episode")
            return None

        # Get or create season
        seasons = await self.get_series_seasons(series.id)
        season = next((s for s in seasons if s.season_number == season_num), None)

        if not season:
            season = await self.add_season(series.id, season_num)

        # Get or create episode
        episode = await self.get_episode_by_number(series.id, season_num, episode_num)
        if not episode:
            episode = await self.add_episode(
                season.id,
                episode_num,
                episode_title=metadata.get("episode_title") if metadata else None,
            )

        # Add downloaded file
        quality = self._detect_quality(video_file.name)
        await self.add_downloaded_file(
            media_entity_id=episode.id,
            file_path=video_file,
            source=torrent_name,
            quality=quality,
        )

        logger.info(
            f"Successfully imported episode: {series.title} S{season_num:02d}E{episode_num:02d}"
        )
        return episode

    async def get_or_create_series_entity(self, imdb_title: IMDbTitle) -> MediaEntity:
        """Get existing series entity or create a new one.

        Args:
            imdb_title: IMDb title object for the series

        Returns:
            Series MediaEntity
        """
        # Check if already exists
        entity = await self.get_media_entity(imdb_title.id)
        if entity and entity.media_type == MediaType.SERIES:
            return entity

        # Create new series entity
        series_entity = create_series_entity(imdb_title)

        # Save to library
        entity_dir = self.entities_path / series_entity.imdb_id
        entity_dir.mkdir(parents=True, exist_ok=True)
        await self._save_entity_metadata(series_entity)

        # Add to cache
        self._entities_cache[series_entity.imdb_id] = series_entity

        logger.info(f"Created series entity: {series_entity.title}")
        return series_entity

    async def get_or_create_season_entity(
        self, series_imdb_id: str, imdb_season: IMDbSeason
    ) -> MediaEntity:
        """Get existing season entity or create a new one.

        Args:
            series_imdb_id: IMDb ID of the parent series
            imdb_season: IMDb season object

        Returns:
            Season MediaEntity
        """
        # Get series entity
        series = await self.get_media_entity(series_imdb_id)
        if not series:
            raise ValueError(f"Series not found: {series_imdb_id}")

        # Generate season IMDb ID
        season_imdb_id = f"{series_imdb_id}_S{imdb_season.season}"

        # Check if already exists
        entity = await self.get_media_entity(season_imdb_id)
        if entity and entity.media_type == MediaType.SEASON:
            return entity

        # Create new season entity
        season_entity = create_season_entity(series, imdb_season)

        # Save to library
        series_dir = self.entities_path / series_imdb_id
        season_dir = series_dir / "seasons" / f"S{imdb_season.season.zfill(2)}"
        season_dir.mkdir(parents=True, exist_ok=True)
        await self._save_entity_metadata(season_entity, season_dir / "metadata.json")

        # Add to cache
        self._entities_cache[season_entity.imdb_id] = season_entity

        logger.info(f"Created season entity: {season_entity.title}")
        return season_entity

    async def get_or_create_episode_entity(
        self, season_imdb_id: str, imdb_episode: IMDbEpisode, imdb_title: IMDbTitle
    ) -> MediaEntity:
        """Get existing episode entity or create a new one.

        Args:
            season_imdb_id: IMDb ID of the parent season
            imdb_episode: IMDb episode object (basic info)
            imdb_title: IMDb title object for the episode (detailed info)

        Returns:
            Episode MediaEntity
        """
        # Check if already exists
        entity = await self.get_media_entity(imdb_episode.id)
        if entity and entity.media_type == MediaType.EPISODE:
            return entity

        # Get season and series
        season = await self.get_media_entity(season_imdb_id)
        if not season or season.media_type != MediaType.SEASON:
            raise ValueError(f"Season not found: {season_imdb_id}")

        series = await self.get_media_entity(season.series_id)
        if not series:
            raise ValueError(f"Series not found: {season.series_id}")

        # Create new episode entity
        episode_entity = create_episode_entity(series, season, imdb_episode, imdb_title)

        # Save to library
        series_dir = self.entities_path / series.imdb_id
        season_num_str = imdb_episode.season if imdb_episode.season else "00"
        episode_num_str = (
            str(imdb_episode.episodeNumber).zfill(2) if imdb_episode.episodeNumber else "00"
        )

        episode_dir = (
            series_dir
            / "seasons"
            / f"S{season_num_str.zfill(2)}"
            / "episodes"
            / f"E{episode_num_str}"
        )
        episode_dir.mkdir(parents=True, exist_ok=True)
        await self._save_entity_metadata(episode_entity, episode_dir / "metadata.json")

        # Add to cache
        self._entities_cache[episode_entity.imdb_id] = episode_entity

        logger.info(f"Created episode entity: {episode_entity.title}")
        return episode_entity

    async def search(
        self,
        query: str,
        media_type: MediaType | None = None,
        genre: Genre | None = None,
    ) -> list[MediaEntity]:
        """Search for media entities.

        Args:
            query: Search query
            media_type: Filter by media type
            genre: Filter by genre

        Returns:
            List of matching MediaEntity objects
        """
        if not self._cache_loaded:
            await self.scan_library()

        results = []
        query_lower = query.lower()

        entities = await self.get_all_media_entities(media_type)

        for entity in entities:
            # Check title match
            if query_lower not in entity.title.lower():
                continue

            # Check genre match
            if genre and genre not in entity.genres:
                continue

            results.append(entity)

        return results

    async def get_or_create_movie_entity(self, imdb_title) -> MediaEntity:
        """Get or create a movie entity from IMDb title.

        Args:
            imdb_title: IMDbTitle object

        Returns:
            MediaEntity for the movie
        """
        from app.library.models import create_movie_entity

        # Check if exists
        entity = await self.get_media_entity(imdb_title.id)
        if entity:
            return entity

        # Create new entity
        entity = create_movie_entity(imdb_title)

        # Save to library
        entity_dir = self.entities_path / entity.imdb_id
        entity_dir.mkdir(parents=True, exist_ok=True)

        await self._save_entity_metadata(entity)
        self._entities_cache[entity.imdb_id] = entity

        logger.info(f"Created movie entity: {entity.title}")
        return entity

    async def get_or_create_series_entity(self, imdb_title) -> MediaEntity:
        """Get or create a series entity from IMDb title.

        Args:
            imdb_title: IMDbTitle object (should be a series)

        Returns:
            MediaEntity for the series
        """
        from app.library.models import create_series_entity

        # Check if exists
        entity = await self.get_media_entity(imdb_title.id)
        if entity:
            return entity

        # Create new entity
        entity = create_series_entity(imdb_title)

        # Save to library
        entity_dir = self.entities_path / entity.imdb_id
        entity_dir.mkdir(parents=True, exist_ok=True)

        await self._save_entity_metadata(entity)
        self._entities_cache[entity.imdb_id] = entity

        logger.info(f"Created series entity: {entity.title}")
        return entity

    async def get_or_create_season_entity(self, series_imdb_id: str, imdb_season) -> MediaEntity:
        """Get or create a season entity.

        Args:
            series_imdb_id: Series IMDb ID
            imdb_season: IMDbSeason object

        Returns:
            MediaEntity for the season
        """
        from app.library.models import create_season_entity

        # Generate season imdb_id
        season_imdb_id = f"{series_imdb_id}_S{imdb_season.season}"

        # Check if exists
        entity = await self.get_media_entity(season_imdb_id)
        if entity:
            return entity

        # Get series entity
        series = await self.get_media_entity(series_imdb_id)
        if not series:
            raise ValueError(f"Series not found: {series_imdb_id}")

        # Create new season entity
        entity = create_season_entity(series, imdb_season)

        # Save to library
        series_dir = self.entities_path / series_imdb_id
        season_dir = series_dir / "seasons" / f"S{imdb_season.season.zfill(2)}"
        season_dir.mkdir(parents=True, exist_ok=True)

        await self._save_entity_metadata(entity, season_dir / "metadata.json")
        self._entities_cache[entity.imdb_id] = entity

        logger.info(f"Created season entity: {entity.title}")
        return entity

    async def get_or_create_episode_entity(
        self, season_imdb_id: str, imdb_episode, imdb_title
    ) -> MediaEntity:
        """Get or create an episode entity.

        Args:
            season_imdb_id: Season IMDb ID
            imdb_episode: IMDbEpisode object (basic info)
            imdb_title: IMDbTitle object (full episode details)

        Returns:
            MediaEntity for the episode
        """
        from app.library.models import create_episode_entity

        # Check if exists
        entity = await self.get_media_entity(imdb_episode.id)
        if entity:
            return entity

        # Get season entity
        season = await self.get_media_entity(season_imdb_id)
        if not season or season.media_type != MediaType.SEASON:
            raise ValueError(f"Season not found: {season_imdb_id}")

        # Get series entity
        series = await self.get_media_entity(season.series_id)
        if not series:
            raise ValueError(f"Series not found: {season.series_id}")

        # Create new episode entity
        entity = create_episode_entity(series, season, imdb_episode, imdb_title)

        # Save to library
        series_dir = self.entities_path / series.imdb_id
        season_num_padded = str(imdb_episode.season).zfill(2) if imdb_episode.season else "00"
        episode_num_padded = (
            str(imdb_episode.episodeNumber).zfill(2) if imdb_episode.episodeNumber else "00"
        )

        episode_dir = (
            series_dir / "seasons" / f"S{season_num_padded}" / "episodes" / f"E{episode_num_padded}"
        )
        episode_dir.mkdir(parents=True, exist_ok=True)

        await self._save_entity_metadata(entity, episode_dir / "metadata.json")
        self._entities_cache[entity.imdb_id] = entity

        logger.info(f"Created episode entity: {entity.title}")
        return entity
