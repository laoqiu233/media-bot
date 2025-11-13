import asyncio
import logging
from dataclasses import dataclass, field

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    MOVIE_BACK,
    MOVIE_DOWNLOAD_SEASON,
    MOVIE_DOWNLOAD_SERIES,
    MOVIE_EPISODES_BACK,
    MOVIE_EPISODES_NEXT,
    MOVIE_EPISODES_PREV,
    MOVIE_NEXT,
    MOVIE_PREV,
    MOVIE_SEASONS_BACK,
    MOVIE_SEASONS_NEXT,
    MOVIE_SEASONS_PREV,
    MOVIE_SELECT,
    MOVIE_SELECT_EPISODE,
    MOVIE_SELECT_SEASON,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.library.imdb_client import IMDbClient
from app.library.models import (
    DownloadEpisode,
    DownloadMovie,
    DownloadSeason,
    DownloadSeries,
    IMDbEpisode,
    IMDbSeason,
    IMDbTitle,
)

logger = logging.getLogger(__name__)

SEASONS_PER_PAGE = 8
EPISODES_PER_PAGE = 8
STATE_KEY = "movie_selection_state"


@dataclass
class MovieSelectionState:
    """State for movie selection screen."""

    titles: list[IMDbTitle] = field(default_factory=list)
    query: str = ""
    page: int = 0
    fetching_details: dict[int, bool] = field(default_factory=dict)
    detailed_movies: dict[int, IMDbTitle] = field(default_factory=dict)
    detailed_series_seasons: dict[int, list[IMDbSeason]] = field(default_factory=dict)
    detailed_series_episodes: dict[int, dict[str, list[IMDbEpisode]]] = field(default_factory=dict)
    display_series_options: bool = False
    season_page: int = 0
    episode_page: int = 0
    selected_season_index: int | None = None


