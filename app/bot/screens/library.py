"""Library screen for browsing media entities (movies and series)."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    LIBRARY_CLEAR_FILTER,
    LIBRARY_DELETE_ENTITY,
    LIBRARY_DOWNLOAD_EPISODE,
    LIBRARY_MAIN,
    LIBRARY_MOVIES,
    LIBRARY_MOVIES_NEXT,
    LIBRARY_MOVIES_PREV,
    LIBRARY_PLAY_FILE,
    LIBRARY_SCAN,
    LIBRARY_SEARCH,
    LIBRARY_SELECT_FILE,
    LIBRARY_VIEW_ENTITY,
    LIBRARY_VIEW_EPISODE,
    LIBRARY_VIEW_SEASON_EPISODES,
    LIBRARY_VIEW_SERIES_SEASONS,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.models import MediaType

logger = logging.getLogger(__name__)


class LibraryScreen(Screen):
    """Screen for browsing media library."""

    def __init__(self, library_manager, player):
        """Initialize library screen.

        Args:
            library_manager: Library manager instance
            player: Player controller instance
        """
        self.library = library_manager
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "library"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the library screen based on current view."""
        view = context.get_context().get("view", "main")

        if view == "main":
            return await self._render_main(context)
        elif view == "list":
            return await self._render_list(context)
        elif view == "entity_detail":
            return await self._render_entity_detail(context)
        elif view == "file_selection":
            return await self._render_file_selection(context)
        elif view == "series_seasons":
            return await self._render_series_seasons(context)
        elif view == "season_episodes":
            return await self._render_season_episodes(context)
        elif view == "episode_detail":
            return await self._render_episode_detail(context)

    async def _render_main(self, context: Context) -> ScreenRenderResult:
        """Render main library view."""
        movies = await self.library.get_all_media_entities(MediaType.MOVIE)
        series = await self.library.get_all_media_entities(MediaType.SERIES)

        text = "📚 *My Library*\n\n"

        # Show scan result if present
        if context.get_context().get("scan_result"):
            text += f"{context.get_context().get('scan_result')}\n\n"

        total_items = len(movies) + len(series)

        if total_items == 0:
            text += "Your library is empty.\nSearch and download content to get started!"
            keyboard = [
                [InlineKeyboardButton("🔍 Search Content", callback_data=LIBRARY_SEARCH)],
                [InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)],
                [InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)],
            ]
        else:
            text += f"You have *{len(movies)}* movies and *{len(series)}* series.\n\n"
            text += "Select an option to continue:"

            keyboard = []
            if movies:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"🎬 Browse Movies ({len(movies)})", callback_data=LIBRARY_MOVIES
                        )
                    ]
                )
            if series:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📺 Browse Series ({len(series)})",
                            callback_data=LIBRARY_VIEW_SERIES_SEASONS,
                        )
                    ]
                )
            keyboard.append([InlineKeyboardButton("🔄 Scan Library", callback_data=LIBRARY_SCAN)])
            keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_list(self, context: Context) -> ScreenRenderResult:
        """Render paginated entity list with filtering."""
        all_entities = await self.library.get_all_media_entities(MediaType.MOVIE)
        page = context.get_context().get("page", 0)
        filter_query = context.get_context().get("filter_query", "")
        items_per_page = 8

        # Apply filter if active
        if filter_query:
            entities = await self._filter_entities(all_entities, filter_query)
            text = f"🎬 *Movies* - Filtered by: '{filter_query}'\n\n"
            text += f"Found {len(entities)} matching movies\n\n"
        else:
            entities = all_entities
            text = f"🎬 *Movies* ({len(entities)} total)\n\n"
            text += "💡 _Send a message to filter movies_\n\n"

        if not entities:
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
        total_pages = (len(entities) - 1) // items_per_page + 1
        start_idx = page * items_per_page
        end_idx = min(start_idx + items_per_page, len(entities))
        page_entities = entities[start_idx:end_idx]

        text += f"Page {page + 1}/{total_pages}\n\n"
        text += "Select a movie to view details:"

        keyboard = []

        # Entity buttons
        for entity in page_entities:
            button_text = f"{entity.title}"
            if entity.year:
                button_text += f" ({entity.year})"

            if entity.rating:
                button_text += f" ⭐{entity.rating:.1f}"

            button_text = button_text[:60]  # Truncate

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{LIBRARY_VIEW_ENTITY}{entity.id}"
                    )
                ]
            )

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("« Previous", callback_data=LIBRARY_MOVIES_PREV)
            )
        if end_idx < len(entities):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_MOVIES_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Clear filter button
        if filter_query:
            keyboard.append(
                [InlineKeyboardButton("❌ Clear Filter", callback_data=LIBRARY_CLEAR_FILTER)]
            )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_entity_detail(self, context: Context) -> ScreenRenderResult:
        """Render entity detail view."""
        entity_id = context.get_context().get("selected_entity_id")

        if not entity_id:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        entity = await self.library.get_media_entity_by_id(entity_id)

        if not entity:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        # Build entity information
        text = f"🎬 *{entity.title}*"
        if entity.year:
            text += f" ({entity.year})"
        text += "\n\n"

        # Rating
        if entity.rating:
            stars = "⭐" * int(entity.rating / 2)
            text += f"{stars} *{entity.rating:.1f}/10*\n\n"

        # Genres
        if entity.genres:
            genres_text = ", ".join(
                [
                    g.value.capitalize() if hasattr(g, "value") else str(g).capitalize()
                    for g in entity.genres
                ]
            )
            text += f"🎭 *Genres:* {genres_text}\n\n"

        # Director (for movies)
        if entity.media_type == MediaType.MOVIE and entity.director:
            text += f"🎬 *Director:* {entity.director}\n\n"

        # Cast (for movies)
        if entity.media_type == MediaType.MOVIE and entity.cast:
            cast_text = ", ".join(entity.cast[:3])
            text += f"⭐ *Cast:* {cast_text}\n\n"

        # Description
        if entity.description:
            plot = entity.description
            if len(plot) > 300:
                plot = plot[:297] + "..."
            text += f"📖 *Plot:*\n{plot}\n\n"

        # Files info
        if entity.downloaded_files:
            text += f"📁 *Files:* {len(entity.downloaded_files)} downloaded file(s)\n"

        # Build keyboard
        keyboard = []

        if entity.media_type == MediaType.MOVIE:
            # Movie: show file selection if multiple files, or play directly
            if len(entity.downloaded_files) > 1:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "📁 Select File", callback_data=f"{LIBRARY_SELECT_FILE}{entity.id}"
                        )
                    ]
                )
            elif len(entity.downloaded_files) == 1:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "▶️ Play",
                            callback_data=f"{LIBRARY_PLAY_FILE}{entity.downloaded_files[0].id}",
                        )
                    ]
                )

        elif entity.media_type == MediaType.SERIES:
            # Series: show seasons
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📺 View Seasons", callback_data=f"{LIBRARY_VIEW_SERIES_SEASONS}{entity.id}"
                    )
                ]
            )

        keyboard.append(
            [InlineKeyboardButton("🗑️ Delete", callback_data=f"{LIBRARY_DELETE_ENTITY}{entity.id}")]
        )
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        poster_url = entity.poster_url if entity.poster_url else None

        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=poster_url)

    async def _render_file_selection(self, context: Context) -> ScreenRenderResult:
        """Render file selection view for entity with multiple files."""
        entity_id = context.get_context().get("selected_entity_id")

        if not entity_id:
            context.update_context(view="list", page=0)
            return await self._render_list(context)

        entity = await self.library.get_media_entity_by_id(entity_id)

        if not entity or not entity.downloaded_files:
            context.update_context(view="entity_detail", selected_entity_id=entity_id)
            return await self._render_entity_detail(context)

        text = "📁 *Select File*\n\n"
        text += f"*{entity.title}*\n\n"
        text += "Select a file to play:\n\n"

        keyboard = []

        for file in entity.downloaded_files:
            file_info = f"{file.quality.value if hasattr(file.quality, 'value') else file.quality}"
            if file.file_size:
                size_gb = file.file_size / (1024**3)
                file_info += f" ({size_gb:.2f} GB)"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"▶️ {file_info}", callback_data=f"{LIBRARY_PLAY_FILE}{file.id}"
                    )
                ]
            )

        keyboard.append(
            [InlineKeyboardButton("« Back", callback_data=f"{LIBRARY_VIEW_ENTITY}{entity_id}")]
        )

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_series_seasons(self, context: Context) -> ScreenRenderResult:
        """Render series seasons list."""
        series_id = context.get_context().get("selected_series_id")

        if not series_id:
            context.update_context(view="main")
            return await self._render_main(context)

        series = await self.library.get_media_entity_by_id(series_id)

        if not series or series.media_type != MediaType.SERIES:
            context.update_context(view="main")
            return await self._render_main(context)

        seasons = await self.library.get_series_seasons(series_id)

        text = f"📺 *{series.title}*\n\n"
        text += "*Seasons*\n\n"

        if not seasons:
            text += "No seasons available.\n"

        keyboard = []

        for season in seasons:
            season_num = season.season_number or 0
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Season {season_num}",
                        callback_data=f"{LIBRARY_VIEW_SEASON_EPISODES}{season.id}",
                    )
                ]
            )

        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_MAIN)])

        poster_url = series.poster_url if series.poster_url else None

        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=poster_url)

    async def _render_season_episodes(self, context: Context) -> ScreenRenderResult:
        """Render season episodes list."""
        season_id = context.get_context().get("selected_season_id")

        if not season_id:
            context.update_context(view="main")
            return await self._render_main(context)

        season = await self.library.get_media_entity_by_id(season_id)

        if not season or season.media_type != MediaType.SEASON:
            context.update_context(view="main")
            return await self._render_main(context)

        episodes = await self.library.get_season_episodes(season_id)

        text = f"📺 *{season.title}*\n\n"
        text += "*Episodes*\n\n"

        if not episodes:
            text += "No episodes available.\n"

        keyboard = []

        for episode in episodes:
            ep_num = episode.episode_number or 0
            ep_title = episode.episode_title or episode.title
            button_text = f"E{ep_num:02d}: {ep_title[:40]}"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{LIBRARY_VIEW_EPISODE}{episode.id}"
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "« Back to Seasons",
                    callback_data=f"{LIBRARY_VIEW_SERIES_SEASONS}{season.series_id}",
                )
            ]
        )

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_episode_detail(self, context: Context) -> ScreenRenderResult:
        """Render episode detail view."""
        episode_id = context.get_context().get("selected_episode_id")

        if not episode_id:
            context.update_context(view="main")
            return await self._render_main(context)

        episode = await self.library.get_media_entity_by_id(episode_id)

        if not episode or episode.media_type != MediaType.EPISODE:
            context.update_context(view="main")
            return await self._render_main(context)

        text = f"📺 *{episode.title}*\n\n"

        if episode.episode_title:
            text += f"*{episode.episode_title}*\n\n"

        if episode.description:
            plot = episode.description
            if len(plot) > 300:
                plot = plot[:297] + "..."
            text += f"📖 *Plot:*\n{plot}\n\n"

        if episode.air_date:
            text += f"📅 *Air Date:* {episode.air_date.strftime('%Y-%m-%d')}\n\n"

        if episode.downloaded_files:
            text += f"📁 *Files:* {len(episode.downloaded_files)} downloaded file(s)\n"

        keyboard = []

        # File selection or play
        if len(episode.downloaded_files) > 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📁 Select File", callback_data=f"{LIBRARY_SELECT_FILE}{episode.id}"
                    )
                ]
            )
        elif len(episode.downloaded_files) == 1:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "▶️ Play",
                        callback_data=f"{LIBRARY_PLAY_FILE}{episode.downloaded_files[0].id}",
                    )
                ]
            )

        # Download options
        keyboard.append(
            [
                InlineKeyboardButton(
                    "⬇️ Download Episode", callback_data=f"{LIBRARY_DOWNLOAD_EPISODE}{episode.id}"
                )
            ]
        )

        if episode.season_id:
            season = await self.library.get_media_entity_by_id(episode.season_id)
            if season:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "« Back to Episodes",
                            callback_data=f"{LIBRARY_VIEW_SEASON_EPISODES}{season.id}",
                        )
                    ]
                )

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _filter_entities(self, entities, query: str):
        """Filter entities by query."""
        query_lower = query.lower()
        filtered = []

        for entity in entities:
            if query_lower in entity.title.lower():
                filtered.append(entity)
                continue

            if entity.description and query_lower in entity.description.lower():
                filtered.append(entity)
                continue

            if entity.genres:
                genres_text = " ".join(
                    [g.value if hasattr(g, "value") else str(g) for g in entity.genres]
                ).lower()
                if query_lower in genres_text:
                    filtered.append(entity)

        return filtered

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
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

        elif query.data.startswith(LIBRARY_VIEW_ENTITY):
            entity_id = query.data[len(LIBRARY_VIEW_ENTITY) :]
            context.update_context(view="entity_detail", selected_entity_id=entity_id)

        elif query.data.startswith(LIBRARY_SELECT_FILE):
            entity_id = query.data[len(LIBRARY_SELECT_FILE) :]
            context.update_context(view="file_selection", selected_entity_id=entity_id)

        elif query.data.startswith(LIBRARY_PLAY_FILE):
            file_id = query.data[len(LIBRARY_PLAY_FILE) :]
            return await self._play_file(query, file_id)

        elif query.data.startswith(LIBRARY_VIEW_SERIES_SEASONS):
            series_id = query.data[len(LIBRARY_VIEW_SERIES_SEASONS) :]
            context.update_context(view="series_seasons", selected_series_id=series_id)

        elif query.data.startswith(LIBRARY_VIEW_SEASON_EPISODES):
            season_id = query.data[len(LIBRARY_VIEW_SEASON_EPISODES) :]
            context.update_context(view="season_episodes", selected_season_id=season_id)

        elif query.data.startswith(LIBRARY_VIEW_EPISODE):
            episode_id = query.data[len(LIBRARY_VIEW_EPISODE) :]
            context.update_context(view="episode_detail", selected_episode_id=episode_id)

        elif query.data.startswith(LIBRARY_DOWNLOAD_EPISODE):
            episode_id = query.data[len(LIBRARY_DOWNLOAD_EPISODE) :]
            await query.answer("Download feature coming soon", show_alert=True)

        elif query.data.startswith(LIBRARY_DELETE_ENTITY):
            entity_id = query.data[len(LIBRARY_DELETE_ENTITY) :]
            await query.answer("Delete feature coming soon", show_alert=True)

    async def handle_message(
        self,
        message: Message,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle text messages for filtering."""
        view = context.get_context().get("view", "main")
        if view != "list":
            return None

        query_text = message.text.strip()
        if not query_text:
            return None

        context.update_context(filter_query=query_text, page=0, view="list")
        return None

    async def _scan_library(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> None:
        """Scan library."""
        try:
            await query.answer("Scanning library...")
            movies_count, series_count = await self.library.scan_library()
            context.update_context(
                scan_result=f"✅ Scanned: {movies_count} movies, {series_count} series"
            )
        except Exception as e:
            logger.error(f"Error scanning library: {e}")
            await query.answer("Error scanning library", show_alert=True)

    async def _play_file(
        self,
        query: CallbackQuery,
        file_id: str,
    ) -> ScreenHandlerResult:
        """Play a downloaded file."""
        try:
            # Find file by ID
            all_entities = await self.library.get_all_media_entities()
            file_path = None
            file_title = "Unknown"

            for entity in all_entities:
                for downloaded_file in entity.downloaded_files:
                    if downloaded_file.id == file_id:
                        file_path = downloaded_file.file_path
                        file_title = entity.title
                        break
                if file_path:
                    break

            if not file_path or not file_path.exists():
                await query.answer("File not found", show_alert=True)
                return

            await query.answer(f"Playing: {file_title}")

            success = await self.player.play(file_path)

            if success:
                return Navigation("player")
            else:
                await query.answer(f"Failed to play: {file_title}", show_alert=True)

        except Exception as e:
            logger.error(f"Error playing file: {e}")
            await query.answer("Error playing file", show_alert=True)
