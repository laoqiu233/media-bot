"""RuTracker authorization screen."""

import asyncio
import logging
import os
import socket
import subprocess
from pathlib import Path

import qrcode
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    RUTRACKER_AUTH_BACK,
    RUTRACKER_AUTH_CHECK,
    RUTRACKER_AUTH_QR,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.init_flow import _project_root, ensure_rutracker_credentials

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """Detect a likely reachable local IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _generate_qr_png(url: str, out_path: Path) -> None:
    """Generate a QR code PNG image for the given URL.
    
    Args:
        url: URL to encode in QR code
        out_path: Path where to save the PNG image
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_path)


async def _display_with_mpv(image_path: Path) -> subprocess.Popen:
    """Launch mpv to display the provided image fullscreen in a loop.
    
    Returns the process. The caller should wait for the image to actually load
    before stopping any loading screens.
    """
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
        "--video-zoom=0",  # No zoom
        "--video-pan-x=0",  # No horizontal pan
        "--video-pan-y=0",  # No vertical pan
        "--video-align-x=0",  # Center horizontally
        "--video-align-y=0",  # Center vertically
        str(image_path),
    ]
    # Start detached so we can kill later
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for mpv to start and display the image
    # Check process is running and wait for display to be ready
    for _ in range(15):  # Check up to 1.5 seconds to ensure image is visible
        await asyncio.sleep(0.1)
        if proc.poll() is not None:
            # Process exited, something went wrong
            break
    return proc


