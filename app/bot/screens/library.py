"""Library screen for browsing downloaded movies and series."""

import logging
from dataclasses import dataclass, field

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callback_data import (
    LIBRARY_BACK,
    LIBRARY_CLEAR_FILTER,
    LIBRARY_DELETE,
    LIBRARY_DELETE_FILE,
    LIBRARY_TOGGLE_DELETE_FILES_MODE,
    LIBRARY_NEXT_PAGE,
    LIBRARY_PLAY,
    LIBRARY_PREV_PAGE,
    LIBRARY_RESCAN,
    LIBRARY_SELECT_ENTITY,
    LIBRARY_SHOW_MOVIES,
    LIBRARY_SHOW_SERIES,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.manager import LibraryManager
from app.library.models import MediaEntity, MediaType
from app.player.mpv_controller import MPVController

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5
LIBRARY_SCREEN_STATE = "library_screen_state"


@dataclass
class LibraryScreenState:
    """State of the library screen."""

    view: str = "main"
    movies_list: list[MediaEntity] = field(default_factory=list)
    series_list: list[MediaEntity] = field(default_factory=list)
    entity_list_page: int = 0
    entity_pages_list: list[int] = field(default_factory=list)
    filter_query: str = ""
    selected_entity: MediaEntity | None = None
    delete_files_mode: bool = False

class LibraryScreen(Screen):
    """Screen for browsing and managing library content."""

    def __init__(self, library_manager: LibraryManager, player: MPVController):
        """Initialize library screen.

        Args:
            library_manager: Library manager instance
            player: MPV player controller
        """
        self.library = library_manager
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "library"

    def _get_state(self, context: Context) -> LibraryScreenState:
        """Get the state from context."""
        return context.get(LIBRARY_SCREEN_STATE)

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen."""
        # Check if we're returning with a saved state (e.g., from player)
        saved_state = kwargs.get("library_state")
        
        if saved_state:
            # Restore the full library state
            context.update_context(**{LIBRARY_SCREEN_STATE: saved_state})
            return
        else:
            # Default initialization
            context.update_context(
                **{
                    LIBRARY_SCREEN_STATE: LibraryScreenState(
                        view="main",
                        movies_list=[],
                        series_list=[],
                        filter_query="",
                    )
                }
            )
            self._update_entities_in_state(context)

    def _update_entities_in_state(self, context: Context):
        state = self._get_state(context)
        state.movies_list = []

        all_entities = self.library.get_all_media_entities()

        movies = [e for e in all_entities if e.media_type == MediaType.MOVIE]
        series = [e for e in all_entities if e.media_type == MediaType.SERIES]

        # Sort by added_date (newest first)
        movies.sort(key=lambda x: x.added_date, reverse=True)
        series.sort(key=lambda x: x.added_date, reverse=True)

        state.movies_list = movies
        state.series_list = series

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the screen based on current view state."""
        state = self._get_state(context)

        if state.view == "main":
            return await self._render_main(context)
        elif state.selected_entity is not None:
            return await self._render_entity_detail(context)
        elif state.view == "movies":
            return await self._render_movies_list(context)
        elif state.view == "series":
            return await self._render_series_list(context)

        # Default fallback
        state.view = "main"
        return await self._render_main(context)

    async def _render_main(self, context: Context) -> ScreenRenderResult:
        """Render the main library view with Movies/Series buttons."""
        state = self._get_state(context)

        text = "📚 *Media Library*\n\n"
        text += "Choose a category to browse:\n\n"
        text += f"📽️ Movies: {len(state.movies_list)}\n"
        text += f"📺 Series: {len(state.series_list)}"

        keyboard = [
            [
                InlineKeyboardButton(
                    f"📽️ Movies ({len(state.movies_list)})", callback_data=LIBRARY_SHOW_MOVIES
                )
            ],
            [
                InlineKeyboardButton(
                    f"📺 Series ({len(state.series_list)})", callback_data=LIBRARY_SHOW_SERIES
                )
            ],
            [InlineKeyboardButton("🔄 Rescan Library", callback_data=LIBRARY_RESCAN)],
            [InlineKeyboardButton("« Back to Menu", callback_data=LIBRARY_BACK)],
        ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_movies_list(self, context: Context) -> ScreenRenderResult:
        """Render the movies list view."""
        state = self._get_state(context)
        return await self._render_entity_list(
            context,
            state.movies_list,
            "📽️ Movies",
        )

    async def _render_series_list(self, context: Context) -> ScreenRenderResult:
        """Render the series list view."""
        state = self._get_state(context)
        return await self._render_entity_list(
            context,
            state.series_list,
            "📺 Series",
        )

    async def _render_entity_list(
        self,
        context: Context,
        entities: list[MediaEntity],
        title: str,
    ) -> ScreenRenderResult:
        """Render a paginated list of entities with filtering.

        Args:
            context: Screen context
            entities: List of entities to display
            title: Title for the list
            select_callback_prefix: Callback prefix for selection buttons
        """
        state = self._get_state(context)

        # Filter entities
        filtered = self._get_filtered_entities(entities, state.filter_query)

        # Paginate
        start_idx = state.entity_list_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_entities = filtered[start_idx:end_idx]

        # Build text
        text = f"{title}\n\n"

        if state.filter_query:
            text += f"🔍 *Filter:* {state.filter_query}\n"
            text += f"Found {len(filtered)} result(s)\n\n"
        else:
            text += f"Total: {len(filtered)}\n"
            text += "_Type a query to filter..._\n\n"

        if not filtered:
            text += "No items found."
        else:
            for entity in page_entities:
                # Title and year
                title_line = f"🎬 *{entity.title}*"
                if entity.year:
                    title_line += f" ({entity.year})"
                text += title_line + "\n"

                # Rating
                if entity.rating:
                    text += f"⭐ {entity.rating:.1f}/10"
                    if entity.genres:
                        text += f" • {', '.join(entity.genres[:2])}"
                    text += "\n"
                elif entity.genres:
                    text += f"🎭 {', '.join(entity.genres[:2])}\n"

                text += "\n"

            # Page info
            total_pages = (len(filtered) - 1) // ITEMS_PER_PAGE + 1
            text += f"_Page {state.entity_list_page + 1} of {total_pages}_"

        # Build keyboard
        keyboard = []

        # Entity selection buttons
        for entity in page_entities:
            button_text = entity.title
            if len(button_text) > 40:
                button_text = button_text[:37] + "..."
            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{LIBRARY_SELECT_ENTITY}{entity.imdb_id}"
                    )
                ]
            )

        # Pagination buttons
        nav_buttons = []
        if state.entity_list_page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=LIBRARY_PREV_PAGE))
        if end_idx < len(filtered):
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_NEXT_PAGE))
        if nav_buttons:
            keyboard.append(nav_buttons)

        # Filter button
        if state.filter_query:
            keyboard.append(
                [InlineKeyboardButton("✖️ Clear Filter", callback_data=LIBRARY_CLEAR_FILTER)]
            )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Library", callback_data=LIBRARY_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def _render_entity_detail(self, context: Context) -> ScreenRenderResult:
        """Render movie detail view."""
        state = self._get_state(context)
        entity = state.selected_entity

        if not entity:
            text = "⚠️ *Error*\n\nMovie not found."
            keyboard = [[InlineKeyboardButton("« Back", callback_data=LIBRARY_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Build text
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
            text += f"🎭 *Genres:* {', '.join(entity.genres)}\n\n"

        # Director
        if entity.director:
            text += f"🎬 *Director:* {entity.director}\n\n"

        # Cast
        if entity.cast:
            cast_str = ", ".join(entity.cast[:3])
            text += f"⭐ *Cast:* {cast_str}\n\n"

        # Description
        if entity.description:
            desc = entity.description
            if len(desc) > 300:
                desc = desc[:297] + "..."
            text += f"📖 *Plot:*\n{desc}\n\n"

        # Build keyboard
        keyboard = []

        # Files info
        if entity.media_type == MediaType.MOVIE or entity.media_type == MediaType.EPISODE:
            file_count = len(entity.downloaded_files)
            text += f"📁 *Files:* {file_count} video(s)\n\n"
            if file_count > 0:
                if file_count == 1:
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "▶️ Play",
                                callback_data=f"{LIBRARY_PLAY}{entity.downloaded_files[0].id}",
                            )
                        ]
                    )
                else:
                    page = state.entity_pages_list[-1]
                    start_idx = page * ITEMS_PER_PAGE
                    end_idx = start_idx + ITEMS_PER_PAGE
                    page_entities = entity.downloaded_files[start_idx:end_idx]
                    for file in page_entities:
                        button_text = file.file_name
                        if len(button_text) > 40:
                            button_text = button_text[:37] + "..."
                        if state.delete_files_mode:
                            button_text = f"🗑️ Delete {button_text}"
                            callback_data = f"{LIBRARY_DELETE_FILE}{file.id}"
                        else:
                            button_text = f"▶️ Play {button_text}"
                            callback_data = f"{LIBRARY_PLAY}{file.id}"
                        keyboard.append(
                            [InlineKeyboardButton(button_text, callback_data=callback_data)]
                        )
                    videos_pagination_buttons = []
                    if page > 0:
                        videos_pagination_buttons.append(InlineKeyboardButton("« Previous", callback_data=LIBRARY_PREV_PAGE))
                    if end_idx < len(entity.downloaded_files):
                        videos_pagination_buttons.append(InlineKeyboardButton("Next »", callback_data=LIBRARY_NEXT_PAGE))
                    if videos_pagination_buttons:
                        keyboard.append(videos_pagination_buttons)

                    if state.delete_files_mode:
                        keyboard.append(
                            [InlineKeyboardButton("📂 Watch Files", callback_data=LIBRARY_TOGGLE_DELETE_FILES_MODE)]
                        )
                    else:
                        keyboard.append(
                            [InlineKeyboardButton("🗑️ Delete Files", callback_data=LIBRARY_TOGGLE_DELETE_FILES_MODE)]
                        )
        else:
            children = await self.library.get_child_entities(entity)
            page = state.entity_pages_list[-1]
            start_idx = page * ITEMS_PER_PAGE
            end_idx = start_idx + ITEMS_PER_PAGE
            page_entities = children[start_idx:end_idx]
            for child in page_entities:
                button_text = child.title
                if len(button_text) > 40:
                    button_text = button_text[:37] + "..."
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            button_text, callback_data=f"{LIBRARY_SELECT_ENTITY}{child.imdb_id}"
                        )
                    ]
                )

            total_pages = (len(children) - 1) // ITEMS_PER_PAGE + 1
            text += f"_Page {page + 1} of {total_pages}_"
            pagination_buttons = []
            if page > 0:
                pagination_buttons.append(
                    InlineKeyboardButton("« Previous Page", callback_data=LIBRARY_PREV_PAGE)
                )
            if end_idx < len(children):
                pagination_buttons.append(
                    InlineKeyboardButton("Next Page »", callback_data=LIBRARY_NEXT_PAGE)
                )
            if pagination_buttons:
                keyboard.append(pagination_buttons)

        if entity.media_type == MediaType.SEASON or entity.media_type == MediaType.EPISODE:
            parent = await self.library.get_parent_entity(entity)
            if parent is not None:
                sibling_pagination_buttons = []
                siblings = await self.library.get_child_entities(parent)
                my_index = next(
                    (i for i, s in enumerate(siblings) if s.imdb_id == entity.imdb_id), -1
                )
                if my_index > 0:
                    sibling_pagination_buttons.append(
                        InlineKeyboardButton(
                            f"« Previous {entity.media_type.value.title()}",
                            callback_data=f"{LIBRARY_SELECT_ENTITY}{siblings[my_index - 1].imdb_id}",
                        )
                    )
                if my_index < len(siblings) - 1:
                    sibling_pagination_buttons.append(
                        InlineKeyboardButton(
                            f"Next {entity.media_type.value.title()} »",
                            callback_data=f"{LIBRARY_SELECT_ENTITY}{siblings[my_index + 1].imdb_id}",
                        )
                    )
                if sibling_pagination_buttons:
                    keyboard.append(sibling_pagination_buttons)

        # Delete button
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🗑️ Delete {entity.media_type.value.title()}",
                    callback_data=f"{LIBRARY_DELETE}{entity.imdb_id}",
                )
            ]
        )

        # Back button
        keyboard.append([InlineKeyboardButton("« Back", callback_data=LIBRARY_BACK)])

        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=entity.poster_url)

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        state = self._get_state(context)

        if query.data is None:
            return

        elif query.data == LIBRARY_RESCAN:
            await self.library.scan_library()
            self._update_entities_in_state(context)

        elif query.data == LIBRARY_BACK:
            if state.selected_entity is not None:
                parent_entity = await self.library.get_parent_entity(state.selected_entity)
                state.selected_entity = parent_entity
                state.entity_pages_list.pop()
            elif state.view == "main":
                return Navigation(next_screen="main_menu")
            else:
                state.view = "main"

        # Navigation: Show movies/series
        elif query.data == LIBRARY_SHOW_MOVIES:
            state.view = "movies"
            state.entity_list_page = 0
            state.filter_query = ""

        elif query.data == LIBRARY_SHOW_SERIES:
            state.view = "series"
            state.entity_list_page = 0
            state.filter_query = ""

        # Pagination
        elif query.data == LIBRARY_NEXT_PAGE:
            if state.selected_entity is not None:
                state.entity_pages_list[-1] = state.entity_pages_list[-1] + 1
            else:
                state.entity_list_page += 1

        elif query.data == LIBRARY_PREV_PAGE:
            if state.selected_entity is not None:
                state.entity_pages_list[-1] = max(0, state.entity_pages_list[-1] - 1)
            else:
                state.entity_list_page = max(0, state.entity_list_page - 1)

        # Clear filter
        elif query.data == LIBRARY_CLEAR_FILTER:
            state.filter_query = ""
            state.entity_list_page = 0
            state.entity_pages_list = []

        # Move to entity
        elif query.data.startswith(LIBRARY_SELECT_ENTITY):
            state.delete_files_mode = False
            entity_id = query.data[len(LIBRARY_SELECT_ENTITY) :]
            entity = await self.library.get_entity(entity_id)
            if entity is not None:
                if (
                    state.selected_entity is not None
                    and state.selected_entity.media_type == entity.media_type
                ):
                    state.entity_pages_list[-1] = 0
                else:
                    state.entity_pages_list.append(0)
                state.selected_entity = entity
            else:
                state.selected_entity = None
                state.entity_pages_list = []

        elif query.data == LIBRARY_TOGGLE_DELETE_FILES_MODE:
            state.delete_files_mode = not state.delete_files_mode

        # Play
        elif query.data.startswith(LIBRARY_PLAY):
            file_id = query.data[len(LIBRARY_PLAY) :]
            if state.selected_entity is not None:
                file_path = self.library.get_media_file_path(state.selected_entity, file_id)
                result = await self.player.play(file_path)
                if result:
                    # Pass the current library state to player so it can return to it
                    return Navigation(next_screen="player", library_state=state)

        # Delete
        elif query.data.startswith(LIBRARY_DELETE):
            entity_id = query.data[len(LIBRARY_DELETE) :]
            next_entity = await self.library.delete_entity(entity_id, True)
            if next_entity is not None:
                state.selected_entity = await self.library.get_entity(next_entity)
            else:
                state.selected_entity = None
        
        elif query.data.startswith(LIBRARY_DELETE_FILE):
            file_id = query.data[len(LIBRARY_DELETE_FILE) :]
            if state.selected_entity is not None:
                await self.library.delete_file(state.selected_entity.imdb_id, file_id)

    async def handle_message(self, message: Message, context: Context) -> ScreenHandlerResult:
        """Handle text messages for filtering."""
        state = self._get_state(context)

        # Only handle messages in list views
        if state.view not in ("movies", "series"):
            return

        if not message.text:
            return

        # Set filter query
        query = message.text.strip()
        state.filter_query = query
        state.entity_list_page = 0

        return

    def _get_filtered_entities(self, entities: list[MediaEntity], query: str) -> list[MediaEntity]:
        """Filter entities by query (case-insensitive, searches title/description/genres).

        Args:
            entities: List of entities to filter
            query: Filter query string

        Returns:
            Filtered list of entities
        """
        if not query:
            return entities

        query_lower = query.lower()
        filtered = []

        for entity in entities:
            # Search in title
            if query_lower in entity.title.lower():
                filtered.append(entity)
                continue

            # Search in description
            if entity.description and query_lower in entity.description.lower():
                filtered.append(entity)
                continue

            # Search in genres
            if any(query_lower in genre.lower() for genre in entity.genres):
                filtered.append(entity)
                continue

        return filtered
