"""MPV player controller for video playback."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import mpv
except ImportError:
    mpv = None

logger = logging.getLogger(__name__)


class MPVController:
    """Controller for MPV media player."""

    _instance = None
    _lock = asyncio.Lock()
    _seeking = False

    def __new__(cls):
        """Singleton pattern to ensure only one player instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize MPV controller."""
        if not hasattr(self, "_initialized"):
            self._player: Any | None = None
            self._current_file: Path | None = None
            self._is_playing = False
            self._event_handlers: dict[str, list[Callable]] = {}
            self._loading_proc: Any | None = None  # Process for displaying loading.gif
            self._loading_proc_pid: int | None = None  # PID of loading.gif process from init_flow
            self._background_tasks: set[asyncio.Task] = set()  # Keep track of background tasks
            self._event_loop: asyncio.AbstractEventLoop | None = None  # Store event loop reference
            self._downloader: Any | None = None  # Torrent downloader reference for pause/resume
            self._initialized = True

    def initialize(
        self,
        vo: str = "gpu",
        ao: str = "alsa",
        hwdec: str = "auto",
        fullscreen: bool = True,
        downloader: Any | None = None,
    ):
        """Initialize the MPV player with configuration.

        Args:
            vo: Video output driver
            ao: Audio output driver
            fullscreen: Start in fullscreen mode
            hwdec: Hardware decoding mode
            downloader: Optional torrent downloader instance for auto-pause/resume
        """
        self._downloader = downloader
        if mpv is None:
            raise RuntimeError(
                "python-mpv is not installed. Please install it: pip install python-mpv"
            )

        if self._player is not None:
            logger.warning("MPV player already initialized")
            return

        # Store event loop reference for use in callbacks
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - try to get or create one
            try:
                # Try to get existing event loop (may not be running)
                self._event_loop = asyncio.get_event_loop()
            except RuntimeError:
                # No event loop exists, create a new one
                self._event_loop = asyncio.new_event_loop()
                # Set it as the event loop for this thread
                asyncio.set_event_loop(self._event_loop)

        try:
            self._player = mpv.MPV(
                vo=vo,
                ao=ao,
                fullscreen=True,  # Don't force fullscreen - display at native size
                hwdec=hwdec,
                input_default_bindings=True,
                input_vo_keyboard=True,
                osc=True,  # On-screen controller
                border=False,  # Remove border
                window_dragging=False,  # Disable window dragging
                keepaspect=True,  # Maintain aspect ratio (native size)
                panscan=0.0,  # No pan/scan (native size)
                video_unscaled="no",  # Allow scaling but maintain aspect
            )

            # Register event handlers
            @self._player.property_observer("time-pos")
            def time_observer(_name, value):
                if value is not None:
                    self._trigger_event("time_update", value)

            @self._player.event_callback("end-file")
            def end_file_callback(event):
                self._is_playing = False
                self._current_file = None
                self._trigger_event("playback_finished", event)
                
                # Resume all downloads when playback ends
                async def resume_downloads_and_show_loading():
                    # Resume downloads first
                    if self._downloader is not None:
                        try:
                            resumed_count = await self._downloader.resume_all_downloads()
                            if resumed_count > 0:
                                logger.info(f"Resumed {resumed_count} downloads after playback ended")
                        except Exception as e:
                            logger.error(f"Error resuming downloads after playback: {e}")
                    
                    # Wait 1.5 seconds for video to fully stop before showing loading.gif
                    await asyncio.sleep(1.5)
                    await self._show_loading_gif()
                
                # Schedule task on main event loop from MPV's callback thread
                loop = self._event_loop
                if loop and loop.is_running():
                    # Use run_coroutine_threadsafe to schedule from MPV's callback thread
                    future = asyncio.run_coroutine_threadsafe(
                        resume_downloads_and_show_loading(), loop
                    )
                    # Store future to prevent garbage collection
                    # Note: We don't need to await it, it's fire-and-forget
                else:
                    logger.warning("Event loop not available for resuming downloads and showing loading gif")

            @self._player.event_callback("file-loaded")
            def file_loaded_callback(event):
                self._is_playing = True
                self._trigger_event("file_loaded", event)
                # Hide loading.gif when file loads - schedule on main event loop from MPV's thread
                loop = self._event_loop
                if loop and loop.is_running():
                    # Use run_coroutine_threadsafe to schedule from MPV's callback thread
                    asyncio.run_coroutine_threadsafe(self._hide_loading_gif(), loop)
            
            @self._player.event_callback("playback-restart")
            def playback_restart_callback(event):
                """Called when playback actually starts/restarts."""
                self._is_playing = True
                # Also hide loading.gif when playback starts (fallback) - schedule on main event loop
                loop = self._event_loop
                if loop and loop.is_running():
                    # Use run_coroutine_threadsafe to schedule from MPV's callback thread
                    asyncio.run_coroutine_threadsafe(self._hide_loading_gif(), loop)

            logger.info("MPV player initialized successfully")
            
            # Show loading.gif when player is idle (no media playing)
            # This will only run if init_flow has finished (no SETUP_ACTIVE env var)
            # Check if setup is active to avoid conflicts with init_flow's loading.gif
            import os
            if not os.getenv("MEDIA_BOT_SETUP_ACTIVE"):
                # Setup is complete, show loading.gif if no media is playing
                if not self._is_playing:
                    asyncio.create_task(self._show_loading_gif())

        except Exception as e:
            logger.error(f"Failed to initialize MPV player: {e}")
            raise

    def shutdown(self):
        """Shutdown the MPV player."""
        # Terminate loading.gif only on shutdown
        if self._loading_proc is not None:
            try:
                self._loading_proc.terminate()
                self._loading_proc.wait(timeout=2)
            except Exception:
                pass
            self._loading_proc = None
        
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
            logger.error("MPV player not initialized. Call initialize() first.")
            return False

        # Convert to Path if string
        if isinstance(file_path, str):
            file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        try:
            async with self._lock:
                logger.info(f"Starting playback of: {file_path}")
                logger.info(f"File size: {file_path.stat().st_size / (1024*1024):.2f} MB")

                # Pause all downloads when playback starts
                if self._downloader is not None:
                    try:
                        paused_count = await self._downloader.pause_all_downloads()
                        if paused_count > 0:
                            logger.info(f"Paused {paused_count} downloads for playback")
                    except Exception as e:
                        logger.error(f"Error pausing downloads for playback: {e}")

                # Load and play the file first (this will switch to video screen)
                # The file-loaded event will handle stopping loading.gif
                self._player.loadfile(str(file_path))
                self._current_file = file_path

                # Ensure playback starts (unpause if paused)
                self._player.pause = False
                self._is_playing = True

                # Wait for video to actually load and be visible
                # Check if video is playing by waiting for time-pos or duration
                max_wait = 2.0  # Maximum wait time
                waited = 0.0
                video_loaded = False
                
                while waited < max_wait:
                    await asyncio.sleep(0.1)
                    waited += 0.1
                    
                    # Check if video is actually playing/loaded
                    try:
                        if self._player.time_pos is not None or self._player.duration is not None:
                            video_loaded = True
                            break
                    except Exception:
                        pass
                
                # Only stop loading.gif AFTER video is confirmed loaded and visible
                # Wait 1.5 seconds to ensure video is fully rendered and visible before stopping GIF
                if video_loaded:
                    logger.info("Video loaded and visible - waiting 1.5s before stopping loading.gif")
                    await asyncio.sleep(1.5)
                    await self._hide_loading_gif()
                else:
                    # Fallback: if we can't detect, wait a bit more then stop anyway
                    logger.warning("Could not confirm video load, waiting 1.5s then stopping loading.gif anyway")
                    await asyncio.sleep(1.5)
                    await self._hide_loading_gif()

                # Verify playback actually started
                try:
                    if self._player.time_pos is not None or self._player.duration is not None:
                        logger.info(f"✅ Playback started successfully: {file_path.name}")
                        logger.info(f"   Duration: {self._player.duration}s")
                    else:
                        logger.warning("⚠️  File loaded but playback status unknown")
                        logger.warning(
                            "   This is normal on systems without video output (e.g., macOS)"
                        )
                        logger.warning(
                            "   On Raspberry Pi with HDMI, playback should work correctly"
                        )
                except Exception as e:
                    logger.debug(f"Could not read playback status: {e}")

                return True
        except AttributeError as e:
            logger.error(f"MPV player method not available: {e}")
            logger.error("Make sure python-mpv is properly installed")
            return False
        except Exception as e:
            logger.error(f"Error starting playback: {e}", exc_info=True)
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
            
            # Ensure downloads are paused when video is paused
            # This handles cases where downloads might have started/resumed after play()
            if self._downloader is not None:
                try:
                    paused_count = await self._downloader.pause_all_downloads()
                    if paused_count > 0:
                        logger.info(f"Paused {paused_count} downloads when video was paused")
                except Exception as e:
                    logger.error(f"Error pausing downloads when video paused: {e}")
            
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
            await self._show_loading_gif()
            await asyncio.sleep(3)
            logger.info("Gif started")
            self._player.stop()
            self._is_playing = False
            self._current_file = None
            
            # Resume all downloads when playback is stopped manually
            if self._downloader is not None:
                try:
                    resumed_count = await self._downloader.resume_all_downloads()
                    if resumed_count > 0:
                        logger.info(f"Resumed {resumed_count} downloads after stop command")
                except Exception as e:
                    logger.error(f"Error resuming downloads after stop: {e}")
            
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

        async def unseek(self):
            await asyncio.sleep(1.5)
            self._seeking = False

        try:
            if self._seeking:
                return False

            self._seeking = True
            asyncio.create_task(unseek(self))

            if relative:
                curr = await self.get_position()
                res = curr + seconds
                self._player.seek(res, "absolute")
                self._player.seek(res, "absolute") # evil double seek to screw with the haters
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

    async def get_audio_tracks(self) -> list[dict[str, Any]]:
        """Get list of available audio tracks.

        Returns:
            List of audio track dictionaries with id, title, lang, codec, etc.
        """
        if not self._player:
            return []

        try:
            track_list = self._player.track_list
            if not track_list:
                return []

            # Filter audio tracks
            audio_tracks = []
            for track in track_list:
                if track.get("type") == "audio":
                    audio_tracks.append({
                        "id": track.get("id"),
                        "title": track.get("title", ""),
                        "lang": track.get("lang", ""),
                        "codec": track.get("codec", ""),
                        "selected": track.get("selected", False),
                    })

            return audio_tracks
        except Exception as e:
            logger.error(f"Error getting audio tracks: {e}")
            return []

    async def get_current_audio_track(self) -> int | None:
        """Get current audio track ID.

        Returns:
            Current audio track ID or None
        """
        if not self._player:
            return None

        try:
            aid = self._player.audio
            return int(aid) if aid is not None else None
        except Exception:
            return None

    async def set_audio_track(self, track_id: int) -> bool:
        """Set audio track by ID.

        Args:
            track_id: Audio track ID

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            self._player.audio = track_id
            logger.info(f"Audio track set to {track_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting audio track: {e}")
            return False

    async def get_position(self) -> float | None:
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

    async def get_duration(self) -> float | None:
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

    async def get_volume(self) -> int | None:
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

    async def is_paused(self) -> bool:
        """Check if playback is paused.

        Returns:
            True if paused
        """
        if not self._player:
            return False

        try:
            return bool(self._player.pause)
        except Exception:
            return False

    def get_current_file(self) -> Path | None:
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
            "is_paused": await self.is_paused(),
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

    async def _show_loading_gif(self) -> None:
        """Display loading3.gif on TV when no media is playing."""
        if self._loading_proc is not None:
            # Check if the process is still running
            if self._loading_proc.poll() is None:
                return  # Already showing and running
            else:
                # Process died, clear it
                self._loading_proc = None
        
        # Check if init_flow left a loading.gif process running
        import os
        loading_pid_str = os.environ.get("MEDIA_BOT_LOADING_PID")
        if loading_pid_str:
            try:
                loading_pid = int(loading_pid_str)
                # Check if process is still running using a simple method
                import subprocess
                try:
                    # Use kill -0 to check if process exists (doesn't actually kill it)
                    result = subprocess.run(
                        ["kill", "-0", str(loading_pid)],
                        capture_output=True,
                        timeout=0.1,
                    )
                    if result.returncode == 0:
                        # Process exists, reuse it
                        logger.info(f"Reusing existing loading3.gif process (PID {loading_pid})")
                        os.environ.pop("MEDIA_BOT_LOADING_PID", None)
                        # Store PID for later cleanup
                        self._loading_proc_pid = loading_pid
                        # Create a dummy Popen-like object to track it
                        # We'll use the PID directly in _hide_loading_gif
                        return
                except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                    # Process doesn't exist or kill command failed
                    os.environ.pop("MEDIA_BOT_LOADING_PID", None)
            except ValueError:
                # Invalid PID
                os.environ.pop("MEDIA_BOT_LOADING_PID", None)
        
        try:
            import subprocess
            from pathlib import Path
            
            # Find project root (assuming this file is in app/player/)
            project_root = Path(__file__).resolve().parents[2]
            loading_path = project_root / "loading3.gif"
            
            if not loading_path.exists():
                logger.debug("loading3.gif not found, skipping display")
                return
            
            # Display loading3.gif with mpv (similar to QR code display)
            cmd = [
                "mpv",
                "--no-terminal",
                "--force-window=yes",
                "--image-display-duration=inf",
                "--loop-file=inf",
                "--fs",
                "--no-border",
                "--no-window-dragging",
                "--no-input-default-bindings",
                "--no-input-vo-keyboard",
                "--keepaspect=no",  # Stretch to fill screen (no black bars)
                "--video-unscaled=no",  # Allow scaling
                "--panscan=1.0",  # Fill screen completely
                "--video-margin-ratio-left=0",
                "--video-margin-ratio-right=0",
                "--video-margin-ratio-top=0",
                "--video-margin-ratio-bottom=0",
                "--fullscreen",
                str(loading_path),
            ]
            self._loading_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            logger.info("Displaying loading3.gif on TV (media loading...)")
        except Exception as e:
            logger.debug(f"Could not display loading3.gif: {e}")

    async def _hide_loading_gif(self) -> None:
        """Hide loading3.gif when media starts playing.
        
        Actually terminate the loading3.gif process to avoid running 2 MPV instances
        on Raspberry Pi, which causes performance issues.
        """
        # Handle PID-based process from init_flow
        if self._loading_proc_pid is not None:
            try:
                import subprocess
                # Wait a tiny bit to ensure video is actually visible
                await asyncio.sleep(0.2)
                # Kill the process by PID
                subprocess.run(
                    ["kill", str(self._loading_proc_pid)],
                    capture_output=True,
                    timeout=1.0,
                )
                logger.info(f"Terminated loading3.gif (PID {self._loading_proc_pid}) - video is now playing")
                self._loading_proc_pid = None
            except Exception as e:
                logger.debug(f"Error terminating loading3.gif by PID: {e}")
                self._loading_proc_pid = None
        
        if self._loading_proc is None:
            return
        
        try:
            # Wait a tiny bit to ensure video is actually visible
            await asyncio.sleep(0.2)
            
            # Terminate the loading.gif process
            if self._loading_proc.poll() is None:  # Still running
                self._loading_proc.terminate()
                try:
                    # Wait up to 1 second for graceful termination
                    await asyncio.wait_for(
                        asyncio.to_thread(self._loading_proc.wait), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Force kill if it doesn't terminate
                    self._loading_proc.kill()
                    await asyncio.to_thread(self._loading_proc.wait)
                
                logger.info("Terminated loading3.gif - video is now playing")
            
            self._loading_proc = None
        except Exception as e:
            logger.debug(f"Error terminating loading3.gif: {e}")
            # Try to kill it anyway
            try:
                if self._loading_proc and self._loading_proc.poll() is None:
                    self._loading_proc.kill()
            except Exception:
                pass
            self._loading_proc = None


# Global player instance
player = MPVController()
