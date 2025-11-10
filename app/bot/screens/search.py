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
        waiting_for_input = state.get("waiting_for_input", False)

        # If waiting for search input
        if waiting_for_input and not results:
            text = (
                "🔍 *Search for Content*\n\n"
                "Type the name of a movie or TV series you want to find.\n\n"
                "I'll search across multiple torrent sources and show you the best results."
            )
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="search:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

        # If no results yet
        if not results:
            text = "🔍 *Search for Content*\n\nType anything to start searching..."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="search:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

        # Show results
        items_per_page = 5
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_results = results[start_idx:end_idx]

        text = f"🔍 *Search Results for:* _{query}_\n\n"
        text += f"Found {len(results)} results (page {page + 1}/{(len(results) - 1) // items_per_page + 1})\n\n"

        keyboard = []

        # Add result buttons
        for i, result in enumerate(page_results):
            actual_idx = start_idx + i
            button_text = f"{result.title[:40]}{'...' if len(result.title) > 40 else ''}"
            details = f"{result.quality} • {result.size} • S:{result.seeders}"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📦 {button_text}",
                    callback_data=f"search:select:{actual_idx}"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    f"   {details}",
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
            InlineKeyboardButton("🔍 New Search", callback_data="search:new:")
        ])
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
        # Set state to wait for input
        self.set_state(chat_id, {"waiting_for_input": True})

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

        elif action == "new":
            self.set_state(chat_id, {"waiting_for_input": True})
            await self.refresh(chat_id)

        elif action == "prev_page":
            page = state.get("page", 0)
            state["page"] = max(0, page - 1)
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "next_page":
            page = state.get("page", 0)
            results = state.get("results", [])
            items_per_page = 5
            max_page = (len(results) - 1) // items_per_page
            state["page"] = min(max_page, page + 1)
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "download":
            await self._start_download(update, context, chat_id, params)

    async def handle_text_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
    ) -> None:
        """Handle text input for search query.

        Args:
            update: Telegram update
            context: Bot context
            text: User's text input
        """
        chat_id = update.effective_chat.id
        state = self.get_state(chat_id)

        # Only process if waiting for input
        if not state.get("waiting_for_input"):
            return

        # Perform search
        try:
            # Show searching message
            await update.message.reply_text(f"🔍 Searching for: _{text}_...")

            results = await self.searcher.search(text, limit=20)

            if not results:
                state.update({
                    "waiting_for_input": True,
                    "results": [],
                    "query": text,
                })
                self.set_state(chat_id, state)
                await update.message.reply_text(
                    f"No results found for '{text}'. Try a different search term."
                )
                return

            # Store results
            state.update({
                "waiting_for_input": False,
                "results": results,
                "query": text,
                "page": 0,
            })
            self.set_state(chat_id, state)

            # Show results
            await self.screen_manager.create_or_update_active_message(
                update, context, chat_id
            )

        except Exception as e:
            logger.error(f"Error searching: {e}")
            await update.message.reply_text(
                "An error occurred while searching. Please try again."
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

