"""Screen manager for handling navigation and active messages."""

import logging

from telegram import CallbackQuery, Message
from telegram.ext import ExtBot

from app.bot.screen_registry import ScreenRegistry
from app.bot.session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages screens registry and sessions."""

    def __init__(self, bot: ExtBot[None], screen_registry: ScreenRegistry):
        """Initialize the screen manager."""
        self.sessions: dict[int, Session] = {}
        self.bot = bot
        self.screen_registry = screen_registry

    async def get_session(self, chat_id: int) -> Session:
        if chat_id not in self.sessions:
            new_session = Session(
                chat_id, self.screen_registry.main_menu, self.bot, self.screen_registry
            )
            self.sessions[chat_id] = new_session
            await new_session.render_screen()
        return self.sessions[chat_id]

    async def stop_session(self, chat_id: int) -> None:
        if chat_id in self.sessions:
            session = self.sessions[chat_id]
            await session.cleanup()
            await session.screen.on_exit(session.context)
            del self.sessions[chat_id]

    async def restart_session(self, chat_id: int) -> None:
        await self.stop_session(chat_id)
        new_session = Session(
            chat_id, self.screen_registry.main_menu, self.bot, self.screen_registry
        )
        self.sessions[chat_id] = new_session
        await new_session.render_screen()

    async def handle_callback(self, chat_id: int, query: CallbackQuery) -> None:
        await query.answer()
        session = await self.get_session(chat_id)
        await session.handle_callback(query)

    async def handle_message(self, chat_id: int, message: Message) -> None:
        session = await self.get_session(chat_id)
        await session.handle_message(message)
