"""Integrated bot with all system components."""

import asyncio
import logging
import os
from pathlib import Path

from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import load_config
from app.library.manager import LibraryManager
from app.torrent.searcher import TorrentSearcher
from app.torrent.downloader import get_downloader
from app.player.mpv_controller import player
from app.tv.hdmi_cec import get_cec_controller
from app.scheduler.series_scheduler import get_scheduler
from app.bot.handlers import BotHandlers

logger = logging.getLogger(__name__)


async def initialize_components():
    """Initialize all system components.

    Returns:
        Tuple of initialized components
    """
    logger.info("Initializing components...")

    # Load configuration
    config = load_config()

    # Initialize library manager
    library_manager = LibraryManager(config.media_library.library_path)
    movies_count, series_count = await library_manager.scan_library()
    logger.info(f"Library scanned: {movies_count} movies, {series_count} series")

    # Initialize torrent system
    torrent_searcher = TorrentSearcher()
    torrent_downloader = get_downloader(config.media_library.download_path)
    torrent_downloader.start_monitoring()
    logger.info("Torrent system initialized")

    # Initialize MPV player
    mpv_controller = player
    try:
        mpv_controller.initialize(
            vo=config.mpv.vo,
            ao=config.mpv.ao,
            fullscreen=config.mpv.fullscreen,
            hwdec=config.mpv.hwdec,
        )
        logger.info("MPV player initialized")
    except Exception as e:
        logger.warning(f"MPV initialization failed: {e}")

    # Initialize CEC controller
    cec_controller = get_cec_controller(
        cec_device=config.cec.device,
        enabled=config.cec.enabled,
    )
    logger.info("CEC controller initialized")

    # Initialize series scheduler
    data_dir = config.media_library.library_path / "data"
    series_scheduler = get_scheduler(data_dir)
    await series_scheduler.load_progress()
    logger.info("Series scheduler initialized")

    # Create bot handlers
    bot_handlers = BotHandlers(
        library_manager=library_manager,
        torrent_searcher=torrent_searcher,
        torrent_downloader=torrent_downloader,
        mpv_controller=mpv_controller,
        cec_controller=cec_controller,
        series_scheduler=series_scheduler,
    )

    return config, bot_handlers, torrent_downloader, mpv_controller, series_scheduler


def run_integrated_bot():
    """Run the integrated bot with all components."""
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    async def main():
        """Main async function."""
        try:
            # Initialize components
            config, handlers, downloader, player, scheduler = (
                await initialize_components()
            )

            # Create Telegram application
            application = Application.builder().token(config.telegram.bot_token).build()

            # Register command handlers
            application.add_handler(CommandHandler("start", handlers.start_command))
            application.add_handler(CommandHandler("help", handlers.help_command))
            application.add_handler(CommandHandler("search", handlers.search_command))
            application.add_handler(CommandHandler("library", handlers.library_command))
            application.add_handler(
                CommandHandler("downloads", handlers.downloads_command)
            )
            application.add_handler(CommandHandler("play", handlers.play_command))
            application.add_handler(CommandHandler("tv_on", handlers.tv_on_command))
            application.add_handler(CommandHandler("tv_off", handlers.tv_off_command))
            application.add_handler(CommandHandler("status", handlers.status_command))

            # Register callback query handler
            application.add_handler(CallbackQueryHandler(handlers.handle_callback))

            logger.info("🚀 Media Bot is starting...")
            logger.info("Press Ctrl+C to stop")

            # Run the bot
            await application.run_polling()

        except KeyboardInterrupt:
            logger.info("Received stop signal")
        except Exception as e:
            logger.error(f"Error running bot: {e}", exc_info=True)
        finally:
            # Cleanup
            logger.info("Shutting down...")
            if downloader:
                downloader.stop_monitoring()
                downloader.shutdown()
            if player:
                player.shutdown()
            if scheduler:
                await scheduler.save_progress()
            logger.info("Shutdown complete")

    # Run the async main function
    asyncio.run(main())

