# Movie Selection Screen State Refactoring

**Date**: November 12, 2025  
**Type**: Refactoring

## Summary

Refactored the `MovieSelectionScreen` to use a single dataclass (`MovieSelectionState`) for state management instead of storing separate keys in the context. This improves type safety, code clarity, and makes state management more maintainable.

## Changes Made

### New State Dataclass

**File**: `app/bot/screens/movie_selection.py`

Created `MovieSelectionState` dataclass to encapsulate all screen state:

```python
@dataclass
class MovieSelectionState:
    """State for movie selection screen."""
    
    titles: list[IMDbTitle] = field(default_factory=list)
    query: str = ""
    page: int = 0
    detailed_movies: dict[int, IMDbTitle] = field(default_factory=dict)
    detailed_series_seasons: dict[int, list[IMDbSeason]] = field(default_factory=dict)
    detailed_series_episodes: dict[int, list[IMDbEpisode]] = field(default_factory=dict)
    display_series_options: bool = False
    season_page: int = 0
    episode_page: int = 0
    selected_season_index: int | None = None
```

### State Management Methods

Added helper methods to the screen class:

1. **`_get_state(context: Context) -> MovieSelectionState`**
   - Retrieves the state dataclass from context
   - Returns a new empty state if none exists
   - Type-safe retrieval with proper type checking

2. **`_update_state(context: Context, state: MovieSelectionState)`**
   - Stores the state dataclass back into context
   - Uses a constant key (`STATE_KEY = "movie_selection_state"`)

### Before and After

#### Before (Separate Keys)
```python
# Getting state
state = context.get_context()
titles = state.get("titles", [])
page = state.get("page", 0)
detailed_movies = state.get("detailed_movies", {})

# Updating state
context.update_context(
    page=new_page,
    detailed_movies=detailed_movies
)
```

#### After (Dataclass)
```python
# Getting state
state = self._get_state(context)
titles = state.titles
page = state.page
detailed_movies = state.detailed_movies

# Updating state
state.page = new_page
state.detailed_movies = detailed_movies
self._update_state(context, state)
```

### Refactored Methods

1. **`on_enter`** - Creates new state from kwargs
2. **`render`** - Uses state attributes directly
3. **`_fetch_page_details`** - Modifies state and updates context
4. **`handle_callback`** - All callback handlers now use state dataclass

### Benefits

1. **Type Safety**: IDE autocomplete and type checking for all state fields
2. **Clarity**: Clear definition of all state fields in one place
3. **Maintainability**: Easy to add/remove state fields
4. **Less Error-Prone**: No more typos in string keys
5. **Better Documentation**: Dataclass serves as documentation
6. **Immutability Options**: Can add `frozen=True` if needed in future
7. **Default Values**: Clear default values in dataclass definition

### State Fields Explained

- **titles**: List of IMDb titles from search results
- **query**: Original search query string
- **page**: Current movie page index (0-based)
- **detailed_movies**: Cache of detailed movie data by page index
- **detailed_series_seasons**: Cache of series seasons by page index
- **detailed_series_episodes**: Cache of series episodes by page index
- **display_series_options**: Whether to show series season/episode selection
- **season_page**: Current season pagination page
- **episode_page**: Current episode pagination page
- **selected_season_index**: Index of currently selected season (for episode view)

### Implementation Notes

1. **State Key**: All state stored under single key `"movie_selection_state"`
2. **Type Checking**: Added `isinstance` check in `_get_state` for safety
3. **Navigation**: State can still be passed to other screens via Navigation kwargs
4. **Backwards Compatibility**: Navigation still uses separate kwargs (not breaking other screens)

### Testing Considerations

- Test navigation through movie list (prev/next)
- Test series season selection and pagination
- Test series episode selection and pagination
- Test movie selection (non-series)
- Test return navigation from torrent screen
- Test detail fetching and caching
- Verify poster display still works
- Test all pagination boundaries

### Pattern for Other Screens

This refactoring establishes a pattern that can be applied to other screens:

1. Define a dataclass for screen state
2. Add `_get_state()` and `_update_state()` helper methods
3. Use `STATE_KEY` constant for context storage
4. Refactor all methods to use dataclass attributes
5. Keep Navigation kwargs separate (for cross-screen communication)

### Screens That Could Benefit

- `SearchScreen` - query, page state
- `LibraryScreen` - view, page, filter_query, filtering_mode
- `DownloadsScreen` - filter, sort, page
- `TorrentScreen` - view, provider, results, results_page (already using view state)

## Files Modified

- ✅ `app/bot/screens/movie_selection.py` - Complete refactoring with dataclass

## Linter Status

- ✅ No linter errors introduced
- ✅ All type hints pass type checking
- ✅ Code follows project style guide

