"""Screen-based UI system for the bot."""

from app.bot.screens.base import Screen
from app.bot.screens.downloads import DownloadsScreen
from app.bot.screens.library import LibraryScreen
from app.bot.screens.main_menu import MainMenuScreen
from app.bot.screens.movie_selection import MovieSelectionScreen
from app.bot.screens.player import PlayerScreen
from app.bot.screens.search import SearchScreen
from app.bot.screens.setup_confirmation import SetupConfirmationScreen
from app.bot.screens.status import StatusScreen
from app.bot.screens.torrent_providers import TorrentProvidersScreen
from app.bot.screens.torrent_results import TorrentResultsScreen
from app.bot.screens.tv import TVScreen

__all__ = [
    "Screen",
    "DownloadsScreen",
    "LibraryScreen",
    "MainMenuScreen",
    "MovieSelectionScreen",
    "PlayerScreen",
    "SearchScreen",
    "SetupConfirmationScreen",
    "StatusScreen",
    "TorrentProvidersScreen",
    "TorrentResultsScreen",
    "TVScreen",
]
