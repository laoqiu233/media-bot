"""Search screen for finding and downloading torrents."""

import logging
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class SearchScreen(Screen):
    """Screen for searching torrents."""

    def __init__(self, screen_manager, searcher, downloader):
        """Initialize search screen.

        Args:
            screen_manager: Screen manager instance
            searcher: Torrent searcher
            downloader: Torrent downloader
        """
        super().__init__(screen_manager)
        self.searcher = searcher
        self.downloader = downloader

    def get_name(self) -> str:
        """Get screen name."""
        return "search"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the search screen.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        state = state or {}
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
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="search:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

        # If no results found after search
        if no_results and query:
            text = (
                "🔍 *Search for Content*\n\n"
                f"No results found for: _{query}_\n\n"
                "Try typing a different search term."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="search:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

        # If no results yet (first time on search screen)
        if not results:
            text = (
                "🔍 *Search for Content*\n\n"
                "Type the name of a movie or TV series to find.\n\n"
                "I'll search across multiple torrent sources."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="search:back:")]]
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
            
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"search:download:{actual_idx}"
                )
            ])

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("« Previous", callback_data="search:prev_page:")
            )
        if end_idx < len(results):
            nav_buttons.append(
                InlineKeyboardButton("Next »", callback_data="search:next_page:")
            )
        
        if nav_buttons:
            keyboard.append(nav_buttons)

        # Bottom buttons
        keyboard.append([
            InlineKeyboardButton("« Back to Menu", callback_data="search:back:")
        ])

        return text, InlineKeyboardMarkup(keyboard)

    async def on_enter(self, chat_id: int, **kwargs) -> None:
        """Called when entering the search screen.

        Args:
            chat_id: Chat ID
            **kwargs: Additional context
        """
        # Clear any previous state - always ready for new search
        self.set_state(chat_id, {
            "results": [],
            "query": "",
            "page": 0,
            "no_results": False,
            "error": None,
        })

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle search screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters
        """
        chat_id = update.callback_query.message.chat_id
        state = self.get_state(chat_id)

        if action == "back":
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

        elif action == "prev_page":
            page = state.get("page", 0)
            state["page"] = max(0, page - 1)
            self.set_state(chat_id, state)
            # screen_manager auto-refreshes after callback

        elif action == "next_page":
            page = state.get("page", 0)
            results = state.get("results", [])
            items_per_page = 5
            max_page = (len(results) - 1) // items_per_page
            state["page"] = min(max_page, page + 1)
            self.set_state(chat_id, state)
            # screen_manager auto-refreshes after callback

        elif action == "download":
            await self._start_download(update, context, chat_id, params)

    async def handle_text_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> None:
        """Handle text input for search query.

        Always performs a new search when user types on search screen.

        Args:
            update: Telegram update
            context: Bot context
            text: User's text input
        """
        chat_id = update.effective_chat.id

        # Delete user's message for cleaner UX
        try:
            await update.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")

        # Perform search
        try:
            results = await self.searcher.search(text, limit=20)

            if not results:
                self.set_state(chat_id, {
                    "results": [],
                    "query": text,
                    "no_results": True,
                    "page": 0,
                    "error": None,
                })
                # Update active message to show "no results"
                await self.screen_manager.create_or_update_active_message(
                    update, context, chat_id
                )
                return

            # Store results
            self.set_state(chat_id, {
                "results": results,
                "query": text,
                "page": 0,
                "no_results": False,
                "error": None,
            })

            # Show results - update active message
            await self.screen_manager.create_or_update_active_message(
                update, context, chat_id
            )

        except Exception as e:
            logger.error(f"Error searching: {e}")
            self.set_state(chat_id, {
                "results": [],
                "query": text,
                "error": str(e),
                "no_results": False,
                "page": 0,
            })
            # Update active message to show error
            await self.screen_manager.create_or_update_active_message(
                update, context, chat_id
            )

    async def _start_download(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        params: str,
    ) -> None:
        """Start downloading a torrent.

        Args:
            update: Telegram update
            context: Bot context
            chat_id: Chat ID
            params: Result index as string
        """
        try:
            index = int(params)
            state = self.get_state(chat_id)
            results = state.get("results", [])

            if 0 <= index < len(results):
                result = results[index]
                
                await update.callback_query.answer(
                    f"Starting download: {result.title[:30]}...",
                    show_alert=False
                )

                # Add download
                task_id = await self.downloader.add_download(
                    result.magnet_link, result.title
                )

                # Navigate to downloads screen
                await self.navigate_to(chat_id, "downloads")

        except Exception as e:
            logger.error(f"Error starting download: {e}")
            await update.callback_query.answer(
                "Failed to start download",
                show_alert=True
            )

