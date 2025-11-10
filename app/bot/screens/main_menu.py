"""Main menu screen."""

import logging
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class MainMenuScreen(Screen):
    """Main menu screen with primary navigation options."""

    def get_name(self) -> str:
        """Get screen name."""
        return "main_menu"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the main menu.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        text = (
            "🎬 *Media Bot*\n\n"
            "Welcome to your personal media center!\n\n"
            "Select an option below:"
        )

        keyboard = [
            [InlineKeyboardButton("🔍 Search Content", callback_data="main_menu:search:")],
            [InlineKeyboardButton("📚 My Library", callback_data="main_menu:library:")],
            [
                InlineKeyboardButton("📥 Downloads", callback_data="main_menu:downloads:"),
                InlineKeyboardButton("🎮 Player", callback_data="main_menu:player:"),
            ],
            [
                InlineKeyboardButton("📺 TV Control", callback_data="main_menu:tv:"),
                InlineKeyboardButton("ℹ️ System Status", callback_data="main_menu:status:"),
            ],
        ]

        return text, InlineKeyboardMarkup(keyboard)

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle main menu callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters
        """
        chat_id = update.callback_query.message.chat_id

        if action == "search":
            await self.navigate_to(chat_id, "search")

        elif action == "library":
            await self.navigate_to(chat_id, "library")

        elif action == "downloads":
            await self.navigate_to(chat_id, "downloads")

        elif action == "player":
            await self.navigate_to(chat_id, "player")

        elif action == "tv":
            await self.navigate_to(chat_id, "tv")

        elif action == "status":
            await self._show_status(update, context, chat_id)

    async def _show_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int
    ) -> None:
        """Show system status.

        Args:
            update: Telegram update
            context: Bot context
            chat_id: Chat ID
        """
        # Get system components from screen manager
        handlers = getattr(self.screen_manager, "handlers", None)
        if not handlers:
            await update.callback_query.answer("Status not available", show_alert=True)
            return

        try:
            player_status = await handlers.player.get_status()
            cec_status = await handlers.cec.get_status()
            tasks = await handlers.downloader.get_all_tasks()

            status_text = "🖥 *System Status*\n\n"

            # Player status
            status_text += "🎮 *Player:*\n"
            if player_status["is_playing"]:
                from pathlib import Path
                filename = Path(player_status["current_file"]).name
                status_text += f"▶️ Playing: {filename}\n"
            else:
                status_text += "⏹ Idle\n"

            # CEC status
            status_text += "\n📺 *TV (CEC):*\n"
            if cec_status["available"]:
                power = cec_status.get("power_status", "unknown")
                status_text += f"Power: {power}\n"
                if cec_status.get("tv_name"):
                    status_text += f"Device: {cec_status['tv_name']}\n"
            else:
                status_text += "Not available\n"

            # Download status
            active_downloads = [t for t in tasks if t.status == "downloading"]
            status_text += f"\n📥 *Downloads:* {len(active_downloads)} active\n"

            await update.callback_query.answer(status_text, show_alert=True)

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            await update.callback_query.answer(
                "Error retrieving status", show_alert=True
            )