class MovieSelectionScreen(Screen):
    """Screen for selecting a movie from IMDb search results."""

    def __init__(self, imdb_client: IMDbClient):
        """Initialize movie selection screen.

        Args:
            imdb_client: IMDb API client
        """
        self.imdb_client = imdb_client

    def get_name(self) -> str:
        """Get screen name."""
        return "movie_selection"

    def _get_state(self, context: Context) -> MovieSelectionState:
        """Get the state from context, or create a new one if it doesn't exist."""
        raw_state = context.get_context().get(STATE_KEY)
        if raw_state is None or not isinstance(raw_state, MovieSelectionState):
            raw_state = MovieSelectionState()
            context.update_context(**{STATE_KEY: raw_state})
            return raw_state
        return raw_state

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.

        Expects kwargs (new search from search screen):
            movies: List of IMDbTitle objects from search
            query: Original search query

        Or kwargs (returning from torrent screen):
            movies: List of IMDbTitle objects
            detailed_movies: Dict of detailed movie data
            query: Search query
            page: Current page
        """
        state = self._get_state(context)
        if "titles" in kwargs:
            state.titles = kwargs["titles"]
        elif STATE_KEY in kwargs:
            context.update_context(**{STATE_KEY: kwargs[STATE_KEY]})
        asyncio.create_task(self._fetch_page_details(context, state.page))

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the movie selection screen."""
        state = self._get_state(context)

        if not state.titles:
            text = (
                "🎬 *Movie Selection*\n\n"
                "No movies or series found.\n\n"
                "Please go back and try a different search."
            )
            keyboard = [[InlineKeyboardButton("« Back to Search", callback_data=MOVIE_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        # Get current movie - use detailed version if available, otherwise basic from search
        movie: IMDbTitle = (
            state.detailed_movies[state.page]
            if state.page in state.detailed_movies
            else state.titles[state.page]
        )

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

        if not state.detailed_movies or state.page not in state.detailed_movies:
            text += "⏳ Loading details...\n\n"

        # Page info
        text += f"_Movie or series {state.page + 1} of {len(state.titles)}_"

        # Build keyboard
        keyboard = []

        if not state.display_series_options:
            # Select button (Not shown if details are not fetched yet)
            if state.detailed_movies and state.page in state.detailed_movies:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"✅ Select This {'Series' if movie.is_series else 'Movie'}",
                            callback_data=f"{MOVIE_SELECT}{state.page}",
                        )
                    ]
                )

            # Navigation buttons
            nav_buttons = []
            if state.page > 0:
                nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=MOVIE_PREV))
            if state.page < len(state.titles) - 1:
                nav_buttons.append(InlineKeyboardButton("Next »", callback_data=MOVIE_NEXT))

            if nav_buttons:
                keyboard.append(nav_buttons)

            # Back button
            keyboard.append([InlineKeyboardButton("« Back to Search", callback_data=MOVIE_BACK)])
        else:
            # Series options
            selected_season: IMDbSeason | None = (
                None
                if state.selected_season_index is None
                else state.detailed_series_seasons.get(state.page, [])[state.selected_season_index]
            )
            if selected_season is not None:
                # Episode selection with pagination
                episodes_in_series: dict[str, list[IMDbEpisode]] = (
                    state.detailed_series_episodes.get(state.page, {})
                )
                episodes_in_season = episodes_in_series.get(selected_season.season, [])

                # Slice episodes for current page
                start_idx = state.episode_page * EPISODES_PER_PAGE
                end_idx = start_idx + EPISODES_PER_PAGE
                page_episodes = episodes_in_season[start_idx:end_idx]

                # Display fake button when loading episodes
                if not episodes_in_season:
                    keyboard.append(
                        [InlineKeyboardButton("Loading episodes...", callback_data="fake_callback")]
                    )

                # Display episodes for current page
                for idx, episode in enumerate(page_episodes):
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"Episode {episode.episodeNumber if episode.episodeNumber is not None else 'N/A'} ({episode.title})",
                                callback_data=f"{MOVIE_SELECT_EPISODE}{start_idx + idx}",
                            )
                        ]
                    )

                # Pagination buttons for episodes
                nav_buttons = []
                if state.episode_page > 0:
                    nav_buttons.append(
                        InlineKeyboardButton("« Previous", callback_data=MOVIE_EPISODES_PREV)
                    )
                if end_idx < len(episodes_in_season):
                    nav_buttons.append(
                        InlineKeyboardButton("Next »", callback_data=MOVIE_EPISODES_NEXT)
                    )

                if nav_buttons:
                    keyboard.append(nav_buttons)

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "Download Entire Season",
                            callback_data=f"{MOVIE_DOWNLOAD_SEASON}{state.selected_season_index}",
                        )
                    ]
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "« Back to Seasons List", callback_data=MOVIE_EPISODES_BACK
                        )
                    ]
                )
            else:
                # Season selection with pagination
                seasons: list[IMDbSeason] = state.detailed_series_seasons.get(state.page, [])

                # Slice seasons for current page
                start_idx = state.season_page * SEASONS_PER_PAGE
                end_idx = start_idx + SEASONS_PER_PAGE

                # Display seasons for current page
                for season_index_in_all_seasons in range(start_idx, min(end_idx, len(seasons))):
                    season = seasons[season_index_in_all_seasons]
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"Season {season.season} ({season.episodeCount} episodes)",
                                callback_data=f"{MOVIE_SELECT_SEASON}{season_index_in_all_seasons}",
                            )
                        ]
                    )

                # Pagination buttons for seasons
                nav_buttons = []
                if state.season_page > 0:
                    nav_buttons.append(
                        InlineKeyboardButton("« Previous", callback_data=MOVIE_SEASONS_PREV)
                    )
                if end_idx < len(seasons):
                    nav_buttons.append(
                        InlineKeyboardButton("Next »", callback_data=MOVIE_SEASONS_NEXT)
                    )

                if nav_buttons:
                    keyboard.append(nav_buttons)

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "Download Entire Series",
                            callback_data=f"{MOVIE_DOWNLOAD_SERIES}{state.page}",
                        )
                    ]
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "« Back to Movie Selection", callback_data=MOVIE_SEASONS_BACK
                        )
                    ]
                )

        # Return with poster URL in render options
        return text, InlineKeyboardMarkup(keyboard), RenderOptions(photo_url=movie.poster_url)

    async def _fetch_page_details(self, context: Context, page: int) -> None:
        """Fetch full details for a specific page if not already cached.

        Args:
            context: Screen context
            page: Page index to fetch details for
        """
        state = self._get_state(context)

        # Skip if already fetched or invalid page
        if (
            page in state.detailed_movies
            or page < 0
            or page >= len(state.titles)
            or state.fetching_details.get(page, False)
        ):
            return

        state.fetching_details[page] = True

        try:
            movie = state.titles[page]
            logger.info(f"Fetching details for: {movie.primaryTitle} (page {page})")
            detailed_movie = await self.imdb_client.get_title(movie.id)

            if detailed_movie:
                state.detailed_movies[page] = detailed_movie

                if movie.is_series:
                    seasons = await self.imdb_client.get_series_seasons(movie.id)
                    state.detailed_series_seasons[page] = seasons
                    state.detailed_series_episodes[page] = {}

            logger.info(f"Cached details for page {page}")
        except Exception as e:
            logger.warning(f"Failed to fetch details for page {page}: {e}")

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        if query.data is None:
            return

        state = self._get_state(context)

        if query.data == MOVIE_BACK:
            return Navigation(next_screen="search")

        elif query.data == MOVIE_PREV:
            new_page = max(0, state.page - 1)
            state.page = new_page

            # Fetch details for new page
            await self._fetch_page_details(context, new_page)

        elif query.data == MOVIE_NEXT:
            new_page = min(state.page + 1, len(state.titles) - 1)
            state.page = new_page

            # Fetch details for new page
            await self._fetch_page_details(context, new_page)

        elif query.data.startswith(MOVIE_SELECT_SEASON):
            season_index = int(query.data[len(MOVIE_SELECT_SEASON) :])
            season_list: list[IMDbSeason] = state.detailed_series_seasons.get(state.page, [])
            if 0 <= season_index < len(season_list):

                async def fetch_episodes(season: IMDbSeason):
                    episodes = await self.imdb_client.get_series_episodes(
                        state.titles[state.page].id, season.season
                    )
                    state.detailed_series_episodes[state.page][season.season] = episodes

                asyncio.create_task(fetch_episodes(season_list[season_index]))
                state.selected_season_index = season_index
                state.episode_page = 0

        elif query.data == MOVIE_SEASONS_BACK:
            state.display_series_options = False
            state.season_page = 0

        elif query.data == MOVIE_SEASONS_PREV:
            new_season_page = max(0, state.season_page - 1)
            state.season_page = new_season_page

        elif query.data == MOVIE_SEASONS_NEXT:
            total_seasons: list[IMDbSeason] = state.detailed_series_seasons.get(state.page, [])
            max_season_page = (len(total_seasons) - 1) // SEASONS_PER_PAGE
            new_season_page = min(state.season_page + 1, max_season_page)
            state.season_page = new_season_page

        elif query.data == MOVIE_EPISODES_BACK:
            state.selected_season_index = None
            state.episode_page = 0

        elif query.data == MOVIE_EPISODES_PREV:
            new_episode_page = max(0, state.episode_page - 1)
            state.episode_page = new_episode_page

        elif query.data == MOVIE_EPISODES_NEXT:
            if state.selected_season_index is not None:
                selected_season = state.detailed_series_seasons.get(state.page, [])[
                    state.selected_season_index
                ]
                episodes_in_series: dict[str, list[IMDbEpisode]] = (
                    state.detailed_series_episodes.get(state.page, {})
                )
                episodes_in_season: list[IMDbEpisode] = episodes_in_series.get(
                    selected_season.season, []
                )
                max_episode_page = (len(episodes_in_season) - 1) // EPISODES_PER_PAGE
                new_episode_page = min(state.episode_page + 1, max_episode_page)
                state.episode_page = new_episode_page

        elif query.data.startswith(MOVIE_SELECT):
            index = int(query.data[len(MOVIE_SELECT) :])

            if 0 <= index < len(state.titles):
                # Use detailed version if available, otherwise basic
                selected_movie = state.detailed_movies.get(index, state.titles[index])
                await query.answer(f"Selected: {selected_movie.primaryTitle}", show_alert=False)

                # Check if it's a TV series using the helper property
                if selected_movie.is_series:
                    state.display_series_options = True
                    state.season_page = 0
                    state.episode_page = 0
                else:
                    # Navigate to torrent screen for movies
                    download_metadata = DownloadMovie(movie=selected_movie)
                    return Navigation(
                        next_screen="torrent",
                        movie_selection_state=state,
                        imdb_metadata=download_metadata,
                    )

        elif query.data.startswith(MOVIE_SELECT_EPISODE):
            if state.selected_season_index is not None:
                episode = int(query.data[len(MOVIE_SELECT_EPISODE) :])
                selected_series = state.detailed_movies[state.page]
                selected_season = state.detailed_series_seasons.get(state.page, [])[
                    state.selected_season_index
                ]
                selected_episode = state.detailed_series_episodes.get(state.page, {})[
                    selected_season.season
                ][episode]
                download_metadata = DownloadEpisode(
                    series=selected_series, season=selected_season, episode=selected_episode
                )
                return Navigation(
                    next_screen="torrent",
                    movie_selection_state=state,
                    imdb_metadata=download_metadata,
                )

        elif query.data.startswith(MOVIE_DOWNLOAD_SEASON):
            # Download season
            if state.selected_season_index is not None:
                selected_series = state.detailed_movies[state.page]
                selected_season = state.detailed_series_seasons.get(state.page, [])[
                    state.selected_season_index
                ]
                download_metadata = DownloadSeason(series=selected_series, season=selected_season)
                return Navigation(
                    next_screen="torrent",
                    movie_selection_state=state,
                    imdb_metadata=download_metadata,
                )

        elif query.data.startswith(MOVIE_DOWNLOAD_SERIES):
            selected_series = state.detailed_movies[state.page]
            download_metadata = DownloadSeries(series=selected_series)
            return Navigation(
                next_screen="torrent", movie_selection_state=state, imdb_metadata=download_metadata
            )
