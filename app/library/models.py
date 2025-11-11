"""Data models for media library."""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    """Media type enumeration."""

    MOVIE = "movie"
    SERIES = "series"
    EPISODE = "episode"


class Genre(str, Enum):
    """Genre enumeration."""

    ACTION = "action"
    COMEDY = "comedy"
    DRAMA = "drama"
    HORROR = "horror"
    SCIFI = "scifi"
    THRILLER = "thriller"
    DOCUMENTARY = "documentary"
    ANIMATION = "animation"
    FANTASY = "fantasy"
    ROMANCE = "romance"
    CRIME = "crime"
    OTHER = "other"


class VideoQuality(str, Enum):
    """Video quality enumeration."""

    SD = "SD"
    HD_720 = "720p"
    HD_1080 = "1080p"
    UHD_4K = "4K"
    UNKNOWN = "unknown"


class MediaItem(BaseModel):
    """Base media item model."""

    id: str = Field(..., description="Unique identifier for the media item")
    title: str = Field(..., description="Title of the media")
    original_title: str | None = Field(None, description="Original title")
    year: int | None = Field(None, description="Release year")
    genres: list[Genre] = Field(default_factory=list, description="List of genres")
    description: str | None = Field(None, description="Plot description")
    media_type: MediaType = Field(..., description="Type of media")
    file_path: Path | None = Field(None, description="Path to video file")
    poster_path: Path | None = Field(None, description="Path to poster image")
    duration: int | None = Field(None, description="Duration in seconds")
    quality: VideoQuality = Field(default=VideoQuality.UNKNOWN, description="Video quality")
    file_size: int | None = Field(None, description="File size in bytes")
    added_date: datetime = Field(default_factory=datetime.now, description="Date added to library")
    last_watched: datetime | None = Field(None, description="Last time this was watched")
    watch_count: int = Field(default=0, description="Number of times watched")
    rating: float | None = Field(None, description="User rating (0-10)")
    imdb_id: str | None = Field(None, description="IMDB ID")
    tmdb_id: int | None = Field(None, description="TMDB ID")

    class Config:
        use_enum_values = True


class Movie(MediaItem):
    """Movie model."""

    media_type: MediaType = Field(default=MediaType.MOVIE, description="Media type")
    director: str | None = Field(None, description="Director name")
    cast: list[str] = Field(default_factory=list, description="List of main actors")


class Episode(MediaItem):
    """TV series episode model."""

    media_type: MediaType = Field(default=MediaType.EPISODE, description="Media type")
    series_id: str = Field(..., description="ID of the parent series")
    season_number: int = Field(..., description="Season number")
    episode_number: int = Field(..., description="Episode number")
    episode_title: str | None = Field(None, description="Episode-specific title")
    air_date: datetime | None = Field(None, description="Original air date")


class Series(BaseModel):
    """TV series model."""

    id: str = Field(..., description="Unique identifier for the series")
    title: str = Field(..., description="Series title")
    original_title: str | None = Field(None, description="Original title")
    year: int | None = Field(None, description="First air year")
    genres: list[Genre] = Field(default_factory=list, description="List of genres")
    description: str | None = Field(None, description="Series description")
    poster_path: Path | None = Field(None, description="Path to poster image")
    status: str = Field(default="unknown", description="Series status (ongoing/ended)")
    total_seasons: int = Field(default=0, description="Total number of seasons")
    total_episodes: int = Field(default=0, description="Total number of episodes")
    episodes: list[Episode] = Field(default_factory=list, description="List of episodes")
    imdb_id: str | None = Field(None, description="IMDB ID")
    tmdb_id: int | None = Field(None, description="TMDB ID")
    added_date: datetime = Field(default_factory=datetime.now, description="Date added to library")

    class Config:
        use_enum_values = True


class TorrentSearchResult(BaseModel):
    """Torrent search result model."""

    title: str = Field(..., description="Torrent title")
    magnet_link: str = Field(..., description="Magnet link")
    size: str = Field(..., description="File size (human readable)")
    size_bytes: int | None = Field(None, description="File size in bytes")
    seeders: int = Field(default=0, description="Number of seeders")
    leechers: int = Field(default=0, description="Number of leechers")
    source: str = Field(..., description="Source website")
    upload_date: str | None = Field(None, description="Upload date")
    quality: VideoQuality = Field(
        default=VideoQuality.UNKNOWN, description="Detected video quality"
    )

    class Config:
        use_enum_values = True


class DownloadTask(BaseModel):
    """Download task model."""

    id: str = Field(..., description="Unique task ID")
    torrent_name: str = Field(..., description="Torrent name")
    magnet_link: str = Field(..., description="Magnet link")
    status: str = Field(
        default="queued",
        description="Status: queued, downloading, paused, completed, error",
    )
    progress: float = Field(default=0.0, description="Download progress (0-100)")
    download_speed: float = Field(default=0.0, description="Download speed in bytes/sec")
    upload_speed: float = Field(default=0.0, description="Upload speed in bytes/sec")
    seeders: int = Field(default=0, description="Number of seeders")
    peers: int = Field(default=0, description="Number of peers")
    downloaded_bytes: int = Field(default=0, description="Downloaded bytes")
    total_bytes: int = Field(default=0, description="Total bytes")
    eta: int | None = Field(None, description="ETA in seconds")
    save_path: Path | None = Field(None, description="Save path")
    created_at: datetime = Field(default_factory=datetime.now, description="Task creation time")
    completed_at: datetime | None = Field(None, description="Completion time")
    error_message: str | None = Field(None, description="Error message if failed")


class UserWatchProgress(BaseModel):
    """User watch progress for a media item."""

    user_id: int = Field(..., description="Telegram user ID")
    media_id: str = Field(..., description="Media item ID")
    position: int = Field(default=0, description="Last playback position in seconds")
    duration: int = Field(..., description="Total duration in seconds")
    last_watched: datetime = Field(default_factory=datetime.now, description="Last watch time")
    completed: bool = Field(default=False, description="Whether the item was watched completely")

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.duration == 0:
            return 0.0
        return (self.position / self.duration) * 100
