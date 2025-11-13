"""RuTracker authorization screen."""

import asyncio
import logging
import os
import socket
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    RUTRACKER_AUTH_BACK,
    RUTRACKER_AUTH_CHECK,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.init_flow import ensure_rutracker_credentials


def _project_root() -> Path:
    """Get project root directory."""
    # app/bot/screens/ -> project root
    return Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """Detect a likely reachable local IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"




class RuTrackerAuthScreen(Screen):
    """Screen for RuTracker authorization setup."""

    def __init__(self):
        """Initialize RuTracker auth screen."""
        pass

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
        # No MPV cleanup needed - screen doesn't use MPV player
        pass

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
        
        elif query.data == RUTRACKER_AUTH_CHECK:
            # Check if credentials have been loaded
            await query.answer("Checking status...", show_alert=False)
            
            # Reload environment from .env file
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