class RuTrackerAuthScreen(Screen):
    """Screen for RuTracker authorization setup."""

    def __init__(self):
        """Initialize RuTracker auth screen."""
        self._qr_proc: subprocess.Popen | None = None

    def get_name(self) -> str:
        """Get screen name."""
        return "rutracker_auth"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.
        
        Expects kwargs:
            movie: IMDbMovie object (for back navigation)
            movies: List of all movies (for back navigation)
            detailed_movies: Dict of detailed movie data (for back navigation)
            query: Search query (for back navigation)
            page: Current page (for back navigation)
        """
        movie = kwargs.get("movie")
        movies = kwargs.get("movies", [])
        detailed_movies = kwargs.get("detailed_movies", {})
        query = kwargs.get("query", "")
        page = kwargs.get("page", 0)
        
        context.update_context(
            movie=movie,
            movies=movies,
            detailed_movies=detailed_movies,
            query=query,
            page=page,
        )
        
        # Start setup server in background if not already running
        if os.environ.get("RUTRACKER_SETUP_ACTIVE") != "1":
            asyncio.create_task(ensure_rutracker_credentials())

    async def on_exit(self, context: Context) -> None:
        """Called when leaving the screen."""
        # Close QR code display if it's showing
        if self._qr_proc is not None:
            try:
                self._qr_proc.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self._qr_proc.wait), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    self._qr_proc.kill()
                    await asyncio.to_thread(self._qr_proc.wait)
                self._qr_proc = None
            except Exception as e:
                logger.error(f"Error closing QR code display: {e}")
                if self._qr_proc is not None:
                    try:
                        if self._qr_proc.poll() is None:
                            self._qr_proc.kill()
                    except Exception:
                        pass
                    self._qr_proc = None

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the RuTracker authorization screen."""
        state = context.get_context()
        movie = state.get("movie")
        
        # Check if credentials are already configured
        tracker_username = os.getenv("TRACKER_USERNAME")
        tracker_password = os.getenv("TRACKER_PASSWORD")
        has_credentials = bool(tracker_username and tracker_password)
        
        # Detect IP and build setup URL
        host_ip = _detect_local_ip()
        setup_url = f"http://{host_ip}:8766/"
        
        text = "🏴‍☠️ *RuTracker Authorization*\n\n"
        
        if has_credentials:
            text += "✅ Credentials are configured.\n\n"
            text += "You can now use RuTracker to search for torrents.\n\n"
            text += "Click 'Continue' to proceed with RuTracker search."
        else:
            text += "⚠️ RuTracker credentials are required.\n\n"
            text += f"Please open this URL in your browser:\n`{setup_url}`\n\n"
            text += "After submitting your credentials, click 'Check Status' to verify."
        
        keyboard = []
        
        if has_credentials:
            # Continue button - proceed to search
            keyboard.append(
                [InlineKeyboardButton("▶️ Continue", callback_data="rutracker_auth:continue:")]
            )
        else:
            # Display QR code button
            keyboard.append(
                [InlineKeyboardButton("📱 Display QR Code", callback_data=RUTRACKER_AUTH_QR)]
            )
            # Check status button
            keyboard.append(
                [InlineKeyboardButton("🔄 Check Status", callback_data=RUTRACKER_AUTH_CHECK)]
            )
        
        # Back button
        keyboard.append([InlineKeyboardButton("« Back", callback_data=RUTRACKER_AUTH_BACK)])
        
        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        state = context.get_context()
        
        if query.data == RUTRACKER_AUTH_BACK:
            # Navigate back to provider selection
            return Navigation(
                next_screen="torrent_providers",
                movie=state.get("movie"),
                movies=state.get("movies", []),
                detailed_movies=state.get("detailed_movies", {}),
                query=state.get("query", ""),
                page=state.get("page", 0),
            )
        
        elif query.data == RUTRACKER_AUTH_QR:
            # Generate and display QR code on TV screen
            host_ip = _detect_local_ip()
            setup_url = f"http://{host_ip}:8766/"
            
            try:
                await query.answer("Displaying QR code on screen...", show_alert=False)
                
                # Close any existing QR code display
                if self._qr_proc is not None:
                    try:
                        self._qr_proc.terminate()
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(self._qr_proc.wait), timeout=0.5
                            )
                        except asyncio.TimeoutError:
                            self._qr_proc.kill()
                            await asyncio.to_thread(self._qr_proc.wait)
                    except Exception:
                        pass
                    self._qr_proc = None
                
                # Prepare QR code image path
                project_root = _project_root()
                tmp_dir = project_root / ".setup"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                qr_png = tmp_dir / "rutracker_qr.png"
                
                # Generate QR code image
                _generate_qr_png(setup_url, qr_png)
                
                # Display on TV screen using mpv
                self._qr_proc = await _display_with_mpv(qr_png)
                logger.info(f"Displaying RuTracker QR code on screen: {setup_url}")
                
            except Exception as e:
                logger.error(f"Error displaying QR code: {e}")
                await query.answer("Error displaying QR code", show_alert=True)
            
            # Stay on current screen
            return None
        
        elif query.data == RUTRACKER_AUTH_CHECK:
            # Check if credentials have been loaded
            await query.answer("Checking status...", show_alert=False)
            
            # Reload environment from .env file
            from app.init_flow import _project_root
            env_path = _project_root() / ".env"
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("TRACKER_USERNAME="):
                        os.environ["TRACKER_USERNAME"] = line.split("=", 1)[1].strip()
                    elif line.startswith("TRACKER_PASSWORD="):
                        os.environ["TRACKER_PASSWORD"] = line.split("=", 1)[1].strip()
            
            tracker_username = os.getenv("TRACKER_USERNAME")
            tracker_password = os.getenv("TRACKER_PASSWORD")
            
            if tracker_username and tracker_password:
                await query.answer("✅ Credentials loaded successfully!", show_alert=True)
                # Re-render screen to show updated status
                return None
            else:
                await query.answer("❌ Credentials not found. Please submit them via the web form.", show_alert=True)
                # Stay on current screen
                return None
        
        elif query.data == "rutracker_auth:continue:":
            # Credentials are configured, proceed to search
            movie = state.get("movie")
            if movie:
                await query.answer("Searching RuTracker...", show_alert=False)
                return Navigation(
                    next_screen="torrent_results",
                    movie=movie,
                    provider="rutracker",
                    movies=state.get("movies", []),
                    detailed_movies=state.get("detailed_movies", {}),
                    query=state.get("query", ""),
                    movie_page=state.get("page", 0),
                )
        
        return None

