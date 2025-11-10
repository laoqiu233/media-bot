"""MPV player controller for video playback."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import mpv
except ImportError:
    mpv = None

logger = logging.getLogger(__name__)


class MPVController:
    """Controller for MPV media player."""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one player instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize MPV controller."""
        if not hasattr(self, "_initialized"):
            self._player: Optional[Any] = None
            self._current_file: Optional[Path] = None
            self._is_playing = False
            self._event_handlers: dict[str, list[Callable]] = {}
            self._initialized = True

    def initialize(
        self,
        vo: str = "gpu",
        ao: str = "alsa",
        fullscreen: bool = True,
        hwdec: str = "auto",
    ):
        """Initialize the MPV player with configuration.

        Args:
            vo: Video output driver
            ao: Audio output driver
            fullscreen: Start in fullscreen mode
            hwdec: Hardware decoding mode
        """
        if mpv is None:
            raise RuntimeError(
                "python-mpv is not installed. Please install it: pip install python-mpv"
            )

        if self._player is not None:
            logger.warning("MPV player already initialized")
            return

        try:
            self._player = mpv.MPV(
                vo=vo,
                ao=ao,
                fullscreen=fullscreen,
                hwdec=hwdec,
                input_default_bindings=True,
                input_vo_keyboard=True,
                osc=True,  # On-screen controller
            )

            # Register event handlers
            @self._player.property_observer("time-pos")
            def time_observer(_name, value):
                if value is not None:
                    self._trigger_event("time_update", value)

            @self._player.event_callback("end-file")
            def end_file_callback(event):
                self._is_playing = False
                self._trigger_event("playback_finished", event)

            @self._player.event_callback("file-loaded")
            def file_loaded_callback(event):
                self._is_playing = True
                self._trigger_event("file_loaded", event)

            logger.info("MPV player initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize MPV player: {e}")
            raise

    def shutdown(self):
        """Shutdown the MPV player."""
        if self._player:
            try:
                self._player.terminate()
                self._player = None
                logger.info("MPV player shut down")
            except Exception as e:
                logger.error(f"Error shutting down MPV player: {e}")

    async def play(self, file_path: Path) -> bool:
        """Play a video file.

        Args:
            file_path: Path to the video file

        Returns:
            True if playback started successfully
        """
        if not self._player:
            logger.error("MPV player not initialized")
            return False

        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        try:
            async with self._lock:
                self._player.play(str(file_path))
                self._current_file = file_path
                self._is_playing = True
                logger.info(f"Started playback: {file_path}")
                return True
        except Exception as e:
            logger.error(f"Error starting playback: {e}")
            return False

    async def pause(self) -> bool:
        """Pause playback.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.pause = True
            self._is_playing = False
            logger.info("Playback paused")
            return True
        except Exception as e:
            logger.error(f"Error pausing playback: {e}")
            return False

    async def resume(self) -> bool:
        """Resume playback.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.pause = False
            self._is_playing = True
            logger.info("Playback resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming playback: {e}")
            return False

    async def stop(self) -> bool:
        """Stop playback.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.stop()
            self._is_playing = False
            self._current_file = None
            logger.info("Playback stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")
            return False

    async def seek(self, seconds: float, relative: bool = True) -> bool:
        """Seek to a position in the video.

        Args:
            seconds: Number of seconds to seek
            relative: If True, seek relative to current position

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            if relative:
                self._player.seek(seconds, "relative")
            else:
                self._player.seek(seconds, "absolute")
            logger.info(f"Seeked {'relative' if relative else 'absolute'}: {seconds}s")
            return True
        except Exception as e:
            logger.error(f"Error seeking: {e}")
            return False

    async def set_volume(self, volume: int) -> bool:
        """Set playback volume.

        Args:
            volume: Volume level (0-100)

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            volume = max(0, min(100, volume))  # Clamp to 0-100
            self._player.volume = volume
            logger.info(f"Volume set to {volume}")
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    async def volume_up(self, step: int = 5) -> bool:
        """Increase volume.

        Args:
            step: Volume increase step

        Returns:
            True if successful
        """
        current_volume = await self.get_volume()
        if current_volume is not None:
            return await self.set_volume(current_volume + step)
        return False

    async def volume_down(self, step: int = 5) -> bool:
        """Decrease volume.

        Args:
            step: Volume decrease step

        Returns:
            True if successful
        """
        current_volume = await self.get_volume()
        if current_volume is not None:
            return await self.set_volume(current_volume - step)
        return False

    async def toggle_pause(self) -> bool:
        """Toggle pause/play state.

        Returns:
            True if successful
        """
        if self._is_playing:
            return await self.pause()
        else:
            return await self.resume()

    async def toggle_fullscreen(self) -> bool:
        """Toggle fullscreen mode.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.fullscreen = not self._player.fullscreen
            return True
        except Exception as e:
            logger.error(f"Error toggling fullscreen: {e}")
            return False

    async def load_subtitle(self, subtitle_path: Path) -> bool:
        """Load a subtitle file.

        Args:
            subtitle_path: Path to subtitle file

        Returns:
            True if successful
        """
        if not self._player or not subtitle_path.exists():
            return False

        try:
            self._player.sub_add(str(subtitle_path))
            logger.info(f"Loaded subtitle: {subtitle_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading subtitle: {e}")
            return False

    async def cycle_subtitle(self) -> bool:
        """Cycle through available subtitles.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.cycle("sub")
            return True
        except Exception as e:
            logger.error(f"Error cycling subtitle: {e}")
            return False

    async def cycle_audio(self) -> bool:
        """Cycle through available audio tracks.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.cycle("audio")
            return True
        except Exception as e:
            logger.error(f"Error cycling audio: {e}")
            return False

    async def get_position(self) -> Optional[float]:
        """Get current playback position in seconds.

        Returns:
            Current position or None
        """
        if not self._player:
            return None

        try:
            return self._player.time_pos
        except Exception:
            return None

    async def get_duration(self) -> Optional[float]:
        """Get total duration in seconds.

        Returns:
            Total duration or None
        """
        if not self._player:
            return None

        try:
            return self._player.duration
        except Exception:
            return None

    async def get_volume(self) -> Optional[int]:
        """Get current volume level.

        Returns:
            Volume level (0-100) or None
        """
        if not self._player:
            return None

        try:
            return int(self._player.volume)
        except Exception:
            return None

    def is_playing(self) -> bool:
        """Check if media is currently playing.

        Returns:
            True if playing
        """
        return self._is_playing

    def get_current_file(self) -> Optional[Path]:
        """Get currently playing file.

        Returns:
            Path to current file or None
        """
        return self._current_file

    async def get_status(self) -> dict:
        """Get player status.

        Returns:
            Dictionary with player status
        """
        return {
            "is_playing": self._is_playing,
            "current_file": str(self._current_file) if self._current_file else None,
            "position": await self.get_position(),
            "duration": await self.get_duration(),
            "volume": await self.get_volume(),
        }

    def on(self, event: str, handler: Callable):
        """Register an event handler.

        Args:
            event: Event name
            handler: Callback function
        """
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)

    def _trigger_event(self, event: str, data: Any = None):
        """Trigger event handlers.

        Args:
            event: Event name
            data: Event data
        """
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"Error in event handler for {event}: {e}")


# Global player instance
player = MPVController()

