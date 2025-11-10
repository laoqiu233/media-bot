"""Telegram bot handlers with full system integration."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.library.manager import LibraryManager
from app.library.models import MediaType, Movie, Series, Episode
from app.player.mpv_controller import MPVController
from app.torrent.downloader import TorrentDownloader
from app.torrent.searcher import TorrentSearcher
from app.tv.hdmi_cec import CECController
from app.scheduler.series_scheduler import SeriesScheduler

logger = logging.getLogger(__name__)


class BotHandlers:
    """Handlers for telegram bot commands and callbacks."""

    def __init__(
        self,
        library_manager: LibraryManager,
        torrent_searcher: TorrentSearcher,
        torrent_downloader: TorrentDownloader,
        mpv_controller: MPVController,
        cec_controller: CECController,
        series_scheduler: SeriesScheduler,
    ):
        """Initialize bot handlers.

        Args:
            library_manager: Media library manager
            torrent_searcher: Torrent searcher
            torrent_downloader: Torrent downloader
            mpv_controller: MPV player controller
            cec_controller: CEC TV controller
            series_scheduler: Series scheduler
        """
        self.library = library_manager
        self.searcher = torrent_searcher
        self.downloader = torrent_downloader
        self.player = mpv_controller
        self.cec = cec_controller
        self.scheduler = series_scheduler

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome_text = (
            "🎬 Welcome to Media Bot!\n\n"
            "Your smart media center for Raspberry Pi.\n\n"
            "Available commands:\n"
            "/search <query> - Search for content\n"
            "/library - Browse your media library\n"
            "/downloads - View download status\n"
            "/play - Playback controls\n"
            "/tv_on - Turn TV on\n"
            "/tv_off - Turn TV off\n"
            "/status - Player status\n"
            "/help - Show this message"
        )

        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self.start_command(update, context)

    async def search_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /search command."""
        if not context.args:
            await update.message.reply_text(
                "Please provide a search query.\nUsage: /search <movie or series name>"
            )
            return

        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for: {query}...")

        try:
            results = await self.searcher.search(query, limit=10)

            if not results:
                await update.message.reply_text(
                    f"No results found for '{query}'. Try a different search term."
                )
                return

            # Store results in user context
            context.user_data["search_results"] = results
            context.user_data["search_page"] = 0

            # Create keyboard with results
            keyboard = []
            for i, result in enumerate(results[:5]):  # Show first 5
                button_text = (
                    f"{result.title[:40]}... - {result.quality} - {result.size} "
                    f"(S:{result.seeders})"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            button_text, callback_data=f"download_{i}"
                        )
                    ]
                )

            # Navigation buttons
            nav_buttons = []
            if len(results) > 5:
                nav_buttons.append(
                    InlineKeyboardButton("Next ➡️", callback_data="search_next")
                )
            keyboard.append(nav_buttons)

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"Found {len(results)} results. Select one to download:",
                reply_markup=reply_markup,
            )

        except Exception as e:
            logger.error(f"Error searching torrents: {e}")
            await update.message.reply_text(
                "An error occurred while searching. Please try again."
            )

    async def library_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /library command."""
        await update.message.reply_text("📚 Loading library...")

        try:
            movies = await self.library.get_all_movies()
            series = await self.library.get_all_series()

            if not movies and not series:
                await update.message.reply_text(
                    "Your library is empty. Search and download content to get started!"
                )
                return

            keyboard = []

            if movies:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"🎬 Movies ({len(movies)})", callback_data="lib_movies"
                        )
                    ]
                )

            if series:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📺 Series ({len(series)})", callback_data="lib_series"
                        )
                    ]
                )

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔄 Scan Library", callback_data="lib_scan"
                    )
                ]
            )

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"📚 Your Library:\n\n"
                f"Movies: {len(movies)}\n"
                f"Series: {len(series)}\n\n"
                f"Select a category:",
                reply_markup=reply_markup,
            )

        except Exception as e:
            logger.error(f"Error loading library: {e}")
            await update.message.reply_text(
                "An error occurred while loading the library."
            )

    async def downloads_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /downloads command."""
        try:
            tasks = await self.downloader.get_all_tasks()

            if not tasks:
                await update.message.reply_text("No active downloads.")
                return

            status_text = "📥 Active Downloads:\n\n"

            for task in tasks:
                status_text += (
                    f"📦 {task.torrent_name[:40]}...\n"
                    f"Status: {task.status}\n"
                    f"Progress: {task.progress:.1f}%\n"
                    f"Speed: {task.download_speed / 1024 / 1024:.2f} MB/s\n"
                    f"Seeders: {task.seeders} | Peers: {task.peers}\n"
                )

                if task.eta:
                    minutes = task.eta // 60
                    status_text += f"ETA: {minutes} min\n"

                status_text += "\n"

            await update.message.reply_text(status_text)

        except Exception as e:
            logger.error(f"Error getting download status: {e}")
            await update.message.reply_text(
                "An error occurred while fetching download status."
            )

    async def play_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /play command - show player controls."""
        try:
            status = await self.player.get_status()

            keyboard = [
                [
                    InlineKeyboardButton("⏸ Pause", callback_data="player_pause"),
                    InlineKeyboardButton("▶️ Resume", callback_data="player_resume"),
                ],
                [
                    InlineKeyboardButton("⏹ Stop", callback_data="player_stop"),
                    InlineKeyboardButton("🔄 Status", callback_data="player_status"),
                ],
                [
                    InlineKeyboardButton("🔊 Vol+", callback_data="player_vol_up"),
                    InlineKeyboardButton("🔉 Vol-", callback_data="player_vol_down"),
                ],
                [
                    InlineKeyboardButton("⏪ -30s", callback_data="player_seek_-30"),
                    InlineKeyboardButton("⏩ +30s", callback_data="player_seek_30"),
                ],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            status_text = "🎮 Player Controls\n\n"
            if status["is_playing"]:
                status_text += f"▶️ Playing: {Path(status['current_file']).name}\n"
                if status["position"] and status["duration"]:
                    progress = (status["position"] / status["duration"]) * 100
                    status_text += f"Progress: {progress:.1f}%\n"
                    status_text += (
                        f"Time: {int(status['position'])}s / {int(status['duration'])}s\n"
                    )
                status_text += f"Volume: {status['volume']}%"
            else:
                status_text += "⏹ No media playing"

            await update.message.reply_text(status_text, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error showing player controls: {e}")
            await update.message.reply_text("Error loading player controls.")

    async def tv_on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tv_on command."""
        try:
            success = await self.cec.tv_on()
            if success:
                await update.message.reply_text("📺 TV turned on!")
            else:
                await update.message.reply_text(
                    "Failed to turn on TV. Check CEC connection."
                )
        except Exception as e:
            logger.error(f"Error turning TV on: {e}")
            await update.message.reply_text("Error controlling TV.")

    async def tv_off_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tv_off command."""
        try:
            success = await self.cec.tv_off()
            if success:
                await update.message.reply_text("📺 TV turned off!")
            else:
                await update.message.reply_text(
                    "Failed to turn off TV. Check CEC connection."
                )
        except Exception as e:
            logger.error(f"Error turning TV off: {e}")
            await update.message.reply_text("Error controlling TV.")

    async def status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /status command."""
        try:
            player_status = await self.player.get_status()
            cec_status = await self.cec.get_status()

            status_text = "🖥 System Status\n\n"

            # Player status
            status_text += "🎮 Player:\n"
            if player_status["is_playing"]:
                status_text += f"▶️ Playing: {Path(player_status['current_file']).name}\n"
            else:
                status_text += "⏹ Idle\n"

            # CEC status
            status_text += "\n📺 TV (CEC):\n"
            if cec_status["available"]:
                status_text += f"Power: {cec_status.get('power_status', 'unknown')}\n"
                if cec_status.get("tv_name"):
                    status_text += f"Device: {cec_status['tv_name']}\n"
            else:
                status_text += "Not available\n"

            # Download status
            tasks = await self.downloader.get_all_tasks()
            active_downloads = [t for t in tasks if t.status == "downloading"]
            status_text += f"\n📥 Downloads: {len(active_downloads)} active\n"

            await update.message.reply_text(status_text)

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            await update.message.reply_text("Error retrieving system status.")

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        await query.answer()

        data = query.data

        try:
            # Download torrent
            if data.startswith("download_"):
                index = int(data.split("_")[1])
                results = context.user_data.get("search_results", [])

                if 0 <= index < len(results):
                    result = results[index]
                    await query.edit_message_text(
                        f"⬇️ Starting download: {result.title}..."
                    )

                    task_id = await self.downloader.add_download(
                        result.magnet_link, result.title
                    )

                    await query.edit_message_text(
                        f"✅ Download started!\n\n"
                        f"Title: {result.title}\n"
                        f"Size: {result.size}\n"
                        f"Quality: {result.quality}\n\n"
                        f"Use /downloads to check progress."
                    )

            # Library browsing
            elif data == "lib_movies":
                movies = await self.library.get_all_movies()
                keyboard = []

                for movie in movies[:10]:  # Show first 10
                    button_text = f"{movie.title} ({movie.year or 'N/A'})"
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                button_text, callback_data=f"play_movie_{movie.id}"
                            )
                        ]
                    )

                keyboard.append(
                    [InlineKeyboardButton("⬅️ Back", callback_data="lib_back")]
                )

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"🎬 Movies ({len(movies)}):", reply_markup=reply_markup
                )

            elif data == "lib_series":
                series = await self.library.get_all_series()
                keyboard = []

                for s in series[:10]:  # Show first 10
                    button_text = f"{s.title} ({s.year or 'N/A'})"
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                button_text, callback_data=f"view_series_{s.id}"
                            )
                        ]
                    )

                keyboard.append(
                    [InlineKeyboardButton("⬅️ Back", callback_data="lib_back")]
                )

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"📺 Series ({len(series)}):", reply_markup=reply_markup
                )

            elif data == "lib_scan":
                await query.edit_message_text("🔄 Scanning library...")
                movies_count, series_count = await self.library.scan_library()
                await query.edit_message_text(
                    f"✅ Library scanned!\n\nMovies: {movies_count}\nSeries: {series_count}"
                )

            # Play movie
            elif data.startswith("play_movie_"):
                movie_id = data.split("_", 2)[2]
                movie = await self.library.get_movie(movie_id)

                if movie and movie.file_path:
                    # Ensure file_path is a Path object
                    file_path = Path(movie.file_path) if isinstance(movie.file_path, str) else movie.file_path
                    
                    if not file_path.exists():
                        await query.edit_message_text(
                            f"❌ File not found: {movie.title}\n"
                            f"Path: {file_path}"
                        )
                        logger.error(f"Movie file does not exist: {file_path}")
                        return
                    
                    await query.edit_message_text(f"▶️ Playing: {movie.title}...")
                    logger.info(f"Attempting to play: {file_path}")
                    
                    success = await self.player.play(file_path)

                    if success:
                        await query.edit_message_text(
                            f"✅ Now playing: {movie.title}\n\n"
                            f"Use /play for controls."
                        )
                    else:
                        await query.edit_message_text(
                            f"❌ Failed to play: {movie.title}\n"
                            f"Check logs for details."
                        )
                else:
                    await query.edit_message_text("Movie file not found.")

            # Player controls
            elif data == "player_pause":
                success = await self.player.pause()
                await query.answer("⏸ Paused" if success else "Failed")

            elif data == "player_resume":
                success = await self.player.resume()
                await query.answer("▶️ Resumed" if success else "Failed")

            elif data == "player_stop":
                success = await self.player.stop()
                await query.answer("⏹ Stopped" if success else "Failed")

            elif data == "player_vol_up":
                success = await self.player.volume_up()
                await query.answer("🔊 Volume up" if success else "Failed")

            elif data == "player_vol_down":
                success = await self.player.volume_down()
                await query.answer("🔉 Volume down" if success else "Failed")

            elif data.startswith("player_seek_"):
                seconds = int(data.split("_")[2])
                success = await self.player.seek(seconds, relative=True)
                await query.answer(f"⏩ Seeked {seconds}s" if success else "Failed")

            elif data == "player_status":
                status = await self.player.get_status()
                status_text = "🎮 Player Status\n\n"

                if status["is_playing"]:
                    status_text += f"▶️ Playing\n"
                    if status["position"] and status["duration"]:
                        progress = (status["position"] / status["duration"]) * 100
                        status_text += f"Progress: {progress:.1f}%\n"
                else:
                    status_text += "⏹ Stopped"

                await query.answer(status_text, show_alert=True)

        except Exception as e:
            logger.error(f"Error handling callback {data}: {e}")
            await query.answer("An error occurred", show_alert=True)

