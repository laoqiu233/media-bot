"""Library screen for browsing movies and series."""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class LibraryScreen(Screen):
    """Screen for browsing the media library."""

    def __init__(self, screen_manager, library_manager, player):
        """Initialize library screen.

        Args:
            screen_manager: Screen manager instance
            library_manager: Library manager
            player: MPV player controller
        """
        super().__init__(screen_manager)
        self.library = library_manager
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "library"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the library screen.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        state = state or {}
        view = state.get("view", "main")  # main, movies, series, movie_detail, series_detail

        if view == "main":
            return await self._render_main(chat_id, state)
        elif view == "movies":
            return await self._render_movies(chat_id, state)
        elif view == "series":
            return await self._render_series(chat_id, state)
        elif view == "movie_detail":
            return await self._render_movie_detail(chat_id, state)
        elif view == "series_detail":
            return await self._render_series_detail(chat_id, state)
        
        # Default to main
        return await self._render_main(chat_id, state)

    async def _render_main(
        self, chat_id: int, state: Dict[str, Any]
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render main library view.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            movies = await self.library.get_all_movies()
            series = await self.library.get_all_series()

            text = "📚 *My Library*\n\n"
            
            if not movies and not series:
                text += "Your library is empty.\nSearch and download content to get started!"
                keyboard = [
                    [InlineKeyboardButton("🔍 Search Content", callback_data="library:search:")],
                    [InlineKeyboardButton("🔄 Scan Library", callback_data="library:scan:")],
                    [InlineKeyboardButton("« Back to Menu", callback_data="library:back:")],
                ]
            else:
                text += f"You have:\n"
                text += f"🎬 Movies: {len(movies)}\n"
                text += f"📺 Series: {len(series)}\n\n"
                text += "Select a category to browse:"

                keyboard = []
                if movies:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🎬 Movies ({len(movies)})",
                            callback_data="library:movies:"
                        )
                    ])
                if series:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"📺 Series ({len(series)})",
                            callback_data="library:series:"
                        )
                    ])
                
                keyboard.append([
                    InlineKeyboardButton("🔄 Scan Library", callback_data="library:scan:")
                ])
                keyboard.append([
                    InlineKeyboardButton("« Back to Menu", callback_data="library:back:")
                ])

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering library main: {e}")
            text = "📚 *My Library*\n\nError loading library. Please try again."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="library:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

    async def _render_movies(
        self, chat_id: int, state: Dict[str, Any]
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render movies list.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            movies = await self.library.get_all_movies()
            page = state.get("page", 0)
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
                
                keyboard.append([
                    InlineKeyboardButton(
                        button_text,
                        callback_data=f"library:play_movie:{movie.id}"
                    )
                ])

            # Navigation
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton("« Previous", callback_data="library:movies_prev:")
                )
            if end_idx < len(movies):
                nav_buttons.append(
                    InlineKeyboardButton("Next »", callback_data="library:movies_next:")
                )
            
            if nav_buttons:
                keyboard.append(nav_buttons)

            # Back button
            keyboard.append([
                InlineKeyboardButton("« Back to Library", callback_data="library:main:")
            ])

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering movies: {e}")
            text = "Error loading movies."
            keyboard = [[InlineKeyboardButton("« Back", callback_data="library:main:")]]
            return text, InlineKeyboardMarkup(keyboard)

    async def _render_series(
        self, chat_id: int, state: Dict[str, Any]
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render series list.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        try:
            series_list = await self.library.get_all_series()
            page = state.get("page", 0)
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
                
                keyboard.append([
                    InlineKeyboardButton(
                        button_text,
                        callback_data=f"library:view_series:{series.id}"
                    )
                ])

            # Navigation
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton("« Previous", callback_data="library:series_prev:")
                )
            if end_idx < len(series_list):
                nav_buttons.append(
                    InlineKeyboardButton("Next »", callback_data="library:series_next:")
                )
            
            if nav_buttons:
                keyboard.append(nav_buttons)

            # Back button
            keyboard.append([
                InlineKeyboardButton("« Back to Library", callback_data="library:main:")
            ])

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering series: {e}")
            text = "Error loading series."
            keyboard = [[InlineKeyboardButton("« Back", callback_data="library:main:")]]
            return text, InlineKeyboardMarkup(keyboard)

    async def _render_movie_detail(
        self, chat_id: int, state: Dict[str, Any]
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render movie detail view (not used in simple version).

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        # For simplicity, we just play directly
        return await self._render_movies(chat_id, state)

    async def _render_series_detail(
        self, chat_id: int, state: Dict[str, Any]
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render series detail view (not used in simple version).

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
        # For simplicity, we just show list
        return await self._render_series(chat_id, state)

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle library screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters
        """
        chat_id = update.callback_query.message.chat_id
        state = self.get_state(chat_id)

        if action == "back":
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

        elif action == "search":
            await self.navigate_to(chat_id, "search")

        elif action == "main":
            state["view"] = "main"
            state["page"] = 0
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "movies":
            state["view"] = "movies"
            state["page"] = 0
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "series":
            state["view"] = "series"
            state["page"] = 0
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "movies_prev":
            page = state.get("page", 0)
            state["page"] = max(0, page - 1)
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "movies_next":
            page = state.get("page", 0)
            state["page"] = page + 1
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "series_prev":
            page = state.get("page", 0)
            state["page"] = max(0, page - 1)
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "series_next":
            page = state.get("page", 0)
            state["page"] = page + 1
            self.set_state(chat_id, state)
            await self.refresh(chat_id)

        elif action == "scan":
            await self._scan_library(update, context, chat_id)

        elif action == "play_movie":
            await self._play_movie(update, context, chat_id, params)

        elif action == "view_series":
            await update.callback_query.answer(
                "Series browsing coming soon!",
                show_alert=True
            )

    async def _scan_library(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """Scan the library for new content.

        Args:
            update: Telegram update
            context: Bot context
            chat_id: Chat ID
        """
        try:
            await update.callback_query.answer("Scanning library...")
            
            movies_count, series_count = await self.library.scan_library()
            
            await update.callback_query.answer(
                f"✅ Library scanned!\nMovies: {movies_count}\nSeries: {series_count}",
                show_alert=True
            )
            
            # Refresh view
            await self.refresh(chat_id)

        except Exception as e:
            logger.error(f"Error scanning library: {e}")
            await update.callback_query.answer(
                "Error scanning library",
                show_alert=True
            )

    async def _play_movie(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        movie_id: str,
    ) -> None:
        """Play a movie.

        Args:
            update: Telegram update
            context: Bot context
            chat_id: Chat ID
            movie_id: Movie ID
        """
        try:
            movie = await self.library.get_movie(movie_id)
            
            if not movie or not movie.file_path:
                await update.callback_query.answer(
                    "Movie file not found",
                    show_alert=True
                )
                return

            file_path = Path(movie.file_path) if isinstance(movie.file_path, str) else movie.file_path
            
            if not file_path.exists():
                await update.callback_query.answer(
                    f"File not found: {movie.title}",
                    show_alert=True
                )
                logger.error(f"Movie file does not exist: {file_path}")
                return

            await update.callback_query.answer(f"Playing: {movie.title}")
            
            success = await self.player.play(file_path)

            if success:
                # Navigate to player screen
                await self.navigate_to(chat_id, "player")
            else:
                await update.callback_query.answer(
                    f"Failed to play: {movie.title}",
                    show_alert=True
                )

        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            await update.callback_query.answer(
                "Error playing movie",
                show_alert=True
            )

