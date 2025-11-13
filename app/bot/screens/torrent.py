"""Unified torrent screen for provider selection and results display."""

import asyncio
import logging
import os
from dataclasses import dataclass, field

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    PROVIDER_SELECT,
    TORRENT_BACK,
    TORRENT_DOWNLOAD_CANCEL,
    TORRENT_DOWNLOAD_CONFIRM,
    TORRENT_NEXT,
    TORRENT_PREV,
    TORRENT_SELECT,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.bot.screens.movie_selection import MovieSelectionState
from app.library.models import (
    DownloadEpisode,
    DownloadIMDbMetadata,
    DownloadSeason,
    DownloadSeries,
    MatchedTorrentFiles,
)
from app.torrent.downloader import TorrentDownloader
from app.torrent.searcher import TorrentSearcher, TorrentSearchResult
from app.torrent.validator import TorrentValidator

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5
TORRENT_SCREEN_STATE = "torrent_screen_state"


@dataclass
class TorrentScreenState:
    """State of the torrent screen."""

    view: str = "providers"
    imdb_metadata: DownloadIMDbMetadata | None = None
    movie_selection_state: MovieSelectionState | None = None
    results_page: int = 0
    results: list[TorrentSearchResult] = field(default_factory=list)
    search_in_progress: bool = False
    validation_result: MatchedTorrentFiles | None = None
    pending_download: TorrentSearchResult | None = None
    error: str | None = None


