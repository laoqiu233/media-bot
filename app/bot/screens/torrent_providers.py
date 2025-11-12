"""Torrent provider selection screen."""

import logging
import os

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import MOVIE_BACK, PROVIDER_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.models import IMDbMovie

logger = logging.getLogger(__name__)


class TorrentProvidersScreen(Screen):
    """Screen for selecting a torrent provider."""

    def get_name(self) -> str:
        """Get screen name."""
        return "torrent_providers"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.

        Expects kwargs:
            movie: IMDbMovie object
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
            selected_movie=movie,
            movies=movies,
            detailed_movies=detailed_movies,
            query=query,
            page=page,
        )

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the provider selection screen."""
        state = context.get_context()
        movie: IMDbMovie | None = state.get("selected_movie")

        if not movie:
            text = "⚠️ *Error*\n\nNo movie selected."
            keyboard = [[InlineKeyboardButton("« Back", callback_data=MOVIE_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        text = f"🎬 *{movie.primaryTitle}*"
        if movie.startYear:
            text += f" ({movie.startYear})"
        text += "\n\n"

        text += "📥 *Select Torrent Provider*\n\n"
        text += "Choose where to search for torrents:"

        # Define available providers
        providers = [
            {"name": "YTS", "emoji": "🎥", "description": "High quality movies"},
            {"name": "RuTracker", "emoji": "🏴‍☠️", "description": "You know what this is"},
        ]

        keyboard = []

        # Add provider buttons
        for provider in providers:
            button_text = f"{provider['emoji']} {provider['name']} - {provider['description']}"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{PROVIDER_SELECT}{provider['name'].lower()}"
                    )
                ]
            )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Movies", callback_data=MOVIE_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        state = context.get_context()
        
        if query.data == MOVIE_BACK:
            # Pass back the movie list context for proper restoration
            return Navigation(
                next_screen="movie_selection",
                movies=state.get("movies", []),
                detailed_movies=state.get("detailed_movies", {}),
                query=state.get("query", ""),
                page=state.get("page", 0),
            )

        elif query.data.startswith(PROVIDER_SELECT):
            provider = query.data[len(PROVIDER_SELECT) :]
            movie: IMDbMovie = state.get("selected_movie")

            if movie:
                # Check if RuTracker credentials are needed
                if provider == "rutracker":
                    tracker_username = os.getenv("TRACKER_USERNAME")
                    tracker_password = os.getenv("TRACKER_PASSWORD")
                    
                    if not tracker_username or not tracker_password:
                        # Credentials missing - navigate to authorization screen
                        await query.answer("RuTracker credentials required", show_alert=True)
                        
                        # Navigate to RuTracker authorization screen
                        return Navigation(
                            next_screen="rutracker_auth",
                            movie=movie,
                            movies=state.get("movies", []),
                            detailed_movies=state.get("detailed_movies", {}),
                            query=state.get("query", ""),
                            page=state.get("page", 0),
                        )
                
                await query.answer(f"Searching {provider.upper()}...", show_alert=False)

                # Navigate to torrent results with movie, provider, and context for back navigation
                return Navigation(
                    next_screen="torrent_results",
                    movie=movie,
                    provider=provider,
                    movies=state.get("movies", []),
                    detailed_movies=state.get("detailed_movies", {}),
                    query=state.get("query", ""),
                    movie_page=state.get("page", 0),
                )
