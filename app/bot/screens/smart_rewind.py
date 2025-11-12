"""Smart rewind control screen."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    PLAYER_BACK,
    PLAYER_LIBRARY,
    PLAYER_PAUSE,
    PLAYER_RESUME,
    PLAYER_SEEK,
    PLAYER_SMART_REWIND,
    PLAYER_STOP,
    PLAYER_VOL_DOWN,
    PLAYER_VOL_UP,
    SMART_REWIND_BACK,
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

class SmartRewindScreen(Screen):
    def __init__(self, player):
        """Initialize player screen.

        Args:
            screen_manager: Screen manager instance
            player: MPV player controller
        """
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "smart_rewind"

    async def render(self, context: Context) -> ScreenRenderResult:
        try:
            status = await self.player.get_status()

            text = "⏪⏩ *Smart Rewind*\n\n"

            if status["current_file"]:
                # Show current playback info
                filename = (
                    Path(status["current_file"]).name if status.get("current_file") else "Unknown"
                )
                is_paused = status.get("is_paused", False)

                if is_paused:
                    text += f"⏸ *Paused:*\n{filename}\n\n"
                else:
                    text += f"▶️ *Playing:*\n{filename}\n\n"

                if status.get("position") is not None and status.get("duration") is not None:
                    progress_pct = (
                        (status["position"] / status["duration"]) * 100
                        if status["duration"] > 0
                        else 0
                    )
                    progress_bar = self._create_progress_bar(progress_pct)

                    pos_min = int(status["position"]) // 60
                    pos_sec = int(status["position"]) % 60
                    dur_min = int(status["duration"]) // 60
                    dur_sec = int(status["duration"]) % 60

                    text += f"{progress_bar} {progress_pct:.1f}%\n"
                    text += f"Time: {pos_min}:{pos_sec:02d} / {dur_min}:{dur_sec:02d}\n"

                volume = status.get("volume", 0)
                text += f"Volume: {volume}%\n"
                text += "Enter amount by which to rewind:\n"
                text += "format is (+/-{num}s/m)"

                # Playback control buttons - show pause or resume based on state

                keyboard = [
                    [InlineKeyboardButton("« Back to Player Controls", callback_data=SMART_REWIND_BACK)],
                ]

            else:
                text += "⏹ *No media playing*\n\n"
                text += "Use Library to select content to play."

                keyboard = [
                    [InlineKeyboardButton("« Back to Player Controls", callback_data=SMART_REWIND_BACK)],
                ]

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering smart rewind: {e}")
            text = "⏪⏩ *Smart Rewind*\n\nError loading player status."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=SMART_REWIND_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()


    def _create_progress_bar(self, progress: float, length: int = 15) -> str:
        filled = int((progress / 100) * length)
        empty = length - filled
        return f"[{'█' * filled}{'░' * empty}]"

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == SMART_REWIND_BACK:
            return Navigation(next_screen="player")

    async def handle_message(self, message: Message, context: Context) -> ScreenHandlerResult:
        text = message.text.strip()
        neg = text.startswith('-')
        if text.startswith('-') or text.startswith('+'):
            text = text[1:]
        mul = 1
        if text.endswith('m'):
            mul = 60
            text = text[:-1]
        elif text.endswith('s'):
            text = text[:-1]
        amount = int(text)
        amount = mul * amount
        if neg:
            amount = -amount
        await self.player.seek(amount, relative=True)

        
        