class TorrentScreen(Screen):
    """Unified screen for torrent provider selection and results browsing."""

    def __init__(
        self,
        searcher: TorrentSearcher,
        downloader: TorrentDownloader,
        validator: TorrentValidator,
    ):
        """Initialize torrent screen.

        Args:
            searcher: Torrent searcher
            downloader: Torrent downloader
            validator: Torrent validator
        """
        self.searcher = searcher
        self.downloader = downloader
        self.validator = validator

    def get_name(self) -> str:
        """Get screen name."""
        return "torrent"

    def _get_state(self, context: Context) -> TorrentScreenState:
        """Get the state of the screen."""
        return context.get(TORRENT_SCREEN_STATE)

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.

        Expects kwargs:
            imdb_metadata: Download metadata object
            movie_selection_state: State from movie selection screen
            torrent_screen_state: Existing state (when returning from auth screen)
            trigger_rutracker_search: Boolean to trigger RuTracker search on enter
        """
        # Check if we're returning from auth screen with existing state
        if "torrent_screen_state" in kwargs:
            existing_state = kwargs["torrent_screen_state"]
            context.update_context(**{TORRENT_SCREEN_STATE: existing_state})

            # If we should trigger a RuTracker search after auth
            if kwargs.get("trigger_rutracker_search") and existing_state.imdb_metadata:
                asyncio.create_task(
                    self._search_torrents(context, existing_state.imdb_metadata, "rutracker")
                )
        else:
            # Start with provider selection view
            context.update_context(
                **{
                    TORRENT_SCREEN_STATE: TorrentScreenState(
                        imdb_metadata=kwargs.get("imdb_metadata"),
                        movie_selection_state=kwargs.get("movie_selection_state"),
                    )
                }
            )

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the screen based on current view state."""
        state = self._get_state(context)

        if state.view == "providers":
            return await self._render_providers(context)
        elif state.view == "results":
            return await self._render_results(context)
        elif state.view == "validation_warning":
            return await self._render_validation_warning(context)
        elif state.view == "validation_failed":
            return await self._render_validation_failed(context)
        elif state.view == "validation_error":
            return await self._render_validation_error(context)

        state.view = "providers"
        return await self._render_providers(context)

    async def _render_providers(self, context: Context) -> ScreenRenderResult:
        """Render the provider selection view."""
        state = self._get_state(context)

        if not state.imdb_metadata:
            text = "⚠️ *Error*\n\nNo download target selected."
            keyboard = [[InlineKeyboardButton("« Back", callback_data=TORRENT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        search_query = str(state.imdb_metadata)

        text = "📥 *Select Torrent Provider*\n\n"
        text += f"Searching for: {search_query}\n\n"
        text += "Choose where to search for torrents:"

        # Define available providers
        providers = [
            {"name": "YTS", "emoji": "🎥", "description": "High quality movies"},
            {"name": "RuTracker", "emoji": "🏴‍☠️", "description": "You know what this is"},
        ]

        keyboard = []

        # Add provider buttons
        for provider in providers:
            button_text = f"{provider['emoji']} {provider['name']} - {provider['description']}"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{PROVIDER_SELECT}{provider['name'].lower()}"
                    )
                ]
            )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Movies", callback_data=TORRENT_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_results(self, context: Context) -> ScreenRenderResult:
        """Render the torrent results view."""
        state = self._get_state(context)

        if state.imdb_metadata is None:
            text = "⚠️ *Error*\n\nNo download target selected."
            return (
                text,
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
                ),
                RenderOptions(),
            )

        search_query = state.imdb_metadata.__str__()

        if state.search_in_progress:
            text = f"🔍 *Searching for torrents for: {search_query}...*\n\n"
            return (
                text,
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
                ),
                RenderOptions(),
            )

        if state.error:
            text = f"❌ *Error:* {state.error}\n\n"
            text += "Please try again or go back."
            return (
                text,
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
                ),
                RenderOptions(),
            )

        # If no results found
        if not state.results:
            text = f"No torrents found for: _{search_query}_\n\n"
            text += "Try going back and selecting a different provider."
            keyboard = [[InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Show results
        start_idx = state.results_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_results = state.results[start_idx:end_idx]

        total_pages = (len(state.results) - 1) // ITEMS_PER_PAGE + 1
        text = "📥 *Torrent Results*\n\n"
        text += (
            f"Found {len(state.results)} results (page {state.results_page + 1}/{total_pages})\n\n"
        )

        # Show results with details in text
        for i, result in enumerate(page_results):
            safe_title = result.title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
            text += f"{i + 1}. *{safe_title}*\n"
            text += f"   📁 {result.quality.value.capitalize()} • {result.size} • 🌱 {result.seeders} seeders\n\n"

        keyboard = []

        # Add result buttons
        for i, result in enumerate(page_results):
            actual_idx = start_idx + i
            button_text = f"{i + 1}. {result.title[:35]}"
            if len(button_text) > 45:
                button_text = button_text[:42] + "..."

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{TORRENT_SELECT}{actual_idx}")]
            )

        # Navigation buttons
        nav_buttons = []
        if state.results_page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=TORRENT_PREV))
        if end_idx < len(state.results):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=TORRENT_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Providers", callback_data=TORRENT_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        state = self._get_state(context)

        if query.data is None:
            return

        if query.data == TORRENT_BACK:
            # Handle back from different views
            if state.view in ("validation_warning", "validation_failed", "validation_error"):
                # Back from validation views - go to results
                state.view = "results"
                state.validation_result = None
                state.pending_download = None
                return
            elif state.view == "results":
                # Back from results view - go to providers view
                state.view = "providers"
                state.results_page = 0
                return
            elif state.view == "providers":
                # Back from providers - go to movie selection or main menu
                if state.movie_selection_state is None:
                    return Navigation(next_screen="main_menu")
                return Navigation(
                    next_screen="movie_selection", movie_selection_state=state.movie_selection_state
                )

        # Provider selection
        elif query.data.startswith(PROVIDER_SELECT):
            provider = query.data[len(PROVIDER_SELECT) :]

            if state.imdb_metadata:
                # Check if RuTracker credentials are needed
                if provider == "rutracker":
                    tracker_username = os.getenv("TRACKER_USERNAME")
                    tracker_password = os.getenv("TRACKER_PASSWORD")

                    if not tracker_username or not tracker_password:
                        # Credentials missing - navigate to authorization screen
                        await query.answer("RuTracker credentials required", show_alert=True)
                        return Navigation(
                            next_screen="rutracker_auth",
                            torrent_screen_state=state,
                        )

                await query.answer(f"Searching {provider.upper()}...", show_alert=False)
                await self._search_torrents(context, state.imdb_metadata, provider)
                return

        # Results view pagination
        elif query.data == TORRENT_PREV:
            state.results_page = max(0, state.results_page - 1)
            return

        elif query.data == TORRENT_NEXT:
            state.results_page = state.results_page + 1
            return

        # Torrent selection
        elif query.data.startswith(TORRENT_SELECT):
            index = int(query.data[len(TORRENT_SELECT) :])
            return await self._start_download(query, context, index)

        # Download confirmation after validation warning
        elif query.data == TORRENT_DOWNLOAD_CONFIRM:
            await self._confirm_and_download(state)
            await query.answer("Download started!", show_alert=False)
            return Navigation(next_screen="downloads")

        # Cancel download after validation warning
        elif query.data == TORRENT_DOWNLOAD_CANCEL:
            state.view = "results"
            state.validation_result = None
            state.pending_download = None
            await query.answer("Download cancelled", show_alert=False)
            return

        return

    async def _search_torrents(
        self, context: Context, imdb_metadata: DownloadIMDbMetadata, provider: str
    ) -> None:
        """Search for torrents and update context with results."""
        state = self._get_state(context)
        state.view = "results"
        state.search_in_progress = True
        state.results = []
        state.results_page = 0
        state.error = None
        try:
            results = await self.searcher.search(provider, imdb_metadata, limit=20)
            if results:
                state.results = results
            elif isinstance(imdb_metadata, DownloadEpisode):
                return await self._search_torrents(
                    context,
                    DownloadSeason(series=imdb_metadata.series, season=imdb_metadata.season),
                    provider,
                )
            elif isinstance(imdb_metadata, DownloadSeason):
                return await self._search_torrents(
                    context, DownloadSeries(series=imdb_metadata.series), provider
                )
            state.search_in_progress = False
        except Exception as e:
            logger.error(f"Error searching torrents: {e}")
            state.error = str(e)
            state.search_in_progress = False

    async def _start_download(
        self,
        query: CallbackQuery,
        context: Context,
        index: int,
    ) -> ScreenHandlerResult:
        """Start validation and download flow for selected torrent."""
        try:
            state = self._get_state(context)

            if state.imdb_metadata is None:
                return

            if 0 <= index < len(state.results):
                result = state.results[index]

                # Show validation message
                await query.answer("Validating torrent content...", show_alert=False)
                state.pending_download = result

                try:
                    # Call validator

                    validation = await self.validator.validate_torrent(result, state.imdb_metadata)

                    state.validation_result = validation

                    # Handle validation results
                    if len(validation.matched_files) == 0:
                        state.view = "validation_failed"
                        return

                    if not validation.has_all_requested_content:
                        state.view = "validation_warning"
                        return

                    # All good - start download immediately
                    await self._confirm_and_download(state)
                    return Navigation(next_screen="downloads")

                except Exception as e:
                    logger.error(f"Validation error: {e}")
                    state.view = "validation_error"
                    state.error = str(e)
                    return

        except Exception as e:
            logger.error(f"Error in download flow: {e}")
            await query.answer("Failed to start download", show_alert=True)

        return None

    async def _confirm_and_download(self, state: TorrentScreenState) -> None:
        """Confirm and start download with validation result.

        Args:
            state: Torrent screen state
        """
        result = state.pending_download
        validation = state.validation_result

        if not result or not validation or not state.imdb_metadata:
            logger.error("Missing data for download confirmation")
            return

        # Call downloader with validation result
        await self.downloader.add_download(
            result.title,
            result,
            validation,
        )

        logger.info(f"Started download: {result.title}")

    async def _render_validation_warning(self, context: Context) -> ScreenRenderResult:
        """Render validation warning view."""
        state = self._get_state(context)
        validation = state.validation_result

        if not validation:
            text = "⚠️ *Validation Warning*\n\nNo validation data available."
            keyboard = [[InlineKeyboardButton("« Back", callback_data=TORRENT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        text = "⚠️ *Content Mismatch*\n\n"
        text += "The torrent does not contain all requested content.\n\n"

        # Show what was found
        text += f"*Found:* {len(validation.matched_files)} file(s)\n"

        # Show missing content
        if validation.missing_content:
            text += "*Missing:*\n"
            for missing in validation.missing_content[:10]:  # Limit to 10
                text += f"  • {missing}\n"
            if len(validation.missing_content) > 10:
                text += f"  • ... and {len(validation.missing_content) - 10} more\n"
            text += "\n"

        # Show warnings
        if validation.warnings:
            text += "*Warnings:*\n"
            for warning in validation.warnings[:3]:  # Limit to 3
                text += f"  • {warning}\n"
            text += "\n"

        text += "Do you want to download anyway?"

        keyboard = [
            [
                InlineKeyboardButton("✅ Download Anyway", callback_data=TORRENT_DOWNLOAD_CONFIRM),
                InlineKeyboardButton("❌ Cancel", callback_data=TORRENT_DOWNLOAD_CANCEL),
            ]
        ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_validation_failed(self, context: Context) -> ScreenRenderResult:
        """Render validation failed view."""
        state = self._get_state(context)
        validation = state.validation_result

        text = "❌ *Validation Failed*\n\n"

        if validation:
            text += "This torrent does not contain the requested content.\n\n"

            if validation.warnings:
                text += "*Reasons:*\n"
                for warning in validation.warnings:
                    text += f"  • {warning}\n"
        else:
            text += "Could not validate torrent content.\n"

        text += "\nPlease try a different torrent."

        keyboard = [[InlineKeyboardButton("« Back to Results", callback_data=TORRENT_BACK)]]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_validation_error(self, context: Context) -> ScreenRenderResult:
        """Render validation error view."""
        state = self._get_state(context)

        text = "⚠️ *Validation Error*\n\n"
        text += "An error occurred while validating the torrent:\n\n"

        if state.error:
            text += f"`{state.error}`\n\n"

        text += "Please try again or select a different torrent."

        keyboard = [[InlineKeyboardButton("« Back to Results", callback_data=TORRENT_BACK)]]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()
