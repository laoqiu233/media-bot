"""Player control screen."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    PLAYER_BACK,
    PLAYER_LIBRARY,
    PLAYER_PAUSE,
    PLAYER_RESUME,
    PLAYER_SEEK,
    PLAYER_STOP,
    PLAYER_TRACKS,
    PLAYER_VOL_DOWN,
    PLAYER_VOL_UP,
    TV_VOL_DOWN,
    TV_VOL_UP,
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


class PlayerScreen(Screen):
    """Screen for controlling media playback."""

    def __init__(self, player, cec_controller=None):
        """Initialize player screen.

        Args:
            player: MPV player controller
            cec_controller: CEC controller for TV volume control (optional)
        """
        self.player = player
        self.cec = cec_controller

    def get_name(self) -> str:
        """Get screen name."""
        return "player"

    async def render(self, context: Context) -> ScreenRenderResult:
        try:
            status = await self.player.get_status()

            text = "🎮 *Player Controls*\n\n"

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

                # Playback control buttons - show pause or resume based on state
                pause_resume_button = (
                    InlineKeyboardButton("▶️ Resume", callback_data=PLAYER_RESUME)
                    if is_paused
                    else InlineKeyboardButton("⏸ Pause", callback_data=PLAYER_PAUSE)
                )

                keyboard = [
                    [
                        pause_resume_button,
                        InlineKeyboardButton("⏹ Stop", callback_data=PLAYER_STOP),
                    ],
                    [
                        InlineKeyboardButton("⏪ -30s", callback_data=f"{PLAYER_SEEK}-30"),
                        InlineKeyboardButton("⏩ +30s", callback_data=f"{PLAYER_SEEK}30"),
                    ],
                    [
                        InlineKeyboardButton("⏪⏪ -5m", callback_data=f"{PLAYER_SEEK}-300"),
                        InlineKeyboardButton("⏩⏩ +5m", callback_data=f"{PLAYER_SEEK}300"),
                    ],
                    [
                        InlineKeyboardButton("🔉 Player Volume -5", callback_data=PLAYER_VOL_DOWN),
                        InlineKeyboardButton("🔊 Player Volume +5", callback_data=PLAYER_VOL_UP),
                    ],
                    [
                        InlineKeyboardButton("🔉 TV Volume -5", callback_data=TV_VOL_DOWN),
                        InlineKeyboardButton("🔊 TV Volume +5", callback_data=TV_VOL_UP),
                    ],
                    [
                        InlineKeyboardButton("🎵 Audio Tracks", callback_data=PLAYER_TRACKS),
                    ],
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data=PLAYER_BACK),
                    ],
                ]

            else:
                text += "⏹ *No media playing*\n\n"
                text += "Use Library to select content to play."

                keyboard = [
                    [InlineKeyboardButton("📚 Go to Library", callback_data=PLAYER_LIBRARY)],
                    [InlineKeyboardButton("« Back to Menu", callback_data=PLAYER_BACK)],
                ]

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering player: {e}")
            text = "🎮 *Player Controls*\n\nError loading player status."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=PLAYER_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    def _create_progress_bar(self, progress: float, length: int = 15) -> str:
        """Create a visual progress bar.

        Args:
            progress: Progress percentage (0-100)
            length: Length of the progress bar

        Returns:
            Progress bar string
        """
        filled = int((progress / 100) * length)
        empty = length - filled
        return f"[{'█' * filled}{'░' * empty}]"

    async def handle_message(self, message: Message, context: Context) -> ScreenHandlerResult:
        text = message.text.strip()
        neg = text.startswith("-")
        if text.startswith("-") or text.startswith("+"):
            text = text[1:]
        mul = 1
        if text.endswith("m"):
            mul = 60
            text = text[:-1]
        elif text.endswith("s"):
            text = text[:-1]
        amount = int(text)
        amount = mul * amount
        if neg:
            amount = -amount
        await self.player.seek(amount, relative=True)

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == PLAYER_BACK:
            return Navigation(next_screen="main_menu")

        elif query.data == PLAYER_LIBRARY:
            return Navigation(next_screen="library")

        elif query.data == PLAYER_PAUSE:
            success = await self.player.pause()
            await query.answer("⏸ Paused" if success else "Failed")

        elif query.data == PLAYER_RESUME:
            success = await self.player.resume()
            await query.answer("▶️ Resumed" if success else "Failed")

        elif query.data == PLAYER_STOP:
            success = await self.player.stop()
            await query.answer("⏹ Stopped" if success else "Failed")

        elif query.data == PLAYER_VOL_UP:
            success = await self.player.volume_up()
            await query.answer("🔊 Player volume up +5" if success else "Failed")

        elif query.data == PLAYER_VOL_DOWN:
            success = await self.player.volume_down()
            await query.answer("🔉 Player volume down -5" if success else "Failed")

        elif query.data == TV_VOL_UP:
            if not self.cec:
                await query.answer("TV control not available", show_alert=True)
                return None
            await self._tv_volume_up(query)

        elif query.data == TV_VOL_DOWN:
            if not self.cec:
                await query.answer("TV control not available", show_alert=True)
                return None
            await self._tv_volume_down(query)

        elif query.data == PLAYER_TRACKS:
            # Check if media is playing
            status = await self.player.get_status()
            if not status.get("current_file"):
                await query.answer("No media is currently playing", show_alert=True)
                return None
            # Navigate to audio track selection screen
            return Navigation(next_screen="audio_track_selection")

        elif query.data.startswith(PLAYER_SEEK):
            try:
                seconds_str = query.data[len(PLAYER_SEEK) :]
                seconds = int(seconds_str)
                success = await self.player.seek(seconds, relative=True)
                direction = "⏩" if seconds > 0 else "⏪"
                abs_seconds = abs(seconds)
                await query.answer(f"{direction} Seeked {abs_seconds}s" if success else "Failed")
            except ValueError:
                await query.answer("Invalid seek value", show_alert=True)

    async def _tv_volume_up(self, query: CallbackQuery) -> None:
        """Handle TV volume up.

        Args:
            query: Callback query
        """
        try:
            success = await self.cec.volume_up()
            await query.answer("🔊 TV volume up +5" if success else "Failed")
        except Exception as e:
            logger.error(f"Error increasing TV volume: {e}")
            await query.answer("Error", show_alert=True)

    async def _tv_volume_down(self, query: CallbackQuery) -> None:
        """Handle TV volume down.

        Args:
            query: Callback query
        """
        try:
            success = await self.cec.volume_down()
            await query.answer("🔉 TV volume down -5" if success else "Failed")
        except Exception as e:
            logger.error(f"Error decreasing TV volume: {e}")
            await query.answer("Error", show_alert=True)
