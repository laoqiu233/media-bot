"""Search screen for finding movies via IMDb."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import SEARCH_BACK
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.imdb_client import IMDbClient

logger = logging.getLogger(__name__)


class SearchScreen(Screen):
    """Screen for searching movies via IMDb."""

    def __init__(self, imdb_client: IMDbClient):
        """Initialize search screen.

        Args:
            imdb_client: IMDb API client
        """
        self.imdb_client = imdb_client

    def get_name(self) -> str:
        """Get screen name."""
        return "search"

    async def render(self, context: Context) -> ScreenRenderResult:
        state = context.get_context()
        query = state.get("query", "")
        no_results = state.get("no_results", False)
        error = state.get("error")

        # If there was an error
        if error:
            text = (
                "🔍 *Search for movies and series*\n\n"
                f"❌ Error: {error}\n\n"
                "Type a movie or series name to try again."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # If no results found after search
        if no_results and query:
            text = (
                "🔍 *Search for movies and series*\n\n"
                f"No movies found for: _{query}_\n\n"
                "Try typing a different movie or series name."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Default state (ready for search)
        text = (
            "🔍 *Search for movies and series*\n\n"
            "Type the name of a movie or series to search IMDb.\n\n"
            "You'll be able to browse results and select torrents."
        )
        keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def on_enter(self, context: Context, **kwargs) -> None:
        # Clear any previous state - always ready for new search
        context.update_context(
            query="",
            no_results=False,
            error=None,
        )

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == SEARCH_BACK:
            return Navigation(next_screen="main_menu")

    async def handle_message(self, message: Message, context: Context) -> ScreenHandlerResult:
        text = message.text
        if text is None:
            return

        try:
            # Search IMDb for movies
            results = await self.imdb_client.search_titles(text, limit=20)

            if not results:
                context.update_context(query=text, no_results=True, error=None)
                return

            # Navigate to movie selection with results
            return Navigation(next_screen="movie_selection", titles=results, query=text)

        except Exception as e:
            logger.error(f"Error searching IMDb: {e}")
            context.update_context(query=text, no_results=False, error=str(e))
