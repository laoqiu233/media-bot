"""Integrated bot with screen-based UI system."""

import asyncio
import logging
import os

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.auth import init_auth
from app.bot.handlers import BotHandlers
from app.bot.screen_registry import ScreenRegistry
from app.bot.session_manager import SessionManager
from app.config import load_config
from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.player.mpv_controller import player
from app.scheduler.series_scheduler import get_scheduler
from app.torrent.downloader import get_downloader
from app.torrent.searcher import TorrentSearcher
from app.tv.hdmi_cec import get_cec_controller

logger = logging.getLogger(__name__)


async def initialize_components():
    """Initialize all system components.

    Returns:
        Tuple of initialized components
    """
    logger.info("Initializing components...")

    # Load configuration
    config = load_config()

    # Initialize authorization
    auth_manager = None
    if config.telegram.authorized_users:
        auth_manager = init_auth(config.telegram.authorized_users)
        logger.info(f"Authorization enabled for {len(config.telegram.authorized_users)} users")
    else:
        logger.warning("No authorized users configured - bot is open to everyone!")

    # Initialize library manager
    library_manager = LibraryManager(config.media_library.library_path)
    movies_count, series_count = await library_manager.scan_library()
    logger.info(f"Library scanned: {movies_count} movies, {series_count} series")

    # Initialize IMDb client
    imdb_client = IMDbClient()
    logger.info("IMDb client initialized")

    # Initialize torrent system
    torrent_searcher = TorrentSearcher()
    torrent_downloader = get_downloader(config.media_library.download_path)

    # Set up callback to import completed downloads to library
    async def on_download_complete(task_id: str, download_info: dict):
        """Import completed download to library."""
        logger.info(f"Processing completed download: {download_info['name']}")
        download_path = torrent_downloader.get_download_path(task_id)
        if download_path and download_path.exists():
            await library_manager.import_from_download(
                download_path=download_path, torrent_name=download_info["name"]
            )
        else:
            logger.warning(f"Download path not found for task {task_id}")

    torrent_downloader.set_completion_callback(on_download_complete)
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

    screen_registry = ScreenRegistry(
        library_manager,
        mpv_controller,
        cec_controller,
        torrent_searcher,
        torrent_downloader,
        imdb_client,
    )

    logger.info("Screen system initialized")

    return (
        config,
        auth_manager,
        screen_registry,
        torrent_downloader,
        mpv_controller,
        series_scheduler,
    )


def run_integrated_bot():
    """Run the integrated bot with screen-based UI."""
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    async def main():
        """Main async function."""
        # Initialize cleanup variables
        downloader = None
        player_controller = None
        scheduler = None

        try:
            # Initialize components
            (
                config,
                auth_manager,
                screen_registry,
                downloader,
                player_controller,
                scheduler,
            ) = await initialize_components()

            # Create Telegram application
            application = Application.builder().token(config.telegram.bot_token).build()

            # Initialize the application to get the bot instance
            await application.initialize()

            # Create session manager and handlers with the bot instance
            session_manager = SessionManager(application.bot, screen_registry)
            handlers = BotHandlers(
                session_manager=session_manager,
                auth_manager=auth_manager,
            )

            # Register handlers
            # Handle /start separately (don't delete it to avoid Telegram resending)
            application.add_handler(CommandHandler("start", handlers.handle_start_command))

            # Handle all other text messages including commands
            application.add_handler(
                MessageHandler(
                    filters.TEXT,  # Accept all text including commands
                    handlers.handle_text_message,
                )
            )

            # Handle all callback queries (button clicks)
            application.add_handler(CallbackQueryHandler(handlers.handle_callback))

            # Mark bot as running for init flow
            os.environ["MEDIA_BOT_RUNNING"] = "1"
            
            # Start the bot (already initialized above)
            await application.start()
            await application.updater.start_polling()

            # Background task to check for restart flag
            async def check_restart_flag():
                from pathlib import Path
                restart_flag = Path(__file__).resolve().parents[2] / ".setup" / ".restart_needed"
                while True:
                    await asyncio.sleep(2)  # Check every 2 seconds
                    if restart_flag.exists():
                        logger.info("Restart flag detected. Restarting bot to apply credential changes...")
                        # Clean up flag
                        try:
                            restart_flag.unlink()
                        except Exception:
                            pass
                        # Restart by exiting - systemd or startup script should handle restart
                        import sys
                        sys.exit(0)
            
            restart_check_task = asyncio.create_task(check_restart_flag())

            # Keep the bot running
            try:
                # Wait indefinitely until interrupted
                await asyncio.Event().wait()
            finally:
                # Stop the updater
                await application.updater.stop()
                await application.stop()
                await application.shutdown()

        except KeyboardInterrupt:
            logger.info("Received stop signal")
        except Exception as e:
            logger.error(f"Error running bot: {e}", exc_info=True)
        finally:
            # Cleanup
            logger.info("Shutting down...")
            # Cancel restart check task
            if 'restart_check_task' in locals():
                restart_check_task.cancel()
                try:
                    await restart_check_task
                except asyncio.CancelledError:
                    pass
            if downloader:
                downloader.stop_monitoring()
                downloader.shutdown()
            if player_controller:
                player_controller.shutdown()
            if scheduler:
                await scheduler.save_progress()
            # Clear running flag
            os.environ.pop("MEDIA_BOT_RUNNING", None)
            logger.info("Shutdown complete")

    # Run the async main function
    asyncio.run(main())
