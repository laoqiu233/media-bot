"""Data models for media library."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    """Media type enumeration."""

    MOVIE = "movie"
    SERIES = "series"
    SEASON = "season"
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


class DownloadedFile(BaseModel):
    """Downloaded file model linking to MediaEntity."""

    id: str = Field(..., description="Unique identifier for the downloaded file")
    media_entity_id: str = Field(..., description="ID of the associated MediaEntity")
    file_name: str = Field(..., description="Name of the video file")
    quality: VideoQuality = Field(default=VideoQuality.UNKNOWN, description="Video quality")
    file_size: int = Field(..., description="File size in bytes")
    downloaded_date: datetime = Field(default_factory=datetime.now, description="Date downloaded")
    source: str | None = Field(None, description="Source torrent name")

    class Config:
        use_enum_values = True


class MediaEntity(BaseModel):
    """Unified media entity model with imdb_id as primary identifier."""

    imdb_id: str = Field(..., description="IMDb ID (primary identifier)")
    title: str = Field(..., description="Title of the media")
    year: int | None = Field(None, description="Release year")
    genres: list[Genre] = Field(default_factory=list, description="List of genres")
    description: str | None = Field(None, description="Plot description")
    poster_url: str | None = Field(None, description="HTTP URL to poster image")
    media_type: MediaType = Field(..., description="Type of media (MOVIE/SERIES/SEASON/EPISODE)")
    added_date: datetime = Field(default_factory=datetime.now, description="Date added to library")
    rating: float | None = Field(None, description="IMDb rating (0-10)")

    # Movie-specific fields
    director: str | None = Field(None, description="Director name (for movies)")
    cast: list[str] = Field(default_factory=list, description="List of main actors (for movies)")

    # Series-specific fields
    status: str | None = Field(None, description="Series status (ongoing/ended)")
    total_seasons: int | None = Field(None, description="Total number of seasons")
    total_episodes: int | None = Field(None, description="Total number of episodes")

    # Season-specific fields
    series_id: str | None = Field(None, description="Parent series IMDb ID (for seasons/episodes)")

    # Episode-specific fields
    season_id: str | None = Field(None, description="Parent season IMDb ID (for episodes)")
    episode_number: int | None = Field(None, description="Episode number (for episodes)")
    episode_title: str | None = Field(None, description="Episode-specific title")
    air_date: datetime | None = Field(None, description="Original air date (for episodes)")

    # Associated files (for movies and episodes)
    downloaded_files: list[DownloadedFile] = Field(
        default_factory=list, description="List of downloaded files"
    )


@dataclass
class DownloadMovie:
    movie: "IMDbTitle"

    def __str__(self) -> str:
        return f"{self.movie.primaryTitle}"


@dataclass
class DownloadSeries:
    series: "IMDbTitle"

    def __str__(self) -> str:
        return f"{self.series.primaryTitle}"


@dataclass
class DownloadSeason:
    series: "IMDbTitle"
    season: "IMDbSeason"

    def __str__(self) -> str:
        return f"{self.series.primaryTitle} season {self.season.season}"


@dataclass
class DownloadEpisode:
    series: "IMDbTitle"
    season: "IMDbSeason"
    episode: "IMDbEpisode"

    def __str__(self) -> str:
        return f"{self.series.primaryTitle} season {self.season.season} episode {self.episode.episodeNumber}"


DownloadIMDbMetadata = DownloadMovie | DownloadSeries | DownloadSeason | DownloadEpisode


@dataclass
class FileMatch:
    """Match between a torrent file and expected content."""

    file_index: int  # Index in torrent
    file_path: str  # Path in torrent
    episode: "IMDbEpisode | None" = None
    movie: "IMDbTitle | None" = None


@dataclass
class MatchedTorrentFiles:
    has_all_requested_content: bool  # Has everything user requested
    matched_files: list[FileMatch]  # Files that will be downloaded
    missing_content: list[str]  # e.g., ["S01E03", "S01E05"]
    warnings: list[str]  # Human-readable warnings
    download_metadata: DownloadIMDbMetadata
    total_files: int


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


# IMDb API models - field names match API response structure (mixedCase intentional)
# ruff: noqa: N815


class IMDbImage(BaseModel):
    """IMDb image model."""

    url: str | None = Field(None, description="Image URL")
    width: int | None = Field(None, description="Image width")
    height: int | None = Field(None, description="Image height")


class IMDbName(BaseModel):
    """IMDb name model (actor, director, etc.)."""

    id: str = Field(..., description="IMDb name ID")
    displayName: str = Field(..., description="Person's display name")

    @property
    def name(self) -> str:
        """Get name (alias for displayName)."""
        return self.displayName


class IMDbRating(BaseModel):
    """IMDb rating model."""

    aggregateRating: float | None = Field(None, description="Average rating (0-10)")
    voteCount: int | None = Field(None, description="Number of votes")


class IMDbCountry(BaseModel):
    """IMDb country model."""

    code: str | None = Field(None, description="ISO country code")
    name: str | None = Field(None, description="Country name")


class IMDbLanguage(BaseModel):
    """IMDb language model."""

    code: str | None = Field(None, description="ISO language code")
    name: str | None = Field(None, description="Language name")


class IMDbInterest(BaseModel):
    """IMDb interest/topic model."""

    id: str | None = Field(None, description="Interest ID")
    name: str | None = Field(None, description="Interest name")


class IMDbMetacritic(BaseModel):
    """IMDb Metacritic score model."""

    score: int | None = Field(None, description="Metacritic score")
    reviewCount: int | None = Field(None, description="Number of reviews")


class IMDbTitle(BaseModel):
    """IMDb title model (movie, TV series, etc.)."""

    id: str = Field(..., description="IMDb title ID (e.g., tt1234567)")
    type: str | None = Field(None, description="Title type (MOVIE, TV_SERIES, etc.)")
    isAdult: bool = Field(default=False, description="Adult content flag")
    primaryTitle: str = Field(..., description="Primary title")
    startYear: int | None = Field(None, description="Release/start year")
    endYear: int | None = Field(None, description="End year (for series)")
    primaryImage: IMDbImage | None = Field(None, description="Primary poster image")
    rating: IMDbRating | None = Field(None, description="Rating information")
    metacritic: IMDbMetacritic | None = Field(None, description="Metacritic information")
    plot: str | None = Field(None, description="Plot summary")
    directors: list[IMDbName] = Field(default_factory=list, description="List of directors")
    writers: list[IMDbName] = Field(default_factory=list, description="List of writers")
    stars: list[IMDbName] = Field(default_factory=list, description="List of stars")
    genres: list[str] = Field(default_factory=list, description="List of genres")
    runtimeSeconds: int | None = Field(None, description="Runtime in seconds")
    originCountries: list[IMDbCountry] = Field(
        default_factory=list, description="List of origin countries"
    )
    spokenLanguages: list[IMDbLanguage] = Field(
        default_factory=list, description="List of spoken languages"
    )
    interests: list[IMDbInterest] = Field(
        default_factory=list, description="List of interests/topics"
    )

    @property
    def poster_url(self) -> str | None:
        """Get poster URL."""
        return self.primaryImage.url if self.primaryImage else None

    @property
    def director_names(self) -> list[str]:
        """Get list of director names."""
        return [d.name for d in self.directors]

    @property
    def rating_value(self) -> float | None:
        """Get rating value."""
        return self.rating.aggregateRating if self.rating else None

    @property
    def vote_count(self) -> int | None:
        """Get vote count."""
        return self.rating.voteCount if self.rating else None

    @property
    def is_movie(self) -> bool:
        """Check if this is a movie."""
        return self.type in ["MOVIE", "movie"]

    @property
    def is_series(self) -> bool:
        """Check if this is a TV series."""
        return self.type in ["TV_SERIES", "tvSeries", "TV_MINI_SERIES", "tvMiniSeries"]

    class Config:
        """Pydantic config."""

        populate_by_name = True


class IMDbSeason(BaseModel):
    """IMDb season model."""

    season: str = Field(..., description="Season number as string")
    episodeCount: int = Field(..., description="Number of episodes in season")

    class Config:
        """Pydantic config."""

        populate_by_name = True


class IMDbEpisode(BaseModel):
    """IMDb episode model."""

    id: str = Field(..., description="IMDb episode ID (e.g., tt1234567)")
    title: str = Field(..., description="Episode title")
    season: str | None = Field(None, description="Season number")
    episodeNumber: int | None = Field(None, description="Episode number")
    rating: IMDbRating | None = Field(None, description="Episode rating")
    plot: str | None = Field(None, description="Episode plot")
    primaryImage: IMDbImage | None = Field(None, description="Episode image")

    @property
    def poster_url(self) -> str | None:
        """Get episode poster URL."""
        return self.primaryImage.url if self.primaryImage else None

    class Config:
        """Pydantic config."""

        populate_by_name = True


class IMDbSearchResponse(BaseModel):
    """IMDb search titles response."""

    titles: list[IMDbTitle] = Field(default_factory=list, description="List of matching titles")

    class Config:
        """Pydantic config."""

        populate_by_name = True


class IMDbSeasonsResponse(BaseModel):
    """IMDb get seasons response."""

    seasons: list[IMDbSeason] = Field(default_factory=list, description="List of seasons")

    class Config:
        """Pydantic config."""

        populate_by_name = True


class IMDbEpisodesResponse(BaseModel):
    """IMDb get episodes response."""

    episodes: list[IMDbEpisode] = Field(default_factory=list, description="List of episodes")
    nextPageToken: str | None = Field(None, description="Pagination token for next page")

    class Config:
        """Pydantic config."""

        populate_by_name = True


# Helper functions for creating MediaEntity from IMDb models


def _map_genre(imdb_genre: str) -> Genre:
    """Map IMDb genre string to Genre enum.

    Args:
        imdb_genre: Genre string from IMDb API (case-insensitive)

    Returns:
        Corresponding Genre enum value
    """
    genre_mapping = {
        "action": Genre.ACTION,
        "comedy": Genre.COMEDY,
        "drama": Genre.DRAMA,
        "horror": Genre.HORROR,
        "sci-fi": Genre.SCIFI,
        "science fiction": Genre.SCIFI,
        "thriller": Genre.THRILLER,
        "documentary": Genre.DOCUMENTARY,
        "animation": Genre.ANIMATION,
        "fantasy": Genre.FANTASY,
        "romance": Genre.ROMANCE,
        "crime": Genre.CRIME,
    }

    normalized = imdb_genre.lower().strip()
    return genre_mapping.get(normalized, Genre.OTHER)


def create_movie_entity(imdb_title: IMDbTitle) -> MediaEntity:
    """Create a MediaEntity from an IMDb movie title.

    Args:
        imdb_title: IMDb title object (should be a movie)

    Returns:
        MediaEntity with movie-specific fields populated

    Raises:
        ValueError: If the title is not a movie type
    """
    if not imdb_title.is_movie:
        raise ValueError(f"Title {imdb_title.id} is not a movie (type: {imdb_title.type})")

    return MediaEntity(
        imdb_id=imdb_title.id,
        title=imdb_title.primaryTitle,
        year=imdb_title.startYear,
        genres=[_map_genre(g) for g in imdb_title.genres],
        description=imdb_title.plot,
        poster_url=imdb_title.poster_url,
        media_type=MediaType.MOVIE,
        rating=imdb_title.rating_value,
        director=imdb_title.directors[0].name if imdb_title.directors else None,
        cast=[star.name for star in imdb_title.stars[:5]],  # Top 5 stars
        status=None,
        total_seasons=None,
        total_episodes=None,
        series_id=None,
        season_id=None,
        episode_number=None,
        episode_title=None,
        air_date=None,
    )


def create_series_entity(imdb_title: IMDbTitle, total_seasons: int | None = None) -> MediaEntity:
    """Create a MediaEntity from an IMDb TV series title.

    Args:
        imdb_title: IMDb title object (should be a TV series)
        total_seasons: Total number of seasons (if known)

    Returns:
        MediaEntity with series-specific fields populated

    Raises:
        ValueError: If the title is not a series type
    """
    if not imdb_title.is_series:
        raise ValueError(f"Title {imdb_title.id} is not a series (type: {imdb_title.type})")

    # Determine status based on endYear
    status = "ended" if imdb_title.endYear else "ongoing"

    return MediaEntity(
        imdb_id=imdb_title.id,
        title=imdb_title.primaryTitle,
        year=imdb_title.startYear,
        genres=[_map_genre(g) for g in imdb_title.genres],
        description=imdb_title.plot,
        poster_url=imdb_title.poster_url,
        media_type=MediaType.SERIES,
        rating=imdb_title.rating_value,
        director=None,
        cast=[star.name for star in imdb_title.stars[:5]],  # Top 5 stars
        status=status,
        total_seasons=total_seasons,
        total_episodes=None,
        series_id=None,
        season_id=None,
        episode_number=None,
        episode_title=None,
        air_date=None,
    )


def create_season_entity(
    series: MediaEntity,
    imdb_season: IMDbSeason,
) -> MediaEntity:
    """Create a MediaEntity for a season.

    Args:
        series: Parent series MediaEntity
        imdb_season: IMDb season object with episode count
        season_imdb_id: Optional IMDb ID for the season (if available)

    Returns:
        MediaEntity with season-specific fields populated

    Raises:
        ValueError: If series is not of type SERIES
    """
    if series.media_type != MediaType.SERIES:
        raise ValueError(f"Parent entity {series.imdb_id} is not a series")

    season_imdb_id = f"{series.imdb_id}_S{imdb_season.season}"

    return MediaEntity(
        imdb_id=season_imdb_id,
        title=f"{series.title} - Season {imdb_season.season}",
        year=series.year,
        genres=series.genres,
        description=f"Season {imdb_season.season} of {series.title}",
        poster_url=series.poster_url,  # Use series poster by default
        media_type=MediaType.SEASON,
        rating=series.rating,
        director=None,
        cast=[],
        status=None,
        total_seasons=None,
        total_episodes=imdb_season.episodeCount,
        series_id=series.imdb_id,
        season_id=None,
        episode_number=None,
        episode_title=None,
        air_date=None,
    )


def create_episode_entity(
    series: MediaEntity,
    season: MediaEntity,
    imdb_episode: IMDbEpisode,
    imdb_episode_detailed: IMDbTitle,
) -> MediaEntity:
    """Create a MediaEntity for an episode.

    Args:
        series: Parent series MediaEntity
        season: Parent season MediaEntity
        imdb_episode: IMDb episode object

    Returns:
        MediaEntity with episode-specific fields populated

    Raises:
        ValueError: If parent entities are not of correct types
    """
    if series.media_type != MediaType.SERIES:
        raise ValueError(f"Series entity {series.imdb_id} is not of type SERIES")
    if season.media_type != MediaType.SEASON:
        raise ValueError(f"Season entity {season.imdb_id} is not of type SEASON")

    # Parse air date if available (IMDb might provide this in different formats)
    air_date = None
    # Note: IMDb API doesn't always provide air dates in the episode model
    # This could be enhanced if the API response includes it

    episode_num = imdb_episode.episodeNumber or 0

    return MediaEntity(
        imdb_id=imdb_episode.id,
        title=imdb_episode_detailed.primaryTitle,
        year=imdb_episode_detailed.startYear,
        genres=[_map_genre(g) for g in imdb_episode_detailed.genres],
        description=imdb_episode_detailed.plot,
        poster_url=imdb_episode_detailed.poster_url,
        media_type=MediaType.EPISODE,
        rating=imdb_episode_detailed.rating_value,
        director=imdb_episode_detailed.directors[0].name
        if imdb_episode_detailed.directors
        else None,
        cast=[star.name for star in imdb_episode_detailed.stars[:5]],
        status=None,
        total_seasons=None,
        total_episodes=None,
        series_id=series.imdb_id,
        season_id=season.imdb_id,
        episode_number=episode_num,
        episode_title=imdb_episode.title,
        air_date=air_date,
    )
