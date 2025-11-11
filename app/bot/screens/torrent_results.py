"""Torrent results screen for displaying and selecting torrents."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import TORRENT_BACK, TORRENT_NEXT, TORRENT_PREV, TORRENT_SELECT
from app.bot.screens.base import Context, Navigation, RenderOptions, Screen, ScreenHandlerResult
from app.library.models import IMDbMovie

logger = logging.getLogger(__name__)


class TorrentResultsScreen(Screen):
    """Screen for browsing and selecting torrent results."""

    def __init__(self, searcher, downloader):
        """Initialize torrent results screen.

        Args:
            searcher: Torrent searcher
            downloader: Torrent downloader
        """
        self.searcher = searcher
        self.downloader = downloader

    def get_name(self) -> str:
        """Get screen name."""
        return "torrent_results"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.

        Expects kwargs:
            movie: IMDbMovie object
            provider: Provider name (e.g., "yts")
        """
        movie: IMDbMovie = kwargs.get("movie")
        provider = kwargs.get("provider", "yts")

        # Search for torrents using the movie title
        search_query = movie.primaryTitle
        if movie.startYear:
            search_query = f"{movie.primaryTitle} {movie.startYear}"

        logger.info(f"Searching torrents for: {search_query} (provider: {provider})")

        try:
            results = await self.searcher.search(search_query, limit=20)
            context.update_context(
                movie=movie,
                provider=provider,
                search_query=search_query,
                results=results,
                page=0,
                error=None,
            )
        except Exception as e:
            logger.error(f"Error searching torrents: {e}")
            context.update_context(
                movie=movie,
                provider=provider,
                search_query=search_query,
                results=[],
                page=0,
                error=str(e),
            )

    async def render(
        self, context: Context
    ) -> tuple[str, InlineKeyboardMarkup, RenderOptions]:
        """Render the torrent results screen."""
        state = context.get_context()
        movie: IMDbMovie = state.get("movie")
        results = state.get("results", [])
        page = state.get("page", 0)
        search_query = state.get("search_query", "")
        error = state.get("error")

        # Build header
        text = f"🎬 *{movie.primaryTitle}*"
        if movie.startYear:
            text += f" ({movie.startYear})"
        text += "\n\n"

        # If there was an error
        if error:
            text += f"❌ *Error:* {error}\n\n"
            text += "Please try again or go back."
            keyboard = [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # If no results found
        if not results:
            text += f"No torrents found for: _{search_query}_\n\n"
            text += "Try going back and selecting a different provider."
            keyboard = [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Show results
        items_per_page = 5
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]

        total_pages = (len(results) - 1) // items_per_page + 1
        text += "📥 *Torrent Results*\n\n"
        text += f"Found {len(results)} results (page {page + 1}/{total_pages})\n\n"

        # Show results with details in text
        for i, result in enumerate(page_results):
            text += f"{i + 1}. *{result.title[:50]}{'...' if len(result.title) > 50 else ''}*\n"
            text += f"   📁 {result.quality} • {result.size} • 🌱 {result.seeders} seeders\n\n"

        keyboard = []

        # Add result buttons
        for i, result in enumerate(page_results):
            actual_idx = start_idx + i
            button_text = f"{i + 1}. {result.title[:35]}"
            if len(button_text) > 45:
                button_text = button_text[:42] + "..."

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{TORRENT_SELECT}{actual_idx}")]
            )

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=TORRENT_PREV))
        if end_idx < len(results):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=TORRENT_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        if query.data == TORRENT_BACK:
            return Navigation(next_screen="torrent_providers")

        elif query.data == TORRENT_PREV:
            page = context.get_context().get("page", 0)
            context.update_context(page=max(0, page - 1))

        elif query.data == TORRENT_NEXT:
            page = context.get_context().get("page", 0)
            context.update_context(page=page + 1)

        elif query.data.startswith(TORRENT_SELECT):
            index = int(query.data[len(TORRENT_SELECT) :])
            return await self._start_download(query, context, index)

    async def _start_download(
        self,
        query: CallbackQuery,
        context: Context,
        index: int,
    ) -> ScreenHandlerResult:
        """Start downloading the selected torrent."""
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

