"""System status screen."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import STATUS_BACK
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.manager import LibraryManager
from app.player.mpv_controller import MPVController
from app.torrent.downloader import TorrentDownloader
from app.tv.hdmi_cec import CECController
from app.library.models import MediaType

logger = logging.getLogger(__name__)


class StatusScreen(Screen):
    def __init__(
        self,
        mpv_controller: MPVController,
        cec_controller: CECController,
        torrent_downloader: TorrentDownloader,
        library_manager: LibraryManager,
    ):
        self.mpv_controller = mpv_controller
        self.cec_controller = cec_controller
        self.torrent_downloader = torrent_downloader
        self.library_manager = library_manager

    def get_name(self) -> str:
        return "status"

    async def render(self, context: Context) -> ScreenRenderResult:
        try:
            player_status = await self.mpv_controller.get_status()
            cec_status = await self.cec_controller.get_status()
            tasks = await self.torrent_downloader.get_all_tasks()

            status_text = "🖥 *System Status*\n\n"

            # Player status
            status_text += "🎮 *Player:*\n"
            if player_status["is_playing"]:
                filename = (
                    Path(player_status["current_file"]).name
                    if player_status.get("current_file")
                    else "Unknown"
                )
                status_text += f"▶️ Playing: {filename}\n"
            else:
                status_text += "⏹ Idle\n"

            # Player volume
            volume = player_status.get("volume")
            if volume is not None:
                status_text += f"🔊 Volume: {volume}%\n"

            # CEC status
            status_text += "\n📺 *TV (CEC):*\n"
            if cec_status.get("available"):
                power = cec_status.get("power_status")
                if power:
                    power_emoji = "🟢" if power == "on" else "🔴"
                    status_text += f"Power: {power_emoji} {power.capitalize()}\n"
                else:
                    status_text += "Power: Unknown\n"
            else:
                error = cec_status.get("error", "Not available")
                status_text += f"❌ {error}\n"

            # Download status
            # Count active downloads (downloading, checking, or queued but not completed)
            active_statuses = ["downloading", "checking", "queued"]
            active_downloads = [t for t in tasks if t.status in active_statuses]
            completed_downloads = [t for t in tasks if t.status == "completed"]
            paused_downloads = [t for t in tasks if t.status == "paused"]

            # Get library count
            media_entities = self.library_manager.get_all_media_entities()
            movies_count = len([m for m in media_entities if m.media_type == MediaType.MOVIE])
            series_count = len([m for m in media_entities if m.media_type == MediaType.SERIES])

            status_text += f"\n📥 *Downloads:*\n"
            status_text += f"Active: {len(active_downloads)}\n"
            if paused_downloads:
                status_text += f"Paused: {len(paused_downloads)}\n"
            if completed_downloads:
                status_text += f"Completed: {len(completed_downloads)}\n"
            status_text += f"Films in library: {movies_count}\n"
            status_text += f"Series in library: {series_count}\n"

            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data=STATUS_BACK)],
            ]

            return status_text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            error_text = "❌ *System Status*\n\nError retrieving status information."
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data=STATUS_BACK)],
            ]
            return error_text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == STATUS_BACK:
            return Navigation(next_screen="main_menu")
