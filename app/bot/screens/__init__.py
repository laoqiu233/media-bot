"""Screen-based UI system for the bot."""

from app.bot.screens.audio_output_selection import AudioOutputSelectionScreen
from app.bot.screens.audio_track_selection import AudioTrackSelectionScreen
from app.bot.screens.base import Screen
from app.bot.screens.downloads import DownloadsScreen
from app.bot.screens.hdmi_port_selection import HDMIPortSelectionScreen
from app.bot.screens.library import LibraryScreen
from app.bot.screens.main_menu import MainMenuScreen
from app.bot.screens.movie_selection import MovieSelectionScreen
from app.bot.screens.player import PlayerScreen
from app.bot.screens.resolution_selection import ResolutionSelectionScreen
from app.bot.screens.rutracker_auth import RuTrackerAuthScreen
from app.bot.screens.search import SearchScreen
from app.bot.screens.setup_confirmation import SetupConfirmationScreen
from app.bot.screens.status import StatusScreen
from app.bot.screens.system_control import SystemControlScreen
from app.bot.screens.torrent_providers import TorrentProvidersScreen
from app.bot.screens.torrent import TorrentScreen
from app.bot.screens.tv import TVScreen

__all__ = [
    "AudioOutputSelectionScreen",
    "AudioTrackSelectionScreen",
    "Screen",
    "DownloadsScreen",
    "HDMIPortSelectionScreen",
    "LibraryScreen",
    "MainMenuScreen",
    "MovieSelectionScreen",
    "PlayerScreen",
    "ResolutionSelectionScreen",
    "RuTrackerAuthScreen",
    "SearchScreen",
    "SetupConfirmationScreen",
    "StatusScreen",
    "SystemControlScreen",
    "TorrentProvidersScreen",
    "TorrentScreen",
    "TVScreen",
]
