"""Downloads screen for monitoring active downloads."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    DOWNLOADS_BACK,
    DOWNLOADS_CANCEL,
    DOWNLOADS_PAUSE,
    DOWNLOADS_RESUME,
    DOWNLOADS_SEARCH,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.torrent.downloader import DownloadStatus, TorrentDownloader

logger = logging.getLogger(__name__)


class DownloadsScreen(Screen):
    """Screen for viewing and managing downloads."""

    def __init__(self, downloader: TorrentDownloader):
        """Initialize downloads screen.

        Args:
            downloader: Torrent downloader
        """
        self.downloader = downloader

    def get_name(self) -> str:
        """Get screen name."""
        return "downloads"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the downloads screen.

        Args:
            session: The session object

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            tasks = await self.downloader.get_all_tasks()

            if not tasks:
                text = "📥 *Downloads*\n\nNo active downloads.\n\nUse Search to find and download content."
                keyboard = [
                    [InlineKeyboardButton("🔍 Search Content", callback_data=DOWNLOADS_SEARCH)],
                    [InlineKeyboardButton("« Back to Menu", callback_data=DOWNLOADS_BACK)],
                ]
                return text, InlineKeyboardMarkup(keyboard), RenderOptions()

            # Build downloads status text
            text = "📥 *Active Downloads*\n\n"

            keyboard = []

            for i, task in enumerate(tasks, 1):
                # Progress bar
                progress_bar = self._create_progress_bar(task.progress)

                # Status line
                status_emoji = {
                    DownloadStatus.DOWNLOADING: "⬇️",
                    DownloadStatus.COMPLETED: "✅",
                    DownloadStatus.PAUSED: "⏸",
                    DownloadStatus.ERROR: "❌",
                }.get(task.status, "📦")

                text += f"{i}. {status_emoji} *{task.name[:35]}*\n"
                text += f"   {progress_bar} {task.progress:.1f}%\n"

                # Show size info
                if task.total_wanted > 0:
                    downloaded_gb = task.total_done / 1024 / 1024 / 1024
                    total_gb = task.total_wanted / 1024 / 1024 / 1024
                    text += f"   📦 {downloaded_gb:.2f} / {total_gb:.2f} GB\n"

                if task.status == DownloadStatus.DOWNLOADING:
                    # Download speed and ETA
                    speed_mb = task.download_rate / 1024 / 1024
                    text += f"   ⬇️ {speed_mb:.2f} MB/s"

                    if task.eta:
                        minutes = task.eta // 60
                        seconds = task.eta % 60
                        text += f" • ETA: {minutes}m {seconds}s"
                    text += "\n"

                    # Upload speed
                    upload_mb = task.upload_rate / 1024 / 1024
                    text += f"   ⬆️ {upload_mb:.2f} MB/s\n"

                    # Seeders and peers
                    text += f"   🌱 {task.num_seeds} seeders • 👥 {task.num_peers} peers\n"

                elif task.status == DownloadStatus.COMPLETED:
                    text += "   Status: Completed ✅\n"
                    # Show upload speed even when completed (seeding)
                    upload_mb = task.upload_rate / 1024 / 1024
                    if upload_mb > 0:
                        text += f"   ⬆️ {upload_mb:.2f} MB/s (seeding)\n"
                else:
                    text += f"   Status: {task.status.value.capitalize()}\n"

                text += "\n"

                # Add control button
                if task.status == DownloadStatus.DOWNLOADING:
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"⏸ Pause #{i}", callback_data=f"{DOWNLOADS_PAUSE}{task.task_id}"
                            ),
                            InlineKeyboardButton(
                                f"❌ Cancel #{i}", callback_data=f"{DOWNLOADS_CANCEL}{task.task_id}"
                            ),
                        ]
                    )
                elif task.status == DownloadStatus.PAUSED:
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"▶️ Resume #{i}", callback_data=f"{DOWNLOADS_RESUME}{task.task_id}"
                            ),
                            InlineKeyboardButton(
                                f"❌ Cancel #{i}", callback_data=f"{DOWNLOADS_CANCEL}{task.task_id}"
                            ),
                        ]
                    )
            # Bottom buttons
            keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data=DOWNLOADS_BACK)])

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering downloads: {e}")
            text = "📥 *Downloads*\n\nError loading downloads."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=DOWNLOADS_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

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

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle downloads screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            session: The session object
            callback_data: Raw callback data string
        """
        if query.data is None:
            return

        if query.data == DOWNLOADS_BACK:
            return Navigation("main_menu", add_to_history=False)

        elif query.data == DOWNLOADS_SEARCH:
            return Navigation("search")

        elif query.data.startswith(DOWNLOADS_PAUSE):
            task_id = query.data[len(DOWNLOADS_PAUSE) :]
            await self._pause_download(query, task_id)

        elif query.data.startswith(DOWNLOADS_RESUME):
            task_id = query.data[len(DOWNLOADS_RESUME) :]
            await self._resume_download(query, task_id)

        elif query.data.startswith(DOWNLOADS_CANCEL):
            task_id = query.data[len(DOWNLOADS_CANCEL) :]
            await self._cancel_download(query, task_id)

    async def _pause_download(
        self,
        query: CallbackQuery,
        task_id: str,
    ) -> None:
        """Pause a download.

        Args:
            query: CallbackQuery
            context: Bot context
            task_id: Task ID
        """
        try:
            success = await self.downloader.pause_download(task_id)
            if success:
                await query.answer("Download paused")
            else:
                await query.answer("Failed to pause", show_alert=True)
        except Exception as e:
            logger.error(f"Error pausing download: {e}")
            await query.answer("Error", show_alert=True)

    async def _resume_download(
        self,
        query: CallbackQuery,
        task_id: str,
    ) -> ScreenHandlerResult:
        try:
            success = await self.downloader.resume_download(task_id)
            if success:
                await query.answer("Download resumed")
            else:
                await query.answer("Failed to resume", show_alert=True)
        except Exception as e:
            logger.error(f"Error resuming download: {e}")
            await query.answer("Error", show_alert=True)

    async def _cancel_download(
        self,
        query: CallbackQuery,
        task_id: str,
    ) -> ScreenHandlerResult:
        try:
            task = await self.downloader.get_task_status(task_id)
            if not task:
                await query.answer("Download not found", show_alert=True)
                return

            # Confirm via alert
            await query.answer(
                f"Canceling: {task.name[:30]}...\nFiles will be removed.", show_alert=True
            )

            success = await self.downloader.remove_download(task_id, delete_files=True)

            if success:
                logger.info(f"Download canceled: {task_id}")
            else:
                await query.answer("Failed to cancel", show_alert=True)

        except Exception as e:
            logger.error(f"Error canceling download: {e}")
            await query.answer("Error", show_alert=True)
