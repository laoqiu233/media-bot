"""MPV player controller for video playback."""

import asyncio
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import mpv
except ImportError:
    mpv = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

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
            self._loading_proc: Any | None = None  # Process for displaying loading.gif or download progress (legacy, for init_flow)
            self._loading_proc_pid: int | None = None  # PID of loading.gif process from init_flow
            self._background_tasks: set[asyncio.Task] = set()  # Keep track of background tasks
            self._event_loop: asyncio.AbstractEventLoop | None = None  # Store event loop reference
            self._downloader: Any | None = None  # Torrent downloader reference for pause/resume
            self._watch_progress_manager: Any | None = None  # Watch progress manager
            self._showing_download_progress: bool = False  # Track if we're showing download progress
            self._progress_update_task: asyncio.Task | None = None  # Task for updating progress image
            self._showing_image: bool = False  # Track if we're showing an image (not video)
            self._current_image_path: Path | None = None  # Current image being displayed
            self._initialized = True

    def initialize(
        self,
        vo: str = "gpu",
        ao: str = "alsa",
        hwdec: str = "auto",
        fullscreen: bool = True,
        downloader: Any | None = None,
        watch_progress_manager: Any | None = None,
    ):
        """Initialize the MPV player with configuration.

        Args:
            vo: Video output driver
            ao: Audio output driver
            fullscreen: Start in fullscreen mode
            hwdec: Hardware decoding mode
            downloader: Optional torrent downloader instance for auto-pause/resume
            watch_progress_manager: Optional watch progress manager for resume functionality
        """
        self._downloader = downloader
        self._watch_progress_manager = watch_progress_manager
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
                ontop=True,  # Keep window on top
            )

            # Register event handlers
            @self._player.property_observer("time-pos")
            def time_observer(_name, value):
                if value is not None:
                    self._trigger_event("time_update", value)

            @self._player.event_callback("end-file")
            def end_file_callback(event):
                # When switching files, loadfile() triggers end-file for the old file.
                # In play(), we set _is_playing = True and _current_file BEFORE calling loadfile(),
                # so if _is_playing is True when end-file fires, it means we're switching files.
                # Don't clear the state in that case - let the file-loaded event handle it.
                event_reason = getattr(event, "reason", None)
                is_switching = self._is_playing
                
                # Only clear playing state if _is_playing is False (real end, not switching files).
                # When switching files, play() sets _is_playing = True BEFORE calling loadfile(),
                # so if _is_playing is True when end-file fires, we're switching files.
                # If reason is "redirect", it's definitely a file switch, so don't clear.
                if event_reason == "redirect":
                    # File switch - don't clear state, let file-loaded event handle it
                    logger.debug("File switch detected (redirect), keeping playing state")
                elif not self._is_playing:
                    # _is_playing is False, so this is a real end of playback
                    self._is_playing = False
                    self._current_file = None
                    logger.debug("Playback ended, cleared playing state")
                else:
                    # _is_playing is True, so we're switching files
                    # Don't clear state - file-loaded event will confirm
                    logger.debug(f"End-file during file switch (is_playing=True, reason={event_reason}), keeping state")
                
                self._trigger_event("playback_finished", event)

                # Save progress when file ends (only if not switching, since we save in play() when switching)
                # This is a backup for natural file endings
                async def save_progress():
                    """Save watch progress for the file that just ended."""
                    # If switching, progress was already saved in play() before loadfile()
                    # Only save here if this is a natural end (not switching)
                    if is_switching:
                        logger.debug("Skipping progress save in end-file (already saved in play() before switch)")
                        return
                    
                    # Get the file that was playing (before _current_file was cleared)
                    # Since we're not switching, _current_file should still be valid
                    file_to_save = self._current_file
                    if (
                        self._watch_progress_manager is not None
                        and file_to_save is not None
                    ):
                        try:
                            # Get final position and duration
                            position = self._player.time_pos if self._player else None
                            duration = self._player.duration if self._player else None
                            
                            if position is not None and duration is not None:
                                await self._watch_progress_manager.update_progress(
                                    file_path=file_to_save,
                                    position=position,
                                    duration=duration,
                                )
                                logger.info(
                                    f"Saved watch progress on end: {file_to_save.name} at {int(position)}s"
                                )
                            else:
                                logger.warning(
                                    f"Could not get position/duration for {file_to_save.name}, progress not saved"
                                )
                        except Exception as e:
                            logger.error(f"Error saving watch progress: {e}", exc_info=True)

                # Resume downloads and show loading.gif (only if not switching files)
                async def resume_downloads_and_show_loading():
                    """Resume downloads and show loading.gif when playback truly ends."""
                    # Check if we're switching files - if _is_playing is True, we're switching
                    # (because play() sets it to True before loadfile())
                    # Don't resume downloads or show loading.gif if switching
                    if self._is_playing:
                        logger.debug("File switch detected (is_playing=True), skipping download resume and loading.gif")
                        return
                    
                    # Resume downloads
                    if self._downloader is not None:
                        try:
                            resumed_count = await self._downloader.resume_all_downloads()
                            if resumed_count > 0:
                                logger.info(
                                    f"Resumed {resumed_count} downloads after playback ended"
                                )
                        except Exception as e:
                            logger.error(f"Error resuming downloads after playback: {e}")

                    # Wait 1.5 seconds for video to fully stop before showing loading.gif
                    await asyncio.sleep(1.5)
                    await self._show_loading_gif()

                # Schedule tasks on main event loop from MPV's callback thread
                loop = self._event_loop
                if loop and loop.is_running():
                    # Always save progress (whether switching or stopping)
                    asyncio.run_coroutine_threadsafe(save_progress(), loop)
                    
                    # Only resume downloads/show loading if not switching
                    asyncio.run_coroutine_threadsafe(resume_downloads_and_show_loading(), loop)
                else:
                    logger.warning(
                        "Event loop not available for saving progress and resuming downloads"
                    )

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
                
                # Start background task to periodically check for active downloads
                # and update display accordingly
                download_check_task = asyncio.create_task(self._periodic_download_check())
                self._background_tasks.add(download_check_task)

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
        """Play a video file with optional resume from saved progress.

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

                # Check for saved watch progress
                resume_position = None
                if self._watch_progress_manager is not None:
                    try:
                        progress = await self._watch_progress_manager.get_progress(file_path)
                        if progress and progress.should_resume:
                            resume_position = progress.position
                            logger.info(
                                f"Found saved progress: {progress.progress_percentage:.1f}% "
                                f"({int(resume_position)}s / {int(progress.duration)}s)"
                            )
                    except Exception as e:
                        logger.error(f"Error checking watch progress: {e}")

                # Pause all downloads when playback starts
                if self._downloader is not None:
                    try:
                        paused_count = await self._downloader.pause_all_downloads()
                        if paused_count > 0:
                            logger.info(f"Paused {paused_count} downloads for playback")
                    except Exception as e:
                        logger.error(f"Error pausing downloads for playback: {e}")

                # Save progress for the currently playing file before switching (if any)
                old_file = self._current_file
                if (
                    old_file is not None
                    and self._watch_progress_manager is not None
                    and old_file != file_path
                ):
                    try:
                        # Get current position and duration before switching
                        position = self._player.time_pos if self._player else None
                        duration = self._player.duration if self._player else None
                        
                        if position is not None and duration is not None:
                            await self._watch_progress_manager.update_progress(
                                file_path=old_file,
                                position=position,
                                duration=duration,
                            )
                            logger.info(
                                f"Saved watch progress before switch: {old_file.name} at {int(position)}s"
                            )
                    except Exception as e:
                        logger.error(f"Error saving watch progress before switch: {e}")

                # If we're showing an image (loading3.gif or download progress), stop it first
                if self._showing_image:
                    # Stop download progress update task if running
                    if self._progress_update_task is not None:
                        self._showing_download_progress = False
                        self._progress_update_task.cancel()
                        try:
                            await self._progress_update_task
                        except asyncio.CancelledError:
                            pass
                        self._progress_update_task = None
                    
                    # Reset image-specific settings for video
                    self._player.loop_file = "no"
                    self._player.keepaspect = True  # Restore aspect ratio for video
                    self._player.panscan = 0.0
                    self._showing_image = False
                    self._current_image_path = None
                    
                    # The video file will be loaded next, which will replace the image

                # Set playing state and current file BEFORE loadfile() to prevent
                # "end-file" event from clearing _is_playing when switching files
                self._is_playing = True
                self._current_file = file_path

                # Load and play the file first (this will switch to video screen)
                # The file-loaded event will handle stopping loading.gif
                self._player.loadfile(str(file_path))

                # Ensure playback starts (unpause if paused)
                self._player.pause = False

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

                # Resume from saved position if available
                if resume_position is not None and video_loaded:
                    try:
                        self._player.seek(resume_position, "absolute")
                        logger.info(f"▶️  Resumed playback from {int(resume_position)}s")
                    except Exception as e:
                        logger.error(f"Error seeking to resume position: {e}")

                # Only stop loading.gif AFTER video is confirmed loaded and visible
                # Wait 1.5 seconds to ensure video is fully rendered and visible before stopping GIF
                if video_loaded:
                    logger.info(
                        "Video loaded and visible - waiting 1.5s before stopping loading.gif"
                    )
                    await asyncio.sleep(1.5)
                    await self._hide_loading_gif()
                else:
                    # Fallback: if we can't detect, wait a bit more then stop anyway
                    logger.warning(
                        "Could not confirm video load, waiting 1.5s then stopping loading.gif anyway"
                    )
                    await asyncio.sleep(1.5)
                    await self._hide_loading_gif()

                # Verify playback actually started
                try:
                    if self._player.time_pos is not None or self._player.duration is not None:
                        logger.info(f"✅ Playback started successfully: {file_path.name}")
                        logger.info(f"   Duration: {self._player.duration}s")
                        if resume_position is not None:
                            logger.info(f"   Resumed from: {int(resume_position)}s")
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
        """Stop playback and save watch progress.

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            # Save watch progress before stopping
            if (
                self._watch_progress_manager is not None
                and self._current_file is not None
            ):
                try:
                    position = self._player.time_pos
                    duration = self._player.duration
                    
                    if position is not None and duration is not None:
                        await self._watch_progress_manager.update_progress(
                            file_path=self._current_file,
                            position=position,
                            duration=duration,
                        )
                        logger.info(
                            f"Saved watch progress on stop: {self._current_file.name} "
                            f"at {int(position)}s"
                        )
                except Exception as e:
                    logger.error(f"Error saving watch progress on stop: {e}")

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
                if curr is None:
                    curr = 0.0
                res = curr + seconds
                self._player.seek(res, "absolute")
                self._player.seek(res, "absolute")  # evil double seek to screw with the haters
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
                    audio_tracks.append(
                        {
                            "id": track.get("id"),
                            "title": track.get("title", ""),
                            "lang": track.get("lang", ""),
                            "codec": track.get("codec", ""),
                            "selected": track.get("selected", False),
                        }
                    )

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

    async def get_subtitle_tracks(self) -> list[dict[str, Any]]:
        """Get list of available subtitle tracks.

        Returns:
            List of subtitle track dictionaries with id, title, lang, codec, etc.
        """
        if not self._player:
            return []

        try:
            track_list = self._player.track_list
            if not track_list:
                return []

            # Filter subtitle tracks
            subtitle_tracks = []
            for track in track_list:
                if track.get("type") == "sub":
                    subtitle_tracks.append({
                        "id": track.get("id"),
                        "title": track.get("title", ""),
                        "lang": track.get("lang", ""),
                        "codec": track.get("codec", ""),
                        "selected": track.get("selected", False),
                    })

            return subtitle_tracks
        except Exception as e:
            logger.error(f"Error getting subtitle tracks: {e}")
            return []

    async def get_current_subtitle_track(self) -> int | None:
        """Get current subtitle track ID.

        Returns:
            Current subtitle track ID or None if no subtitle is active
        """
        if not self._player:
            return None

        try:
            sid = self._player.sid
            # MPV returns None or "no" when no subtitle is selected
            if sid is None or sid == "no":
                return None
            return int(sid) if sid is not None else None
        except Exception:
            return None

    async def set_subtitle_track(self, track_id: int | None) -> bool:
        """Set subtitle track by ID, or remove subtitles if None.

        Args:
            track_id: Subtitle track ID, or None to disable subtitles

        Returns:
            True if successful
        """
        if not self._player:
            return False

        try:
            if track_id is None:
                # Disable subtitles
                self._player.sid = "no"
                logger.info("Subtitles disabled")
            else:
                self._player.sid = track_id
                logger.info(f"Subtitle track set to {track_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting subtitle track: {e}")
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

    async def _periodic_download_check(self) -> None:
        """Background task to periodically check for active downloads and update TV display.
        
        This ensures download progress is shown when downloads start, even if
        _show_loading_gif() wasn't called at that moment.
        """
        while True:
            try:
                await asyncio.sleep(2.0)  # Check every 2 seconds
                
                # Only check if no media is playing
                if self._is_playing:
                    continue
                
                # Check for active downloads
                if self._downloader is None:
                    continue
                
                tasks = await self._downloader.get_all_tasks()
                active_statuses = ["downloading", "checking", "queued"]
                active_tasks = [t for t in tasks if t.status.value in active_statuses]
                
                logger.debug(f"Periodic check: {len(active_tasks)} active downloads, showing_progress={self._showing_download_progress}")
                
                # If we're showing download progress, the update task will handle it
                if self._showing_download_progress:
                    continue
                
                # If there are active downloads but we're not showing progress, show it
                if active_tasks:
                    logger.info(f"Detected {len(active_tasks)} active download(s), showing progress on TV")
                    # Always show progress if there are active downloads (even if process is running)
                    # This handles the case where loading3.gif is showing but downloads just started
                    await self._show_download_progress()
                else:
                    # No active downloads, make sure we're showing loading3.gif
                    if self._loading_proc is None or self._loading_proc.poll() is not None:
                        # No process running, show loading3.gif
                        await self._show_loading_gif()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic download check: {e}", exc_info=True)
                await asyncio.sleep(2.0)  # Wait before retrying

    def _detect_screen_resolution(self) -> tuple[int, int]:
        """Detect screen resolution, defaulting to 1920x1080 if detection fails."""
        try:
            result = subprocess.run(
                ["xrandr"], capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if " connected " in line and "x" in line:
                        parts = line.split()
                        for part in parts:
                            if "x" in part and part[0].isdigit():
                                try:
                                    w, h = map(int, part.split("x"))
                                    if w > 0 and h > 0:
                                        return w, h
                                except ValueError:
                                    continue
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        
        # Default to 1920x1080 (common TV resolution)
        return 1920, 1080

    def _generate_download_progress_image(self, tasks: list[Any], out_path: Path) -> None:
        """Generate an image showing download progress bars.
        
        Args:
            tasks: List of DownloadState objects
            out_path: Path where to save the PNG image
        """
        if Image is None or ImageDraw is None or ImageFont is None:
            logger.warning("PIL not available, cannot generate download progress image")
            return
        
        # Detect screen resolution for responsive design
        screen_width, screen_height = self._detect_screen_resolution()
        
        # Responsive sizing
        scale_factor = min(screen_width / 1920, screen_height / 1080, 1.5)
        padding = int(60 * scale_factor)
        title_height = int(120 * scale_factor)
        item_height = int(140 * scale_factor)
        progress_bar_height = int(40 * scale_factor)
        spacing = int(30 * scale_factor)
        
        # Calculate layout
        width = screen_width
        height = screen_height
        
        # Create base image with gradient background (matching init_flow style)
        img = Image.new("RGB", (width, height), color=(2, 6, 23))  # #020617
        draw = ImageDraw.Draw(img)
        
        # Fast linear gradient
        step = max(4, height // 200)
        for y in range(0, height, step):
            ratio = y / height if height > 0 else 0
            if ratio < 0.45:
                local_ratio = ratio / 0.45 if 0.45 > 0 else 0
                r = int(30 - (30 - 15) * local_ratio)
                g = int(41 - (41 - 23) * local_ratio)
                b = int(59 - (59 - 42) * local_ratio)
            else:
                local_ratio = (ratio - 0.45) / 0.55 if 0.55 > 0 else 0
                r = int(15 - (15 - 2) * local_ratio)
                g = int(23 - (23 - 6) * local_ratio)
                b = int(42 - (42 - 23) * local_ratio)
            
            draw.rectangle([(0, y), (width, min(y + step, height))], fill=(r, g, b))
        
        # Load fonts
        font_size_title = int(44 * scale_factor)
        font_size_item = int(28 * scale_factor)
        font_size_progress = int(24 * scale_factor)
        
        try:
            font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size_title)
            font_item = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size_item)
            font_progress = ImageFont.truetype("DejaVuSans.ttf", font_size_progress)
        except Exception:
            try:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size_title)
                font_item = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size_item)
                font_progress = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size_progress)
            except Exception:
                font_title = ImageFont.load_default()
                font_item = ImageFont.load_default()
                font_progress = ImageFont.load_default()
        
        # Title
        title_text = "Downloads"
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (width - title_width) // 2
        title_y = padding
        
        # Draw title shadow and main title
        draw.text((title_x + 2, title_y + 2), title_text, fill=(0, 0, 0), font=font_title)
        draw.text((title_x, title_y), title_text, fill=(255, 255, 255), font=font_title)
        
        # Draw download items
        y_offset = title_y + title_height + spacing
        max_items = min(len(tasks), 8)  # Show max 8 items
        
        for i, task in enumerate(tasks[:max_items]):
            if y_offset + item_height > height - padding:
                break
            
            # Item name (truncate if too long)
            item_name = task.name[:50] + "..." if len(task.name) > 50 else task.name
            item_y = y_offset + i * (item_height + spacing)
            
            # Draw item name
            draw.text((padding + 2, item_y + 2), item_name, fill=(0, 0, 0), font=font_item)
            draw.text((padding, item_y), item_name, fill=(255, 255, 255), font=font_item)
            
            # Progress bar
            progress = max(0.0, min(100.0, task.progress))
            bar_x = padding
            bar_y = item_y + int(50 * scale_factor)
            bar_width = width - 2 * padding
            bar_height = progress_bar_height
            
            # Progress bar background
            draw.rectangle(
                [(bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height)],
                fill=(15, 23, 42)
            )
            
            # Progress bar fill
            fill_width = int(bar_width * (progress / 100.0))
            if fill_width > 0:
                # Gradient for progress fill
                for x in range(bar_x, bar_x + fill_width, 2):
                    ratio = (x - bar_x) / bar_width if bar_width > 0 else 0
                    r = int(34 + (59 - 34) * ratio)
                    g = int(197 + (130 - 197) * ratio)
                    b = int(94 + (246 - 94) * ratio)
                    draw.rectangle(
                        [(x, bar_y), (min(x + 2, bar_x + fill_width), bar_y + bar_height)],
                        fill=(r, g, b)
                    )
            
            # Progress text with download speed
            progress_text = f"{progress:.1f}%"
            if task.total_wanted > 0:
                downloaded_gb = task.total_done / 1024 / 1024 / 1024
                total_gb = task.total_wanted / 1024 / 1024 / 1024
                progress_text += f" ({downloaded_gb:.2f} / {total_gb:.2f} GB)"
            
            # Add download speed
            if task.download_rate > 0:
                speed_mb = task.download_rate / 1024 / 1024
                progress_text += f" | {speed_mb:.2f} MB/s"
            
            progress_bbox = draw.textbbox((0, 0), progress_text, font=font_progress)
            progress_text_width = progress_bbox[2] - progress_bbox[0]
            progress_text_x = bar_x + bar_width - progress_text_width
            progress_text_y = bar_y + (bar_height - int(24 * scale_factor)) // 2
            
            draw.text((progress_text_x + 1, progress_text_y + 1), progress_text, fill=(0, 0, 0), font=font_progress)
            draw.text((progress_text_x, progress_text_y), progress_text, fill=(220, 240, 255), font=font_progress)
        
        # Save with maximum quality
        img.save(out_path, quality=100, optimize=False)

    async def _update_progress_image(self) -> None:
        """Background task to periodically update the download progress image on TV.
        
        Regenerates the PNG with latest progress data and reloads it in MPV
        without closing the player, providing smooth live updates.
        """
        while self._showing_download_progress:
            try:
                await asyncio.sleep(1.0)  # Update every 1 second for smoother progress updates
                
                if not self._showing_download_progress:
                    break
                
                if self._downloader is None:
                    break
                
                tasks = await self._downloader.get_all_tasks()
                active_statuses = ["downloading", "checking", "queued"]
                active_tasks = [t for t in tasks if t.status.value in active_statuses]
                
                if not active_tasks:
                    # No active downloads, switch back to loading3.gif
                    self._showing_download_progress = False
                    if self._progress_update_task:
                        self._progress_update_task.cancel()
                        self._progress_update_task = None
                    
                    # Stop progress display and show loading3.gif smoothly using same MPV instance
                    project_root = Path(__file__).resolve().parents[2]
                    loading_path = project_root / "loading3.gif"
                    if loading_path.exists() and self._player is not None:
                        try:
                            # Use same MPV instance - just load the new file
                            self._player.loadfile(str(loading_path))
                            self._showing_image = True
                            self._current_image_path = loading_path
                            await asyncio.sleep(0.2)  # Brief wait for image to load
                        except Exception as e:
                            logger.error(f"Error loading loading3.gif: {e}", exc_info=True)
                    break
                
                # Regenerate progress image
                project_root = Path(__file__).resolve().parents[2]
                tmp_dir = project_root / ".setup"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                progress_png = tmp_dir / "download_progress.png"
                progress_png_temp = tmp_dir / "download_progress_temp.png"
                
                # Generate new image to temp file first
                self._generate_download_progress_image(active_tasks, progress_png_temp)
                
                # Atomically replace the old file (ensures MPV sees the change)
                if progress_png.exists():
                    progress_png.unlink()
                shutil.move(progress_png_temp, progress_png)
                
                # Reload image in the same MPV player instance (fast, no process restart)
                if self._player is not None and self._showing_image:
                    try:
                        # Force reload by calling loadfile again - MPV will reload the updated file
                        # This works because we atomically replaced the file, so MPV sees it as changed
                        self._player.loadfile(str(progress_png))
                        self._current_image_path = progress_png
                        # Small delay to ensure MPV has reloaded the file
                        await asyncio.sleep(0.15)
                    except Exception as e:
                        logger.error(f"Error reloading progress image: {e}", exc_info=True)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error updating progress image: {e}", exc_info=True)
                await asyncio.sleep(2.0)  # Wait before retrying

    async def _show_download_progress(self) -> bool:
        """Display download progress on TV if there are active downloads.
        
        Returns:
            True if progress was displayed, False if no active downloads
        """
        if self._downloader is None:
            return False
        
        try:
            tasks = await self._downloader.get_all_tasks()
            # Filter active downloads (downloading, checking, or queued)
            active_statuses = ["downloading", "checking", "queued"]
            active_tasks = [t for t in tasks if t.status.value in active_statuses]
            
            if not active_tasks:
                return False
            
            # If we're already showing download progress, the update task will handle it
            # But if we're showing loading3.gif, we need to switch to progress
            if self._showing_download_progress:
                # Already showing progress, update task will refresh it
                return True
            
            # Generate progress image
            project_root = Path(__file__).resolve().parents[2]
            tmp_dir = project_root / ".setup"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            progress_png = tmp_dir / "download_progress.png"
            
            self._generate_download_progress_image(active_tasks, progress_png)
            
            # Use the same MPV player instance to display image (no new process)
            if self._player is None:
                logger.warning("MPV player not initialized, cannot show download progress")
                return False
            
            try:
                # Stop any legacy subprocess if running
                if self._loading_proc is not None and self._loading_proc.poll() is None:
                    try:
                        self._loading_proc.terminate()
                        await asyncio.wait_for(asyncio.to_thread(self._loading_proc.wait), timeout=0.5)
                    except (asyncio.TimeoutError, Exception):
                        try:
                            self._loading_proc.kill()
                            await asyncio.to_thread(self._loading_proc.wait)
                        except Exception:
                            pass
                    self._loading_proc = None
                
                # Configure MPV for image display
                self._player.loop_file = "inf"
                self._player.keepaspect = False
                self._player.panscan = 1.0
                self._player.fullscreen = True
                
                # Load the image file
                self._player.loadfile(str(progress_png))
                
                # Mark that we're showing an image
                self._showing_image = True
                self._current_image_path = progress_png
                
                # Wait briefly for image to load
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Error loading progress image in MPV: {e}", exc_info=True)
                return False
            
            # Start background task to update progress periodically
            self._showing_download_progress = True
            if self._progress_update_task is None or self._progress_update_task.done():
                self._progress_update_task = asyncio.create_task(self._update_progress_image())
                self._background_tasks.add(self._progress_update_task)
            
            logger.info(f"Displaying download progress for {len(active_tasks)} active download(s)")
            return True
            
        except Exception as e:
            logger.error(f"Error showing download progress: {e}", exc_info=True)
            return False

    async def _show_loading_gif(self) -> None:
        """Display loading3.gif on TV when no media is playing.
        
        First checks for active downloads and shows progress if available.
        """
        # Stop progress update task if running
        if self._progress_update_task is not None:
            self._showing_download_progress = False
            self._progress_update_task.cancel()
            try:
                await self._progress_update_task
            except asyncio.CancelledError:
                pass
            self._progress_update_task = None
        
        # Check for active downloads first
        if await self._show_download_progress():
            return  # Download progress is showing, don't show loading3.gif
        
        # No active downloads, show loading3.gif
        # Check if process is already running (but allow switching from progress to loading3)
        if self._loading_proc is not None:
            # Check if the process is still running
            if self._loading_proc.poll() is None:
                # Check if we're already showing loading3.gif (not progress)
                # If showing progress, we need to switch to loading3.gif
                if not self._showing_download_progress:
                    return  # Already showing loading3.gif and running
                # Otherwise, we're showing progress and need to switch to loading3.gif
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

            # Use the same MPV player instance to display loading3.gif (no new process)
            if self._player is None:
                logger.warning("MPV player not initialized, cannot show loading3.gif")
                return

            try:
                # Stop any legacy subprocess if running
                if self._loading_proc is not None and self._loading_proc.poll() is None:
                    try:
                        self._loading_proc.terminate()
                        await asyncio.wait_for(asyncio.to_thread(self._loading_proc.wait), timeout=0.5)
                    except (asyncio.TimeoutError, Exception):
                        try:
                            self._loading_proc.kill()
                            await asyncio.to_thread(self._loading_proc.wait)
                        except Exception:
                            pass
                    self._loading_proc = None
                
                # Configure MPV for image display
                self._player.loop_file = "inf"
                self._player.keepaspect = False
                self._player.panscan = 1.0
                self._player.fullscreen = True
                
                # Load the loading3.gif file
                self._player.loadfile(str(loading_path))
                
                # Mark that we're showing an image
                self._showing_image = True
                self._current_image_path = loading_path
                
                # Wait briefly for image to load
                await asyncio.sleep(0.3)
                
                logger.info("Displaying loading3.gif on TV using MPV player instance")
            except Exception as e:
                logger.error(f"Error loading loading3.gif in MPV: {e}", exc_info=True)
        except Exception as e:
            logger.debug(f"Could not display loading3.gif: {e}")

    async def _hide_loading_gif(self) -> None:
        """Hide loading3.gif or download progress when media starts playing.
        
        Since we're now using the same MPV instance, the video file loading
        will automatically replace any image being displayed. This function
        just cleans up state and stops background tasks.
        """
        # Stop download progress update task if running
        if self._progress_update_task is not None:
            self._showing_download_progress = False
            self._progress_update_task.cancel()
            try:
                await self._progress_update_task
            except asyncio.CancelledError:
                pass
            self._progress_update_task = None
        
        # Clear image display state (video is now playing, so no image should be shown)
        self._showing_image = False
        self._current_image_path = None
        
        # Handle PID-based process from init_flow (legacy)
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
                logger.info(
                    f"Terminated loading3.gif (PID {self._loading_proc_pid}) - video is now playing"
                )
                self._loading_proc_pid = None
            except Exception as e:
                logger.debug(f"Error terminating loading3.gif by PID: {e}")
                self._loading_proc_pid = None

        # Handle legacy subprocess if still running
        if self._loading_proc is not None:
            try:
                # Wait a tiny bit to ensure video is actually visible
                await asyncio.sleep(0.2)

                # Terminate the loading.gif process
                if self._loading_proc.poll() is None:  # Still running
                    self._loading_proc.terminate()
                    try:
                        # Wait up to 1 second for graceful termination
                        await asyncio.wait_for(asyncio.to_thread(self._loading_proc.wait), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Force kill if it doesn't terminate
                        self._loading_proc.kill()
                        await asyncio.to_thread(self._loading_proc.wait)

                    logger.info("Terminated loading3.gif subprocess - video is now playing")

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
