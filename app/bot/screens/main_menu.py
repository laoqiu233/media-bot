"""Main menu screen."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    MAIN_MENU_DOWNLOADS,
    MAIN_MENU_LIBRARY,
    MAIN_MENU_PLAYER,
    MAIN_MENU_SEARCH,
    MAIN_MENU_SETUP,
    MAIN_MENU_STATUS,
    MAIN_MENU_TV,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class MainMenuScreen(Screen):
    def get_name(self) -> str:
        return "main_menu"

    async def render(self, context: Context) -> ScreenRenderResult:
        text = (
            "🎬 *Media Bot*\n\n"
            "Welcome to your personal media center!\n\n"
            "Select an option below:"
        )

        keyboard = [
            [InlineKeyboardButton("🔍 Search Content", callback_data=MAIN_MENU_SEARCH)],
            [InlineKeyboardButton("📚 My Library", callback_data=MAIN_MENU_LIBRARY)],
            [
                InlineKeyboardButton("📥 Downloads", callback_data=MAIN_MENU_DOWNLOADS),
                InlineKeyboardButton("🎮 Player", callback_data=MAIN_MENU_PLAYER),
            ],
            [
                InlineKeyboardButton("📺 TV Control", callback_data=MAIN_MENU_TV),
                InlineKeyboardButton("ℹ️ System Status", callback_data=MAIN_MENU_STATUS),
            ],
            [InlineKeyboardButton("🛠 Wi‑Fi / Token Setup", callback_data=MAIN_MENU_SETUP)],
        ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == MAIN_MENU_SEARCH:
            return Navigation(next_screen="search")

        elif query.data == MAIN_MENU_LIBRARY:
            return Navigation(next_screen="library")

        elif query.data == MAIN_MENU_DOWNLOADS:
            return Navigation(next_screen="downloads")

        elif query.data == MAIN_MENU_PLAYER:
            return Navigation(next_screen="player")

        elif query.data == MAIN_MENU_TV:
            return Navigation(next_screen="tv")

        elif query.data == MAIN_MENU_STATUS:
            return Navigation(next_screen="status")

        elif query.data == MAIN_MENU_SETUP:
            return Navigation(next_screen="setup_confirmation")
