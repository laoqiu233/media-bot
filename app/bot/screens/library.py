"""Library screen for browsing movies and series."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    LIBRARY_MAIN,
    LIBRARY_MOVIES,
    LIBRARY_MOVIES_NEXT,
    LIBRARY_MOVIES_PREV,
    LIBRARY_PLAY_MOVIE,
    LIBRARY_SCAN,
    LIBRARY_SEARCH,
    LIBRARY_SERIES,
    LIBRARY_SERIES_NEXT,
    LIBRARY_SERIES_PREV,
    LIBRARY_VIEW_SERIES,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class LibraryScreen(Screen):
    def __init__(self, library_manager, player):
        self.library = library_manager
        self.player = player

    def get_name(self) -> str:
        return "library"

    async def render(self, context: Context) -> ScreenRenderResult:
        view = context.get_context().get("view", "main")  # main, movies, series

        if view == "main":
            return await self._render_main(context)
        elif view == "movies":
            return await self._render_movies(context)
        elif view == "series":
            return await self._render_series(context)

    async def _render_main(self, context: Context) -> ScreenRenderResult:
        movies = await self.library.get_all_movies()
        series = await self.library.get_all_series()

        text = "📚 *My Library*\n\n"

        # Show scan result if present
        if context.get_context().get("scan_result"):
            text += f"{context.get_context().get('scan_result')}\n\n"

        if not movies and not series:
            text += "Your library is empty.\nSearch and download content to get started!"
            keyboard = [
                [InlineKeyboardButton("🔍 Search Content", callback_data=LIBRARY_SEARCH)],
                [InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)],
                [InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)],
            ]
        else:
            text += "You have:\n"
            text += f"🎬 Movies: {len(movies)}\n"
            text += f"📺 Series: {len(series)}\n\n"
            text += "Select a category to browse:"

            keyboard = []
            if movies:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"🎬 Movies ({len(movies)})", callback_data=LIBRARY_MOVIES
                        )
                    ]
                )
            if series:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📺 Series ({len(series)})", callback_data=LIBRARY_SERIES
                        )
                    ]
                )

            keyboard.append([InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)])
            keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard)

    async def _render_movies(self, context: Context) -> ScreenRenderResult:
        movies = await self.library.get_all_movies()
        page = context.get_context().get("page", 0)
        items_per_page = 8

        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_movies = movies[start_idx:end_idx]

        text = f"🎬 *Movies* ({len(movies)} total)\n\n"
        text += f"Page {page + 1}/{(len(movies) - 1) // items_per_page + 1}\n\n"
        text += "Select a movie to play:"

        keyboard = []

        # Movie buttons
        for movie in page_movies:
            title = movie.title
            year = f" ({movie.year})" if movie.year else ""
            button_text = f"{title}{year}"[:60]

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{LIBRARY_PLAY_MOVIE}{movie.id}")]
            )

        # Navigation
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("« Previous", callback_data=LIBRARY_MOVIES_PREV)
            )
        if end_idx < len(movies):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_MOVIES_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard)

    async def _render_series(self, context: Context) -> ScreenRenderResult:
        series_list = await self.library.get_all_series()
        page = context.get_context("page", 0)
        items_per_page = 8

        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_series = series_list[start_idx:end_idx]

        text = f"📺 *Series* ({len(series_list)} total)\n\n"
        text += f"Page {page + 1}/{(len(series_list) - 1) // items_per_page + 1}\n\n"
        text += "Select a series to browse:"

        keyboard = []

        # Series buttons
        for series in page_series:
            title = series.title
            year = f" ({series.year})" if series.year else ""
            button_text = f"{title}{year}"[:60]

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{LIBRARY_VIEW_SERIES}{series.id}"
                    )
                ]
            )

        # Navigation
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("« Previous", callback_data=LIBRARY_SERIES_PREV)
            )
        if end_idx < len(series_list):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_SERIES_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard)

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == LIBRARY_SEARCH:
            return Navigation("search")

        elif query.data == LIBRARY_MAIN:
            return Navigation("main_menu")

        elif query.data == LIBRARY_MOVIES:
            context.update_context(view="movies", page=0)

        elif query.data == LIBRARY_SERIES:
            await query.answer("Series browsing coming soon!", show_alert=True)

        elif query.data == LIBRARY_MOVIES_PREV:
            page = context.get_context().get("page", 0)
            context.update_context(page=max(0, page - 1))

        elif query.data == LIBRARY_MOVIES_NEXT:
            page = context.get_context().get("page", 0)
            context.update_context(page=page + 1)

        elif query.data == LIBRARY_SERIES_PREV:
            page = context.get_context().get("page", 0)
            context.update_context(page=max(0, page - 1))

        elif query.data == LIBRARY_SERIES_NEXT:
            page = context.get_context().get("page", 0)
            context.update_context(page=page + 1)

        elif query.data == LIBRARY_SCAN:
            await self._scan_library(query, context)

        elif query.data.startswith(LIBRARY_PLAY_MOVIE):
            movie_id = query.data[len(LIBRARY_PLAY_MOVIE) :]
            await self._play_movie(query, movie_id)

    async def _scan_library(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> None:
        try:
            # Show scanning status in the callback (no alert popup)
            await query.answer("Scanning library...")

            # Perform the scan
            movies_count, series_count = await self.library.scan_library()

            # Update state with scan result (screen_manager will auto-refresh)
            context.update_context(
                scan_result=f"✅ Scanned: {movies_count} movies, {series_count} series"
            )

        except Exception as e:
            logger.error(f"Error scanning library: {e}")
            # Show error in callback answer
            await query.answer("Error scanning library", show_alert=True)

    async def _play_movie(
        self,
        query: CallbackQuery,
        movie_id: str,
    ) -> ScreenHandlerResult:
        try:
            movie = await self.library.get_movie(movie_id)

            if not movie or not movie.file_path:
                await query.answer("Movie file not found", show_alert=True)
                return

            file_path = (
                Path(movie.file_path) if isinstance(movie.file_path, str) else movie.file_path
            )

            if not file_path.exists():
                await query.answer(f"File not found: {movie.title}", show_alert=True)
                logger.error(f"Movie file does not exist: {file_path}")
                return

            await query.answer(f"Playing: {movie.title}")

            success = await self.player.play(file_path)

            if success:
                # Navigate to player screen
                return Navigation("player")
            else:
                await query.answer(f"Failed to play: {movie.title}", show_alert=True)

        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            await query.answer("Error playing movie", show_alert=True)
