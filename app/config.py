"""Configuration management for the media bot."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

class TrackerConfig(BaseModel):
    proxy: str | None = None
    username: str | None = None
    password: str | None = None

class TelegramConfig(BaseModel):
    """Telegram bot configuration."""

    bot_token: str = Field(..., description="Telegram bot API token")
    authorized_users: list[str] = Field(
        default_factory=list,
        description="List of authorized Telegram usernames (without @)",
    )


class MediaLibraryConfig(BaseModel):
    """Media library configuration."""

    library_path: Path = Field(
        default=Path.home() / "media_library",
        description="Root path for media library",
    )
    download_path: Path = Field(
        default=Path.home() / "downloads",
        description="Path for downloading torrents",
    )
    movies_path: Path | None = None
    series_path: Path | None = None

    def __init__(self, **data):
        super().__init__(**data)
        # Set derived paths
        self.movies_path = self.library_path / "movies"
        self.series_path = self.library_path / "series"

        # Create directories if they don't exist
        self.library_path.mkdir(parents=True, exist_ok=True)
        self.download_path.mkdir(parents=True, exist_ok=True)
        self.movies_path.mkdir(parents=True, exist_ok=True)
        self.series_path.mkdir(parents=True, exist_ok=True)


class MPVConfig(BaseModel):
    """MPV player configuration."""

    vo: str = Field(default="gpu", description="Video output driver")
    ao: str = Field(default="alsa", description="Audio output driver")
    fullscreen: bool = Field(default=True, description="Start in fullscreen mode")
    hwdec: str = Field(default="auto", description="Hardware decoding")


class CECConfig(BaseModel):
    """HDMI-CEC configuration."""

    enabled: bool = Field(default=True, description="Enable CEC control")
    device: str = Field(default="/dev/cec0", description="CEC device path")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format",
    )


class Config(BaseModel):
    """Main application configuration."""

    tracker: TrackerConfig
    telegram: TelegramConfig
    media_library: MediaLibraryConfig = Field(default_factory=MediaLibraryConfig)
    mpv: MPVConfig = Field(default_factory=MPVConfig)
    cec: CECConfig = Field(default_factory=CECConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config() -> Config:
    """Load configuration from environment variables."""
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is required. "
            "Please set it in .env file or environment."
        )

    # Load authorized users from comma-separated env var
    authorized_users_str = os.getenv("AUTHORIZED_USERS", "")
    authorized_users = [user.strip() for user in authorized_users_str.split(",") if user.strip()]

    media_library_path = os.getenv("MEDIA_LIBRARY_PATH")
    download_path = os.getenv("DOWNLOAD_PATH")

    mpv_vo = os.getenv("MPV_VO", "gpu")
    mpv_ao = os.getenv("MPV_AO", "alsa")

    cec_enabled = os.getenv("CEC_ENABLED", "true").lower() == "true"
    cec_device = os.getenv("CEC_DEVICE", "/dev/cec0")

    log_level = os.getenv("LOG_LEVEL", "INFO")

    tracker_proxy = os.getenv("TRACKER_PROXY")
    tracker_username = os.getenv("TRACKER_USERNAME")
    tracker_password = os.getenv("TRACKER_PASSWORD")
    config_data = {
        "tracker": {
            "proxy": tracker_proxy,
            "username": tracker_username,
            "password": tracker_password
        },
        "telegram": {
            "bot_token": telegram_token,
            "authorized_users": authorized_users,
        },
        "media_library": {},
        "mpv": {"vo": mpv_vo, "ao": mpv_ao},
        "cec": {"enabled": cec_enabled, "device": cec_device},
        "logging": {"level": log_level},
    }

    if media_library_path:
        config_data["media_library"]["library_path"] = Path(media_library_path)
    if download_path:
        config_data["media_library"]["download_path"] = Path(download_path)

    config = Config(**config_data)
    return config


# Global config instance (to be initialized in main)
config: Config | None = None
