"""System status screen."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import STATUS_BACK
from app.bot.screens.base import (
    Context,
    Navigation,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.player.mpv_controller import MPVController
from app.torrent.downloader import TorrentDownloader
from app.tv.hdmi_cec import CECController

logger = logging.getLogger(__name__)


class StatusScreen(Screen):
    def __init__(
        self,
        mpv_controller: MPVController,
        cec_controller: CECController,
        torrent_downloader: TorrentDownloader,
    ):
        self.mpv_controller = mpv_controller
        self.cec_controller = cec_controller
        self.torrent_downloader = torrent_downloader

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

            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data=STATUS_BACK)],
            ]

            return (status_text, InlineKeyboardMarkup(keyboard))

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            error_text = "❌ *System Status*\n\nError retrieving status information."
            keyboard = [
                [InlineKeyboardButton("⬅️ Back", callback_data=STATUS_BACK)],
            ]
            return (error_text, InlineKeyboardMarkup(keyboard))

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == STATUS_BACK:
            return Navigation(next_screen="main_menu")
