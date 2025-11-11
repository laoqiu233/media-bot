"""Search screen for finding and downloading torrents."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    SEARCH_BACK,
    SEARCH_DOWNLOAD,
    SEARCH_NEXT_PAGE,
    SEARCH_PREV_PAGE,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class SearchScreen(Screen):
    """Screen for searching torrents."""

    def __init__(self, searcher, downloader):
        """Initialize search screen.

        Args:
            searcher: Torrent searcher
            downloader: Torrent downloader
        """
        self.searcher = searcher
        self.downloader = downloader

    def get_name(self) -> str:
        """Get screen name."""
        return "search"

    async def render(self, context: Context) -> ScreenRenderResult:
        state = context.get_context()
        results = state.get("results", [])
        page = state.get("page", 0)
        query = state.get("query", "")
        no_results = state.get("no_results", False)
        error = state.get("error")

        # If there was an error
        if error:
            text = (
                "🔍 *Search for Content*\n\n"
                f"❌ Error: {error}\n\n"
                "Type a search term to try again."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
            return text, InlineKeyboardMarkup(keyboard)

        # If no results found after search
        if no_results and query:
            text = (
                "🔍 *Search for Content*\n\n"
                f"No results found for: _{query}_\n\n"
                "Try typing a different search term."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
            return text, InlineKeyboardMarkup(keyboard)

        # If no results yet (first time on search screen)
        if not results:
            text = (
                "🔍 *Search for Content*\n\n"
                "Type the name of a movie or TV series to find.\n\n"
                "I'll search across multiple torrent sources."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)]]
            return text, InlineKeyboardMarkup(keyboard)

        # Show results
        items_per_page = 5
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]

        text = f"🔍 *Search Results for:* _{query}_\n\n"
        text += f"Found {len(results)} results (page {page + 1}/{(len(results) - 1) // items_per_page + 1})\n\n"

        # Show results with details in text
        for i, result in enumerate(page_results):
            text += f"{i + 1}. *{result.title[:50]}{'...' if len(result.title) > 50 else ''}*\n"
            text += f"   📁 {result.quality} • {result.size} • 🌱 {result.seeders} seeders\n\n"

        text += "💡 _Type anything to search again_"

        keyboard = []

        # Add result buttons - simple numbered buttons
        for i, result in enumerate(page_results):
            actual_idx = start_idx + i
            button_text = f"{i + 1}. {result.title[:35]}"
            if len(button_text) > 45:
                button_text = button_text[:42] + "..."

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{SEARCH_DOWNLOAD}{actual_idx}")]
            )

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=SEARCH_PREV_PAGE))
        if end_idx < len(results):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=SEARCH_NEXT_PAGE))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Bottom buttons
        keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data=SEARCH_BACK)])

        return text, InlineKeyboardMarkup(keyboard)

    async def on_enter(self, context: Context, **kwargs) -> None:
        # Clear any previous state - always ready for new search
        context.update_context(
            results=[],
            query="",
            page=0,
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

        elif query.data == SEARCH_PREV_PAGE:
            page = context.get_context().get("page", 0)
            context.update_context(page=max(0, page - 1))
        elif query.data == SEARCH_NEXT_PAGE:
            page = context.get_context().get("page", 0)
            context.update_context(page=page + 1)
        elif query.data.startswith(SEARCH_DOWNLOAD):
            index = int(query.data[len(SEARCH_DOWNLOAD) :])
            return await self._start_download(query, context, index)

    async def handle_message(self, message: Message, context: Context) -> ScreenHandlerResult:
        text = message.text

        try:
            results = await self.searcher.search(text, limit=20)
            if not results:
                context.update_context(results=[], query=text, no_results=True, page=0, error=None)
                return
            context.update_context(
                results=results, query=text, no_results=False, page=0, error=None
            )
        except Exception as e:
            logger.error(f"Error searching: {e}")
            context.update_context(results=[], query=text, no_results=False, page=0, error=str(e))

    async def _start_download(
        self,
        query: CallbackQuery,
        context: Context,
        index: int,
    ) -> ScreenHandlerResult:
        try:
            results = context.get_context().get("results", [])

            if 0 <= index < len(results):
                result = results[index]

                await query.answer(f"Starting download: {result.title[:30]}...", show_alert=False)

                # Add download
                await self.downloader.add_download(result.magnet_link, result.title)

                # Navigate to downloads screen
                return Navigation(next_screen="downloads")

        except Exception as e:
            logger.error(f"Error starting download: {e}")
            await query.answer("Failed to start download", show_alert=True)
