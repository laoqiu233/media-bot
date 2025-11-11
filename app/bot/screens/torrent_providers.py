"""Torrent provider selection screen."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import MOVIE_BACK, PROVIDER_SELECT
from app.bot.screens.base import Context, Navigation, RenderOptions, Screen, ScreenHandlerResult
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
        """
        movie = kwargs.get("movie")
        context.update_context(selected_movie=movie)

    async def render(
        self, context: Context
    ) -> tuple[str, InlineKeyboardMarkup, RenderOptions]:
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
        if query.data == MOVIE_BACK:
            return Navigation(next_screen="movie_selection")

        elif query.data.startswith(PROVIDER_SELECT):
            provider = query.data[len(PROVIDER_SELECT) :]
            movie: IMDbMovie = context.get_context().get("selected_movie")

            if movie:
                await query.answer(f"Searching {provider.upper()}...", show_alert=False)

                # Navigate to torrent results with movie and provider
                return Navigation(
                    next_screen="torrent_results",
                    movie=movie,
                    provider=provider,
                )

