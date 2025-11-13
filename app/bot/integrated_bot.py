"""Integrated bot with screen-based UI system."""

import asyncio
import logging

from telegram import error as telegram_error
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.auth import init_auth
from app.bot.handlers import BotHandlers
from app.bot.screen_registry import ScreenRegistry
from app.bot.session_manager import SessionManager
from app.config import load_config
from app.init_flow import ensure_telegram_token, remove_telegram_token_from_env
from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.player.mpv_controller import player
from app.scheduler.series_scheduler import get_scheduler
from app.scheduler.series_updater import SeriesUpdater
from app.scheduler.watch_progress import get_watch_progress_manager
from app.torrent.downloader import DownloadState, TorrentDownloader
from app.torrent.importer import TorrentImporter
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
    torrent_searcher = TorrentSearcher(config)
    torrent_downloader = TorrentDownloader(config)

    # Initialize torrent importer
    torrent_importer = TorrentImporter(library_manager, imdb_client)

    # Set up callback to import completed downloads to library
    async def on_download_complete(task_id: str, state: DownloadState) -> None:
        """Import completed download to library.

        Args:
            task_id: Download task ID
            state: Download state with metadata and validation result
        """
        try:
            logger.info(f"Processing completed download: {state.name}")

            download_path = torrent_downloader.get_download_path(task_id)
            if not download_path or not download_path.exists():
                logger.warning(f"Download path not found for task {task_id}")
                return

            # Import using TorrentImporter with validation result
            await torrent_importer.import_download(
                download_path=download_path,
                torrent=state.torrent,
                validation_result=state.validation_result,
            )

            logger.info(f"Successfully imported download: {state.name}")

        except Exception as e:
            logger.error(f"Failed to import download {task_id}: {e}", exc_info=True)

    # Load and resume persisted downloads
    resumed_count = await torrent_downloader.load_and_resume_downloads()
    if resumed_count > 0:
        logger.info(f"Resumed {resumed_count} download(s) from previous session")

    # Set completion callback and start monitoring
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
            downloader=torrent_downloader,  # Pass downloader for auto-pause/resume
        )
        logger.info("MPV player initialized with downloader integration")
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

    # Initialize watch progress manager
    watch_progress_mgr = get_watch_progress_manager(data_dir)
    await watch_progress_mgr.load_progress()
    logger.info("Watch progress manager initialized")

    # Re-initialize MPV with watch progress manager
    try:
        mpv_controller.initialize(
            vo=config.mpv.vo,
            ao=config.mpv.ao,
            fullscreen=config.mpv.fullscreen,
            hwdec=config.mpv.hwdec,
            downloader=torrent_downloader,
            watch_progress_manager=watch_progress_mgr,
        )
        logger.info("MPV player re-initialized with watch progress manager")
    except Exception as e:
        logger.warning(f"MPV re-initialization failed: {e}")

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
        watch_progress_mgr,
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
        watch_progress = None
        series_updater = None

        try:
            # Initialize components
            (
                config,
                auth_manager,
                screen_registry,
                downloader,
                player_controller,
                scheduler,
                watch_progress,
            ) = await initialize_components()

            # Create Telegram application
            application = Application.builder().token(config.telegram.bot_token).build()

            # Initialize and start the bot - catch Conflict errors
            try:
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

                # Start the bot (already initialized above)
                await application.start()
                await application.updater.start_polling()
            except telegram_error.Conflict as e:
                # Another bot instance is running - remove token and run init_flow
                logger.error(
                    f"Bot conflict detected: {e}. "
                    "Another instance is using this bot token. "
                    "Removing token from .env and running setup flow..."
                )
                remove_telegram_token_from_env()
                logger.info("Running init_flow to configure new bot token...")
                await ensure_telegram_token(force=True)
                logger.info("Setup complete. Please restart the bot.")
                return

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
            if downloader:
                downloader.shutdown()
            if player_controller:
                player_controller.shutdown()
            if scheduler:
                await scheduler.save_progress()
            if watch_progress:
                await watch_progress.save_progress()
            if series_updater:
                series_updater.stop()
            logger.info("Shutdown complete")

    # Run the async main function
    asyncio.run(main())
