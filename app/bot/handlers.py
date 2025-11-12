"""Simplified bot handlers using screen system."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.auth import AuthManager
from app.bot.session_manager import SessionManager

logger = logging.getLogger(__name__)


class BotHandlers:
    def __init__(
        self,
        session_manager: SessionManager,
        auth_manager: AuthManager | None,
    ):
        self.session_manager = session_manager
        self.auth_manager = auth_manager

    def _is_authorized(self, update: Update) -> bool:
        if self.auth_manager is None:
            return True
        return self.auth_manager.is_authorized(update)

    async def handle_start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not self._is_authorized(update):
            return

        if update.effective_chat is None:
            return

        chat_id = update.effective_chat.id
        await self.session_manager.restart_session(chat_id)

    async def handle_text_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not self._is_authorized(update):
            return

        if update.message is None or update.effective_chat is None:
            return

        chat_id = update.effective_chat.id

        await self.session_manager.handle_message(chat_id, update.message)

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not self._is_authorized(update):
            if update.callback_query is not None:
                await update.callback_query.answer()
            return

        if (
            update.callback_query is None
            or update.callback_query.message is None
            or update.effective_chat is None
        ):
            return

        chat_id = update.effective_chat.id

        await self.session_manager.handle_callback(chat_id, update.callback_query)
