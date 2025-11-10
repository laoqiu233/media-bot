"""Player control screen."""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class PlayerScreen(Screen):
    """Screen for controlling media playback."""

    def __init__(self, screen_manager, player):
        """Initialize player screen.

        Args:
            screen_manager: Screen manager instance
            player: MPV player controller
        """
        super().__init__(screen_manager)
        self.player = player
        self._update_tasks: Dict[int, asyncio.Task] = {}

    def get_name(self) -> str:
        """Get screen name."""
        return "player"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the player screen.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            status = await self.player.get_status()

            text = "🎮 *Player Controls*\n\n"

            if status["is_playing"]:
                # Show current playback info
                filename = Path(status["current_file"]).name if status.get("current_file") else "Unknown"
                text += f"▶️ *Playing:*\n{filename}\n\n"

                if status.get("position") is not None and status.get("duration") is not None:
                    progress_pct = (status["position"] / status["duration"]) * 100 if status["duration"] > 0 else 0
                    progress_bar = self._create_progress_bar(progress_pct)
                    
                    pos_min = int(status["position"]) // 60
                    pos_sec = int(status["position"]) % 60
                    dur_min = int(status["duration"]) // 60
                    dur_sec = int(status["duration"]) % 60
                    
                    text += f"{progress_bar} {progress_pct:.1f}%\n"
                    text += f"Time: {pos_min}:{pos_sec:02d} / {dur_min}:{dur_sec:02d}\n"

                volume = status.get("volume", 0)
                text += f"Volume: {volume}%\n"

                # Playback control buttons
                keyboard = [
                    [
                        InlineKeyboardButton("⏸ Pause", callback_data="player:pause:"),
                        InlineKeyboardButton("⏹ Stop", callback_data="player:stop:"),
                    ],
                    [
                        InlineKeyboardButton("⏪ -30s", callback_data="player:seek:-30"),
                        InlineKeyboardButton("⏩ +30s", callback_data="player:seek:30"),
                    ],
                    [
                        InlineKeyboardButton("⏪⏪ -5m", callback_data="player:seek:-300"),
                        InlineKeyboardButton("⏩⏩ +5m", callback_data="player:seek:300"),
                    ],
                    [
                        InlineKeyboardButton("🔉 Vol -", callback_data="player:vol_down:"),
                        InlineKeyboardButton("🔊 Vol +", callback_data="player:vol_up:"),
                    ],
                    [
                        InlineKeyboardButton("🔄 Refresh", callback_data="player:refresh:"),
                    ],
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data="player:back:"),
                    ],
                ]

            else:
                text += "⏹ *No media playing*\n\n"
                text += "Use Library to select content to play."

                keyboard = [
                    [InlineKeyboardButton("📚 Go to Library", callback_data="player:library:")],
                    [InlineKeyboardButton("« Back to Menu", callback_data="player:back:")],
                ]

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering player: {e}")
            text = "🎮 *Player Controls*\n\nError loading player status."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="player:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

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

    async def on_enter(self, chat_id: int, **kwargs) -> None:
        """Called when entering player screen.

        Start auto-refresh if media is playing.

        Args:
            chat_id: Chat ID
            **kwargs: Additional context
        """
        # Check if media is playing
        status = await self.player.get_status()
        if status.get("is_playing"):
            # Start auto-refresh
            if chat_id not in self._update_tasks or self._update_tasks[chat_id].done():
                self._update_tasks[chat_id] = asyncio.create_task(
                    self._auto_refresh_loop(chat_id)
                )
                logger.info(f"Started auto-refresh for player screen in chat {chat_id}")

    async def on_exit(self, chat_id: int) -> None:
        """Called when leaving player screen.

        Stop auto-refresh task.

        Args:
            chat_id: Chat ID
        """
        # Cancel auto-refresh task
        if chat_id in self._update_tasks and not self._update_tasks[chat_id].done():
            self._update_tasks[chat_id].cancel()
            logger.info(f"Stopped auto-refresh for player screen in chat {chat_id}")

    async def _auto_refresh_loop(self, chat_id: int) -> None:
        """Auto-refresh loop for real-time updates.

        Args:
            chat_id: Chat ID
        """
        try:
            while True:
                await asyncio.sleep(5)  # Update every 5 seconds
                
                # Check if still on player screen
                active_screen = self.screen_manager.get_active_screen(chat_id)
                if not active_screen or active_screen.get_name() != "player":
                    break
                
                # Check if still playing
                status = await self.player.get_status()
                if not status.get("is_playing"):
                    # Stopped playing, do one final refresh and exit
                    await self.refresh(chat_id)
                    break
                
                # Refresh the screen
                await self.refresh(chat_id)

        except asyncio.CancelledError:
            logger.debug(f"Auto-refresh cancelled for chat {chat_id}")
        except Exception as e:
            logger.error(f"Error in auto-refresh loop: {e}")

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle player screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters
        """
        chat_id = update.callback_query.message.chat_id

        if action == "back":
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

        elif action == "library":
            await self.navigate_to(chat_id, "library")

        elif action == "refresh":
            await update.callback_query.answer("Refreshing...")
            # screen_manager auto-refreshes after callback

        elif action == "pause":
            success = await self.player.pause()
            await update.callback_query.answer("⏸ Paused" if success else "Failed")
            # screen_manager auto-refreshes after callback

        elif action == "resume":
            success = await self.player.resume()
            await update.callback_query.answer("▶️ Resumed" if success else "Failed")
            # screen_manager auto-refreshes after callback

        elif action == "stop":
            success = await self.player.stop()
            await update.callback_query.answer("⏹ Stopped" if success else "Failed")
            # screen_manager auto-refreshes after callback

        elif action == "vol_up":
            success = await self.player.volume_up()
            await update.callback_query.answer("🔊 Volume up" if success else "Failed")
            # screen_manager auto-refreshes after callback

        elif action == "vol_down":
            success = await self.player.volume_down()
            await update.callback_query.answer("🔉 Volume down" if success else "Failed")
            # screen_manager auto-refreshes after callback

        elif action == "seek":
            try:
                seconds = int(params)
                success = await self.player.seek(seconds, relative=True)
                direction = "⏩" if seconds > 0 else "⏪"
                abs_seconds = abs(seconds)
                await update.callback_query.answer(
                    f"{direction} Seeked {abs_seconds}s" if success else "Failed"
                )
                # screen_manager auto-refreshes after callback
            except ValueError:
                await update.callback_query.answer("Invalid seek value", show_alert=True)

