"""Movie selection screen for browsing IMDb search results."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import MOVIE_BACK, MOVIE_NEXT, MOVIE_PREV, MOVIE_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.models import IMDbMovie

logger = logging.getLogger(__name__)


class MovieSelectionScreen(Screen):
    """Screen for selecting a movie from IMDb search results."""

    def __init__(self, imdb_client):
        """Initialize movie selection screen.

        Args:
            imdb_client: IMDb API client
        """
        self.imdb_client = imdb_client

    def get_name(self) -> str:
        """Get screen name."""
        return "movie_selection"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.

        Expects kwargs (new search from search screen):
            movies: List of movie dictionaries from IMDb API (search results)
            query: Original search query
        
        Or kwargs (returning from torrent_providers):
            movies: List of IMDbMovie objects
            detailed_movies: Dict of detailed movie data
            query: Search query
            page: Current page
        """
        movies_data = kwargs.get("movies", [])
        query = kwargs.get("query", "")
        page = kwargs.get("page", 0)
        detailed_movies = kwargs.get("detailed_movies", {})

        # Check if movies are already IMDbMovie objects or raw dicts
        if movies_data and isinstance(movies_data[0], dict):
            # New search - parse search results
            movies = []
            for movie_data in movies_data:
                try:
                    movie = IMDbMovie(**movie_data)
                    movies.append(movie)
                except Exception as e:
                    logger.warning(f"Failed to parse movie data: {e}")
                    continue

            context.update_context(
                movies=movies,
                query=query,
                page=0,
                detailed_movies={},  # Clear detail cache for new search
            )

            # Fetch details for the first page immediately
            await self._fetch_page_details(context, 0)
        else:
            # Returning from another screen - restore context
            context.update_context(
                movies=movies_data,
                query=query,
                page=page,
                detailed_movies=detailed_movies,
            )

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the movie selection screen."""
        state = context.get_context()
        movies: list[IMDbMovie] = state.get("movies", [])
        page: dict[int, IMDbMovie] = state.get("page", 0)

        if not movies:
            text = (
                "🎬 *Movie Selection*\n\n"
                "No movies found.\n\n"
                "Please go back and try a different search."
            )
            keyboard = [[InlineKeyboardButton("« Back to Search", callback_data=MOVIE_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Get current movie - use detailed version if available, otherwise basic from search
        detailed_movies = state.get("detailed_movies", {})
        movie = detailed_movies[page] if page in detailed_movies else movies[page]

        # Build movie information text
        text = f"🎬 *{movie.primaryTitle}*"
        if movie.startYear:
            text += f" ({movie.startYear})"
        text += "\n\n"

        # Rating
        if movie.rating_value:
            stars = "⭐" * int(movie.rating_value / 2)
            text += f"{stars} *{movie.rating_value:.1f}/10*"
            if movie.vote_count:
                text += f" ({movie.vote_count:,} votes)"
            text += "\n\n"

        # Genres
        if movie.genres:
            text += f"🎭 *Genres:* {', '.join(movie.genres)}\n\n"

        # Directors
        if movie.director_names:
            directors = ", ".join(movie.director_names)
            text += f"🎬 *Director:* {directors}\n\n"

        # Stars (top 3)
        if movie.stars:
            star_names = [star.name for star in movie.stars[:3]]
            if star_names:
                text += f"⭐ *Stars:* {', '.join(star_names)}\n\n"

        # Plot
        if movie.plot:
            plot = movie.plot
            # Limit plot length for readability
            if len(plot) > 200:
                plot = plot[:197] + "..."
            text += f"📖 *Plot:*\n{plot}\n\n"

        # Page info
        text += f"_Movie {page + 1} of {len(movies)}_"

        # Build keyboard
        keyboard = []

        # Select button
        keyboard.append(
            [InlineKeyboardButton("✅ Select This Movie", callback_data=f"{MOVIE_SELECT}{page}")]
        )

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=MOVIE_PREV))
        if page < len(movies) - 1:
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=MOVIE_NEXT))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Back button
        keyboard.append([InlineKeyboardButton("« Back to Search", callback_data=MOVIE_BACK)])

        # Return with poster URL in render options
        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=movie.poster_url)

    async def _fetch_page_details(self, context: Context, page: int) -> None:
        """Fetch full details for a specific page if not already cached.

        Args:
            context: Screen context
            page: Page index to fetch details for
        """
        state = context.get_context()
        movies: list[IMDbMovie] = state.get("movies", [])
        detailed_movies = state.get("detailed_movies", {})

        # Skip if already fetched or invalid page
        if page in detailed_movies or page < 0 or page >= len(movies):
            return

        try:
            movie = movies[page]
            logger.info(f"Fetching details for: {movie.primaryTitle} (page {page})")
            full_data = await self.imdb_client.get_title(movie.id)

            if full_data:
                detailed_movie = IMDbMovie(**full_data)
                detailed_movies[page] = detailed_movie
                context.update_context(detailed_movies=detailed_movies)
                logger.info(f"Cached details for page {page}")
        except Exception as e:
            logger.warning(f"Failed to fetch details for page {page}: {e}")
            # Don't update cache, will use basic data on render

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        if query.data == MOVIE_BACK:
            return Navigation(next_screen="search")

        elif query.data == MOVIE_PREV:
            current_page = context.get_context().get("page", 0)
            new_page = max(0, current_page - 1)
            context.update_context(page=new_page)

            # Fetch details for new page
            if new_page != current_page:
                await self._fetch_page_details(context, new_page)

        elif query.data == MOVIE_NEXT:
            current_page = context.get_context().get("page", 0)
            movies = context.get_context().get("movies", [])
            new_page = min(current_page + 1, len(movies) - 1)
            context.update_context(page=new_page)

            # Fetch details for new page
            if new_page != current_page:
                await self._fetch_page_details(context, new_page)

        elif query.data.startswith(MOVIE_SELECT):
            index = int(query.data[len(MOVIE_SELECT) :])
            state = context.get_context()
            movies: list[IMDbMovie] = state.get("movies", [])
            detailed_movies: dict[int, IMDbMovie] = state.get("detailed_movies", {})
            query_text = state.get("query", "")
            current_page = state.get("page", 0)

            if 0 <= index < len(movies):
                # Use detailed version if available, otherwise basic
                selected_movie = detailed_movies.get(index, movies[index])
                await query.answer(f"Selected: {selected_movie.primaryTitle}", show_alert=False)

                # Navigate to provider selection with movie data and context for back navigation
                return Navigation(
                    next_screen="torrent_providers",
                    movie=selected_movie,
                    movies=movies,
                    detailed_movies=detailed_movies,
                    query=query_text,
                    page=current_page,
                )
