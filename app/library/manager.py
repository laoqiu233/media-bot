"""Media library manager for filesystem-based storage."""

import json
import logging
import os
import shutil
from pathlib import Path
from uuid import uuid4

import aiofiles

from app.library.models import (
    DownloadedFile,
    MediaEntity,
    MediaType,
    VideoQuality,
)
from app.torrent.file_utils import is_video_file

logger = logging.getLogger(__name__)

METADATA_FILE = "metadata.json"
DOWNLOADED_FILES_DIR = "files"
SEASONS_DIR = "seasons"
EPISODES_DIR = "episodes"


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

    async def scan_library(self) -> tuple[int, int]:
        """Scan the library and load all media entities.

        Returns:
            Tuple of (movies_count, series_count)
        """
        await self._scan_entities()

        movies_count = sum(
            1 for e in self._entities_cache.values() if e.media_type == MediaType.MOVIE
        )
        series_count = sum(
            1 for e in self._entities_cache.values() if e.media_type == MediaType.SERIES
        )

        return movies_count, series_count

    def get_all_media_entities(self) -> list[MediaEntity]:
        """Get all media entities from the library."""
        return list(self._entities_cache.values())

    async def _scan_entities(self):
        """Scan media_entities directory and load all entities."""
        self._entities_cache.clear()

        for entity_dir in self.entities_path.iterdir():
            if not entity_dir.is_dir():
                continue

            entity = await self._load_metadata(entity_dir)

            if entity is None:
                continue

            if entity.media_type == MediaType.MOVIE:
                await self._validate_downloaded_files(entity_dir, entity)
            elif entity.media_type == MediaType.SERIES:
                await self._scan_series(entity_dir, entity)
            else:
                logger.warning(
                    f"Unexpected media type {entity.media_type} in media library root directory: {entity_dir}"
                )
                continue

            self._entities_cache[entity.imdb_id] = entity

    async def _scan_series(self, entity_dir: Path, series_entity: MediaEntity):
        """Scan series directory and load all seasons and episodes."""
        seasons_dir = entity_dir / SEASONS_DIR
        if not seasons_dir.exists():
            logger.warning(f"No seasons directory found for series {series_entity.imdb_id}")
            return

        for season_dir in seasons_dir.iterdir():
            if not season_dir.is_dir():
                logger.warning(f"Skipping non-season directory: {season_dir}")
                continue

            season_entity = await self._load_metadata(season_dir)
            if season_entity is None:
                logger.warning(
                    f"No season metadata found for season {season_dir} in series dir {entity_dir}"
                )
                continue

            if season_entity.media_type == MediaType.SEASON:
                await self._scan_season(season_dir, season_entity)
                self._entities_cache[season_entity.imdb_id] = season_entity
            else:
                logger.warning(
                    f"Unexpected media type {season_entity.media_type} in season directory: {season_dir}"
                )

    async def _scan_season(self, entity_dir: Path, season_entity: MediaEntity):
        """Scan season directory and load all episodes."""
        episodes_dir = entity_dir / EPISODES_DIR
        if not episodes_dir.exists():
            logger.warning(f"No episodes directory found for season {season_entity.imdb_id}")
            return

        for episode_dir in episodes_dir.iterdir():
            if not episode_dir.is_dir():
                logger.warning(f"Skipping non-episode directory: {episode_dir}")
                continue

            episode_entity = await self._load_metadata(episode_dir)
            if episode_entity is None:
                logger.warning(
                    f"No episode metadata found for episode {episode_dir} in season dir {entity_dir}"
                )
                continue

            if episode_entity.media_type == MediaType.EPISODE:
                await self._validate_downloaded_files(episode_dir, episode_entity)
                self._entities_cache[episode_entity.imdb_id] = episode_entity
            else:
                logger.warning(
                    f"Unexpected media type {episode_entity.media_type} in episode directory: {episode_dir}"
                )

    async def _validate_downloaded_files(self, entity_dir: Path, entity: MediaEntity):
        """Validate downloaded files for an entity."""
        files_dir = entity_dir / DOWNLOADED_FILES_DIR
        if not files_dir.exists():
            entity.downloaded_files = []
            await self._save_metadata(entity_dir, entity)
            return

        expected_files = {file.file_name: file for file in entity.downloaded_files}
        actual_files: list[DownloadedFile] = []

        for file_path in files_dir.iterdir():
            if not file_path.is_file() or not is_video_file(file_path.name):
                logger.warning(f"Skipping non-video file: {file_path}")
                continue
            if file_path.name not in expected_files:
                logger.warning(f"Found unexpected file: {file_path}, adding to the library")
                actual_files.append(
                    DownloadedFile(
                        id=str(uuid4()),
                        media_entity_id=entity.imdb_id,
                        file_name=file_path.name,
                        quality=VideoQuality.UNKNOWN,
                        file_size=file_path.stat().st_size,
                        source=None,
                    )
                )
                continue
            actual_files.append(expected_files[file_path.name])

        entity.downloaded_files = actual_files
        await self._save_metadata(entity_dir, entity)

    async def get_entity(self, imdb_id: str) -> MediaEntity | None:
        """Get an entity from the library."""
        if imdb_id not in self._entities_cache:
            return None
        return self._entities_cache[imdb_id]

    async def delete_entity(self, entity_id: str, delete_parent: bool) -> str | None:
        entity = await self.get_entity(entity_id)
        if entity is None:
            raise ValueError(f"Entity {entity_id} not found in library")
        entity_dir = self._get_entity_dir(entity)
        shutil.rmtree(entity_dir)
        del self._entities_cache[entity_id]
        children = await self.get_child_entities(entity)

        for child in children:
            await self.delete_entity(child.imdb_id, False)

        parent = await self.get_parent_entity(entity)
        if parent is not None and delete_parent:
            siblings = await self.get_child_entities(parent)
            if len(siblings) == 0:
                return await self.delete_entity(parent.imdb_id, True)
            return parent.imdb_id
        return None

    async def delete_file(self, entity_id: str, file_id: str) -> str | None:
        entity = await self.get_entity(entity_id)
        if entity is None:
            raise ValueError(f"Entity {entity_id} not found in library")
        file = next((f for f in entity.downloaded_files if f.id == file_id), None)
        if file is None:
            raise ValueError(f"File {file_id} not found in entity {entity_id}")
        entity_dir = self._get_entity_dir(entity)
        file_path = entity_dir / DOWNLOADED_FILES_DIR / file.file_name
        os.remove(file_path)
        entity.downloaded_files.remove(file)
        await self._save_metadata(entity_dir, entity)

        if entity.downloaded_files == []:
            return await self.delete_entity(entity_id, True)
        return entity_id

    async def get_parent_entity(self, entity: MediaEntity) -> MediaEntity | None:
        if entity.media_type == MediaType.SEASON and entity.series_id is not None:
            return await self.get_entity(entity.series_id)
        elif entity.media_type == MediaType.EPISODE and entity.season_id is not None:
            return await self.get_entity(entity.season_id)
        return None

    async def get_child_entities(self, parent_entity: MediaEntity) -> list[MediaEntity]:
        """Get all child entities of a parent entity."""
        if parent_entity.media_type == MediaType.SERIES:
            entities = [
                e
                for e in self._entities_cache.values()
                if e.series_id == parent_entity.imdb_id and e.media_type == MediaType.SEASON
            ]
            entities.sort(key=lambda e: e.imdb_id)
            return entities
        elif parent_entity.media_type == MediaType.SEASON:
            entities = [
                e
                for e in self._entities_cache.values()
                if e.season_id == parent_entity.imdb_id and e.media_type == MediaType.EPISODE
            ]
            entities.sort(key=lambda e: e.episode_number or 0)
            return entities
        return []

    async def create_or_update_entity(self, entity: MediaEntity):
        """Create or update an entity in the library.
        
        When updating an existing entity, preserves the downloaded_files list
        to avoid losing files when metadata is refreshed.
        """

        entity_dir = self._get_entity_dir(entity)

        if entity.media_type == MediaType.MOVIE or entity.media_type == MediaType.SERIES:
            if entity.imdb_id not in self._entities_cache:
                entity_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Preserve downloaded files when updating existing entity
                existing_entity = self._entities_cache[entity.imdb_id]
                entity.downloaded_files = existing_entity.downloaded_files

        elif entity.media_type == MediaType.SEASON:
            if entity.series_id not in self._entities_cache:
                raise ValueError(f"Parent series {entity.series_id} not found in library")
            if entity.imdb_id not in self._entities_cache:
                entity_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Preserve downloaded files when updating existing entity
                existing_entity = self._entities_cache[entity.imdb_id]
                entity.downloaded_files = existing_entity.downloaded_files

        elif entity.media_type == MediaType.EPISODE:
            if entity.series_id not in self._entities_cache:
                raise ValueError(f"Parent series {entity.series_id} not found in library")
            if entity.season_id not in self._entities_cache:
                raise ValueError(f"Parent season {entity.season_id} not found in library")
            if entity.imdb_id not in self._entities_cache:
                entity_dir.mkdir(parents=True, exist_ok=True)
            else:
                # Preserve downloaded files when updating existing entity
                existing_entity = self._entities_cache[entity.imdb_id]
                entity.downloaded_files = existing_entity.downloaded_files

        self._entities_cache[entity.imdb_id] = entity
        await self._save_metadata(entity_dir, entity)

    def get_media_file_path(self, entity: MediaEntity, file_id: str) -> Path:
        """Get the path to a media file."""
        file = next((f for f in entity.downloaded_files if f.id == file_id), None)
        if file is None:
            raise ValueError(f"File {file_id} not found in entity {entity.imdb_id}")
        return self._get_entity_dir(entity) / DOWNLOADED_FILES_DIR / file.file_name

    async def _add_downloaded_file(
        self, entity: MediaEntity, downloaded_file: DownloadedFile, from_path: Path
    ):
        """Add a downloaded file to an entity."""
        if entity.imdb_id not in self._entities_cache:
            raise ValueError(f"Entity {entity.imdb_id} not found in library")
        entity.downloaded_files.append(downloaded_file)
        downloaded_files_dir = self._get_entity_dir(entity) / DOWNLOADED_FILES_DIR
        downloaded_files_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(from_path, downloaded_files_dir / downloaded_file.file_name)
        await self._save_metadata(self._get_entity_dir(entity), entity)
        self._entities_cache[entity.imdb_id] = entity

    def _get_entity_dir(self, entity: MediaEntity) -> Path:
        """Get the directory for an entity."""
        if entity.media_type == MediaType.MOVIE or entity.media_type == MediaType.SERIES:
            return self.entities_path / entity.imdb_id
        elif entity.media_type == MediaType.SEASON:
            if entity.series_id is None:
                raise ValueError(f"Series ID is required for season entity: {entity.imdb_id}")
            return self.entities_path / entity.series_id / SEASONS_DIR / entity.imdb_id
        elif entity.media_type == MediaType.EPISODE:
            if entity.series_id is None:
                raise ValueError(f"Series ID is required for episode entity: {entity.imdb_id}")
            if entity.season_id is None:
                raise ValueError(f"Season ID is required for episode entity: {entity.imdb_id}")
            return (
                self.entities_path
                / entity.series_id
                / SEASONS_DIR
                / entity.season_id
                / EPISODES_DIR
                / entity.imdb_id
            )

        raise ValueError(f"Unexpected media type {entity.media_type} in library")

    async def _load_metadata(self, entity_dir: Path) -> MediaEntity | None:
        """Load metadata from metadata directory."""
        metadata_file = entity_dir / METADATA_FILE
        if not metadata_file.exists():
            return None

        async with aiofiles.open(metadata_file, encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
            return MediaEntity(**data)

    async def _save_metadata(self, entity_dir: Path, entity: MediaEntity):
        """Save metadata to metadata directory."""
        metadata_file = entity_dir / METADATA_FILE
        async with aiofiles.open(metadata_file, mode="w", encoding="utf-8") as f:
            await f.write(entity.model_dump_json())
