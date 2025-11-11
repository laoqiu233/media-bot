"""Screen-based UI system for the bot."""

from app.bot.screens.base import Screen
from app.bot.screens.downloads import DownloadsScreen
from app.bot.screens.library import LibraryScreen
from app.bot.screens.main_menu import MainMenuScreen
from app.bot.screens.player import PlayerScreen
from app.bot.screens.search import SearchScreen
from app.bot.screens.status import StatusScreen
from app.bot.screens.tv import TVScreen

__all__ = [
    "Screen",
    "DownloadsScreen",
    "LibraryScreen",
    "MainMenuScreen",
    "PlayerScreen",
    "SearchScreen",
    "StatusScreen",
    "TVScreen",
]
