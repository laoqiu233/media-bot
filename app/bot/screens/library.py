"""Library screen for browsing movies."""

import logging
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    LIBRARY_CLEAR_FILTER,
    LIBRARY_CONFIRM_DELETE,
    LIBRARY_DELETE_MOVIE,
    LIBRARY_MAIN,
    LIBRARY_MOVIES,
    LIBRARY_MOVIES_NEXT,
    LIBRARY_MOVIES_PREV,
    LIBRARY_PLAY_MOVIE,
    LIBRARY_SCAN,
    LIBRARY_SEARCH,
    LIBRARY_VIEW_MOVIE,
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


class LibraryScreen(Screen):
    def __init__(self, library_manager, player):
        self.library = library_manager
        self.player = player

    def get_name(self) -> str:
        return "library"

    async def render(self, context: Context) -> ScreenRenderResult:
        view = context.get_context().get("view", "main")  # main, list, detail, delete_confirm

        if view == "main":
            return await self._render_main(context)
        elif view == "list":
            return await self._render_list(context)
        elif view == "detail":
            return await self._render_detail(context)
        elif view == "delete_confirm":
            return await self._render_delete_confirm(context)

    async def _render_main(self, context: Context) -> ScreenRenderResult:
        movies = await self.library.get_all_movies()

        text = "📚 *My Library*\n\n"

        # Show scan result if present
        if context.get_context().get("scan_result"):
            text += f"{context.get_context().get('scan_result')}\n\n"

        if not movies:
            text += "Your library is empty.\nSearch and download content to get started!"
            keyboard = [
                [InlineKeyboardButton("🔍 Search Content", callback_data=LIBRARY_SEARCH)],
                [InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)],
                [InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)],
            ]
        else:
            text += f"You have *{len(movies)}* movies in your library.\n\n"
            text += "Select an option to continue:"

            keyboard = [
                [
                    InlineKeyboardButton(
                        f"🎬 Browse Movies ({len(movies)})", callback_data=LIBRARY_MOVIES
                    )
                ],
                [InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)],
                [InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)],
            ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_list(self, context: Context) -> ScreenRenderResult:
        """Render paginated movie list with filtering."""
        all_movies = await self.library.get_all_movies()
        page = context.get_context().get("page", 0)
        filter_query = context.get_context().get("filter_query", "")
        items_per_page = 8

        # Apply filter if active
        if filter_query:
            movies = await self._filter_movies(all_movies, filter_query)
            text = f"🎬 *Movies* - Filtered by: '{filter_query}'\n\n"
            text += f"Found {len(movies)} matching movies\n\n"
        else:
            movies = all_movies
            text = f"🎬 *Movies* ({len(movies)} total)\n\n"
            text += "💡 _Send a message to filter movies_\n\n"

        if not movies:
            if filter_query:
                text += "No movies match your filter.\n\nTry a different search term."
            else:
                text += "Your library is empty."

            keyboard = []
            if filter_query:
                keyboard.append(
                    [InlineKeyboardButton("❌ Clear Filter", callback_data=LIBRARY_CLEAR_FILTER)]
                )
            keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Paginate
        total_pages = (len(movies) - 1) // items_per_page + 1
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(movies))
        page_movies = movies[start_idx:end_idx]

        text += f"Page {page + 1}/{total_pages}\n\n"
        text += "Select a movie to view details:"

        keyboard = []

        # Movie buttons - show short info
        for movie in page_movies:
            # Build button text with short info
            button_text = f"{movie.title}"
            if movie.year:
                button_text += f" ({movie.year})"

            # Add IMDb rating if available
            if hasattr(movie, "rating") and movie.rating:
                button_text += f" ⭐{movie.rating:.1f}"

            button_text = button_text[:60]  # Truncate if too long

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{LIBRARY_VIEW_MOVIE}{movie.id}")]
            )

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("« Previous", callback_data=LIBRARY_MOVIES_PREV)
            )
        if end_idx < len(movies):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_MOVIES_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Clear filter button (only show when filter is active)
        if filter_query:
            keyboard.append(
                [InlineKeyboardButton("❌ Clear Filter", callback_data=LIBRARY_CLEAR_FILTER)]
            )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_detail(self, context: Context) -> ScreenRenderResult:
        """Render detailed movie view with poster."""
        movie_id = context.get_context().get("selected_movie_id")

        if not movie_id:
            # Fallback to list view
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        movie = await self.library.get_movie(movie_id)

        if not movie:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        # Build detailed movie information
        text = f"🎬 *{movie.title}*"
        if movie.year:
            text += f" ({movie.year})"
        text += "\n\n"

        # IMDb Rating
        if hasattr(movie, "rating") and movie.rating:
            stars = "⭐" * int(movie.rating / 2)
            text += f"{stars} *{movie.rating:.1f}/10*\n\n"

        # Genres
        if movie.genres:
            genres_text = ", ".join(
                [
                    g.capitalize() if isinstance(g, str) else g.value.capitalize()
                    for g in movie.genres
                ]
            )
            text += f"🎭 *Genres:* {genres_text}\n\n"

        # Director
        if hasattr(movie, "director") and movie.director:
            text += f"🎬 *Director:* {movie.director}\n\n"

        # Cast
        if hasattr(movie, "cast") and movie.cast:
            cast_text = ", ".join(movie.cast[:3])  # Show top 3
            text += f"⭐ *Cast:* {cast_text}\n\n"

        # Description/Plot
        if movie.description:
            plot = movie.description
            # Limit plot length for readability
            if len(plot) > 300:
                plot = plot[:297] + "..."
            text += f"📖 *Plot:*\n{plot}\n\n"

        # File info
        if movie.quality:
            quality = movie.quality.value if hasattr(movie.quality, "value") else movie.quality
            text += f"📺 *Quality:* {quality}\n"

        if movie.file_size:
            size_gb = movie.file_size / (1024**3)
            text += f"💾 *Size:* {size_gb:.2f} GB\n"

        # Build keyboard with actions
        keyboard = [
            [InlineKeyboardButton("▶️ Play", callback_data=f"{LIBRARY_PLAY_MOVIE}{movie.id}")],
            [InlineKeyboardButton("🗑️ Delete", callback_data=f"{LIBRARY_DELETE_MOVIE}{movie.id}")],
            [InlineKeyboardButton("« Back to Movies", callback_data=LIBRARY_MOVIES)],
        ]

        # Get poster URL (direct HTTP URL)
        poster_url = movie.poster_url if movie.poster_url else None

        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=poster_url)

    async def _render_delete_confirm(self, context: Context) -> ScreenRenderResult:
        """Render delete confirmation dialog."""
        movie_id = context.get_context().get("selected_movie_id")

        if not movie_id:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        movie = await self.library.get_movie(movie_id)

        if not movie:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        text = "⚠️ *Delete Movie*\n\n"
        text += "Are you sure you want to delete:\n\n"
        text += f"*{movie.title}*"
        if movie.year:
            text += f" ({movie.year})"
        text += "\n\n"
        text += "⚠️ This will permanently delete the movie file and metadata."

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Yes, Delete", callback_data=f"{LIBRARY_CONFIRM_DELETE}{movie.id}"
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{LIBRARY_VIEW_MOVIE}{movie.id}")],
        ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _filter_movies(self, movies, query: str):
        """Filter movies by query in title, description, and genres."""
        query_lower = query.lower()
        filtered = []

        for movie in movies:
            # Check title
            if query_lower in movie.title.lower():
                filtered.append(movie)
                continue

            # Check description
            if movie.description and query_lower in movie.description.lower():
                filtered.append(movie)
                continue

            # Check genres
            if movie.genres:
                genres_text = " ".join(
                    [g.value if hasattr(g, "value") else str(g) for g in movie.genres]
                ).lower()
                if query_lower in genres_text:
                    filtered.append(movie)
                    continue

        return filtered

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
            context.update_context(view="list", page=0)

        elif query.data == LIBRARY_MOVIES_PREV:
            page = context.get_context().get("page", 0)
            context.update_context(page=max(0, page - 1))

        elif query.data == LIBRARY_MOVIES_NEXT:
            page = context.get_context().get("page", 0)
            context.update_context(page=page + 1)

        elif query.data == LIBRARY_CLEAR_FILTER:
            context.update_context(filter_query="", page=0, view="list")
            await query.answer("Filter cleared")

        elif query.data == LIBRARY_SCAN:
            await self._scan_library(query, context)

        elif query.data.startswith(LIBRARY_VIEW_MOVIE):
            movie_id = query.data[len(LIBRARY_VIEW_MOVIE) :]
            context.update_context(view="detail", selected_movie_id=movie_id)

        elif query.data.startswith(LIBRARY_PLAY_MOVIE):
            movie_id = query.data[len(LIBRARY_PLAY_MOVIE) :]
            return await self._play_movie(query, movie_id)

        elif query.data.startswith(LIBRARY_DELETE_MOVIE):
            movie_id = query.data[len(LIBRARY_DELETE_MOVIE) :]
            context.update_context(view="delete_confirm", selected_movie_id=movie_id)

        elif query.data.startswith(LIBRARY_CONFIRM_DELETE):
            movie_id = query.data[len(LIBRARY_CONFIRM_DELETE) :]
            await self._delete_movie(query, context, movie_id)

    async def handle_message(
        self,
        message: Message,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle text messages for filtering."""
        # Only handle messages when in list view
        view = context.get_context().get("view", "main")
        if view != "list":
            return None

        # Get the search query from the message
        query = message.text.strip()

        if not query:
            return None

        # Apply filter and reset to page 0
        context.update_context(filter_query=query, page=0, view="list")

        return None  # Stay on current screen, will re-render with filter

    async def _scan_library(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> None:
        try:
            await query.answer("Scanning library...")

            movies_count, series_count = await self.library.scan_library()

            context.update_context(scan_result=f"✅ Scanned: {movies_count} movies")

        except Exception as e:
            logger.error(f"Error scanning library: {e}")
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

    async def _delete_movie(
        self,
        query: CallbackQuery,
        context: Context,
        movie_id: str,
    ) -> None:
        try:
            movie = await self.library.get_movie(movie_id)

            if not movie:
                await query.answer("Movie not found", show_alert=True)
                context.update_context(view="list", page=0)
                return

            # Delete using library manager
            success = await self.library.delete_movie(movie_id)

            if success:
                await query.answer(f"Deleted: {movie.title}")
            else:
                await query.answer("Failed to delete movie", show_alert=True)

            # Return to list view
            context.update_context(view="list", page=0, selected_movie_id=None)

        except Exception as e:
            logger.error(f"Error deleting movie: {e}")
            await query.answer("Error deleting movie", show_alert=True)
