"""Downloads screen for monitoring active downloads."""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class DownloadsScreen(Screen):
    """Screen for viewing and managing downloads."""

    def __init__(self, screen_manager, downloader):
        """Initialize downloads screen.

        Args:
            screen_manager: Screen manager instance
            downloader: Torrent downloader
        """
        super().__init__(screen_manager)
        self.downloader = downloader
        self._update_tasks: Dict[int, asyncio.Task] = {}

    def get_name(self) -> str:
        """Get screen name."""
        return "downloads"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the downloads screen.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            tasks = await self.downloader.get_all_tasks()

            if not tasks:
                text = "📥 *Downloads*\n\nNo active downloads.\n\nUse Search to find and download content."
                keyboard = [
                    [InlineKeyboardButton("🔍 Search Content", callback_data="downloads:search:")],
                    [InlineKeyboardButton("« Back to Menu", callback_data="downloads:back:")],
                ]
                return text, InlineKeyboardMarkup(keyboard)

            # Build downloads status text
            text = "📥 *Active Downloads*\n\n"

            keyboard = []

            for i, task in enumerate(tasks, 1):
                # Progress bar
                progress_bar = self._create_progress_bar(task.progress)
                
                # Status line
                status_emoji = {
                    "downloading": "⬇️",
                    "completed": "✅",
                    "paused": "⏸",
                    "error": "❌",
                }.get(task.status, "📦")

                text += f"{i}. {status_emoji} *{task.torrent_name[:35]}*\n"
                text += f"   {progress_bar} {task.progress:.1f}%\n"
                
                if task.status == "downloading":
                    speed_mb = task.download_speed / 1024 / 1024
                    text += f"   Speed: {speed_mb:.2f} MB/s"
                    
                    if task.eta:
                        minutes = task.eta // 60
                        seconds = task.eta % 60
                        text += f" • ETA: {minutes}m {seconds}s"
                    text += "\n"
                elif task.status == "completed":
                    text += f"   Status: Completed ✅\n"
                else:
                    text += f"   Status: {task.status}\n"
                
                text += "\n"

                # Add control button
                if task.status == "downloading":
                    keyboard.append([
                        InlineKeyboardButton(
                            f"⏸ Pause #{i}",
                            callback_data=f"downloads:pause:{task.id}"
                        ),
                        InlineKeyboardButton(
                            f"❌ Cancel #{i}",
                            callback_data=f"downloads:cancel:{task.id}"
                        ),
                    ])
                elif task.status == "paused":
                    keyboard.append([
                        InlineKeyboardButton(
                            f"▶️ Resume #{i}",
                            callback_data=f"downloads:resume:{task.id}"
                        ),
                        InlineKeyboardButton(
                            f"❌ Cancel #{i}",
                            callback_data=f"downloads:cancel:{task.id}"
                        ),
                    ])
                elif task.status == "completed":
                    keyboard.append([
                        InlineKeyboardButton(
                            f"✅ Done #{i}",
                            callback_data=f"downloads:remove:{task.id}"
                        ),
                    ])

            # Bottom buttons
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data="downloads:refresh:")
            ])
            keyboard.append([
                InlineKeyboardButton("« Back to Menu", callback_data="downloads:back:")
            ])

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering downloads: {e}")
            text = "📥 *Downloads*\n\nError loading downloads."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="downloads:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

    def _create_progress_bar(self, progress: float, length: int = 10) -> str:
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
        """Called when entering downloads screen.

        Start auto-refresh task.

        Args:
            chat_id: Chat ID
            **kwargs: Additional context
        """
        # Start auto-refresh task for this chat
        if chat_id not in self._update_tasks or self._update_tasks[chat_id].done():
            self._update_tasks[chat_id] = asyncio.create_task(
                self._auto_refresh_loop(chat_id)
            )
            logger.info(f"Started auto-refresh for downloads screen in chat {chat_id}")

    async def on_exit(self, chat_id: int) -> None:
        """Called when leaving downloads screen.

        Stop auto-refresh task.

        Args:
            chat_id: Chat ID
        """
        # Cancel auto-refresh task
        if chat_id in self._update_tasks and not self._update_tasks[chat_id].done():
            self._update_tasks[chat_id].cancel()
            logger.info(f"Stopped auto-refresh for downloads screen in chat {chat_id}")

    async def _auto_refresh_loop(self, chat_id: int) -> None:
        """Auto-refresh loop for real-time updates.

        Args:
            chat_id: Chat ID
        """
        try:
            while True:
                await asyncio.sleep(3)  # Update every 3 seconds
                
                # Check if still on downloads screen
                active_screen = self.screen_manager.get_active_screen(chat_id)
                if not active_screen or active_screen.get_name() != "downloads":
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
        """Handle downloads screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters (task_id)
        """
        chat_id = update.callback_query.message.chat_id

        if action == "back":
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

        elif action == "search":
            await self.navigate_to(chat_id, "search")

        elif action == "refresh":
            await update.callback_query.answer("Refreshing...")
            await self.refresh(chat_id)

        elif action == "pause":
            await self._pause_download(update, context, params)

        elif action == "resume":
            await self._resume_download(update, context, params)

        elif action == "cancel":
            await self._cancel_download(update, context, params)

        elif action == "remove":
            await self._remove_download(update, context, params)

    async def _pause_download(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task_id: str,
    ) -> None:
        """Pause a download.

        Args:
            update: Telegram update
            context: Bot context
            task_id: Task ID
        """
        try:
            success = await self.downloader.pause_download(task_id)
            if success:
                await update.callback_query.answer("Download paused")
            else:
                await update.callback_query.answer("Failed to pause", show_alert=True)
        except Exception as e:
            logger.error(f"Error pausing download: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _resume_download(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task_id: str,
    ) -> None:
        """Resume a download.

        Args:
            update: Telegram update
            context: Bot context
            task_id: Task ID
        """
        try:
            success = await self.downloader.resume_download(task_id)
            if success:
                await update.callback_query.answer("Download resumed")
            else:
                await update.callback_query.answer("Failed to resume", show_alert=True)
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _cancel_download(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task_id: str,
    ) -> None:
        """Cancel a download.

        Args:
            update: Telegram update
            context: Bot context
            task_id: Task ID
        """
        try:
            # Get task info before canceling
            task = await self.downloader.get_task_status(task_id)
            if not task:
                await update.callback_query.answer("Download not found", show_alert=True)
                return

            # Confirm via alert
            await update.callback_query.answer(
                f"Canceling: {task.torrent_name[:30]}...\nFiles will be removed.",
                show_alert=True
            )

            success = await self.downloader.remove_download(task_id, delete_files=True)
            
            if success:
                logger.info(f"Download canceled: {task_id}")
            else:
                await update.callback_query.answer("Failed to cancel", show_alert=True)

        except Exception as e:
            logger.error(f"Error canceling download: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _remove_download(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        task_id: str,
    ) -> None:
        """Remove a completed download from the list.

        Args:
            update: Telegram update
            context: Bot context
            task_id: Task ID
        """
        try:
            success = await self.downloader.remove_download(task_id, delete_files=False)
            if success:
                await update.callback_query.answer("Removed from list")
            else:
                await update.callback_query.answer("Failed to remove", show_alert=True)
        except Exception as e:
            logger.error(f"Error removing download: {e}")
            await update.callback_query.answer("Error", show_alert=True)

