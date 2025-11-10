"""Simplified bot handlers using screen system."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.auth import AuthManager
from app.bot.screen_manager import ScreenManager

logger = logging.getLogger(__name__)


class BotHandlers:
    """Simplified handlers that delegate to the screen system."""

    def __init__(
        self,
        screen_manager: ScreenManager,
        auth_manager: Optional[AuthManager] = None,
    ):
        """Initialize bot handlers.

        Args:
            screen_manager: Screen manager instance
            auth_manager: Authorization manager (optional)
        """
        self.screen_manager = screen_manager
        self.auth_manager = auth_manager

    def _is_authorized(self, update: Update) -> bool:
        """Check if user is authorized.

        Args:
            update: Telegram update

        Returns:
            True if authorized (or no auth configured), False otherwise
        """
        if not self.auth_manager:
            return True
        return self.auth_manager.is_authorized(update)

    async def handle_start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start command.

        Don't delete the message to avoid Telegram client resending it.

        Args:
            update: Telegram update
            context: Bot context
        """
        # Check authorization
        if not self._is_authorized(update):
            # Silently ignore unauthorized users
            return

        chat_id = update.effective_chat.id

        # Don't delete /start message - just show the active screen
        await self.screen_manager.create_or_update_active_message(
            update, context, chat_id
        )

    async def handle_text_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle any text message.

        Creates or shows the active screen when user types anything.

        Args:
            update: Telegram update
            context: Bot context
        """
        # Check authorization
        if not self._is_authorized(update):
            # Silently ignore unauthorized users
            return

        chat_id = update.effective_chat.id
        text = update.message.text

        # Get active screen
        active_screen = self.screen_manager.get_active_screen(chat_id)
        
        # Check if we're on search screen and waiting for input
        if active_screen and active_screen.get_name() == "search":
            # Delegate to search screen's text input handler
            if hasattr(active_screen, "handle_text_input"):
                await active_screen.handle_text_input(update, context, text)
                return

        # Delete user's message for cleaner single-message UX
        try:
            await update.message.delete()
        except Exception as e:
            logger.debug(f"Could not delete user message: {e}")

        # Create/show the active screen (main menu)
        await self.screen_manager.create_or_update_active_message(
            update, context, chat_id
        )

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle callback queries from inline keyboards.

        Args:
            update: Telegram update
            context: Bot context
        """
        # Check authorization
        if not self._is_authorized(update):
            # Silently ignore unauthorized users
            await update.callback_query.answer()
            return

        # Delegate to screen manager
        await self.screen_manager.handle_callback(update, context)
