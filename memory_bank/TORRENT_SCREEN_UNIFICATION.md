# Torrent Screen Unification

**Date**: November 12, 2025  
**Type**: Refactoring

## Summary

Combined the `TorrentProvidersScreen` and `TorrentResultsScreen` into a single unified `TorrentScreen` that uses internal state to control which view is displayed.

## Changes Made

### New Unified Screen

**File**: `app/bot/screens/torrent.py`

- Created `TorrentScreen` class that combines both provider selection and results display
- Uses internal state via `view` field: `"providers"` or `"results"`
- Provider selection view shows available torrent providers (YTS, RuTracker)
- Results view shows paginated torrent search results

### State Management

The screen uses context state to manage views:

```python
# Provider selection view (default)
context.update_context(view="providers", ...)

# Results view (after provider selection)
context.update_context(view="results", results=..., results_page=0, ...)
```

### Navigation Flow

1. **Entry** → Provider selection view
2. **Select Provider** → Searches torrents → Results view
3. **Back from Results** → Provider selection view (stays on same screen)
4. **Back from Providers** → Movie selection screen (navigates away)

### Callback Handling

- `MOVIE_BACK` - Navigate back to movie selection (from providers view)
- `TORRENT_BACK` - Switch to providers view (from results view)
- `PROVIDER_SELECT{provider}` - Search torrents and switch to results view
- `TORRENT_SELECT{index}` - Download selected torrent
- `TORRENT_PREV` / `TORRENT_NEXT` - Paginate results

### Files Modified

1. **Created**: `app/bot/screens/torrent.py` - Unified torrent screen
2. **Deleted**: `app/bot/screens/torrent_providers.py` - Old provider screen
3. **Deleted**: `app/bot/screens/torrent_results.py` - Old results screen
4. **Updated**: `app/bot/screen_registry.py` - Register unified screen
5. **Updated**: `app/bot/screens/__init__.py` - Export unified screen
6. **Updated**: `app/bot/screens/movie_selection.py` - Navigate to "torrent" instead of "torrent_providers"
7. **Updated**: `app/bot/screens/series_download.py` - Navigate to "torrent" instead of "torrent_results"

### Screen Name Change

- Old: `"torrent_providers"` → New: `"torrent"` (initial view: providers)
- Old: `"torrent_results"` → New: `"torrent"` (with view: results)

## Benefits

1. **Simpler Navigation**: No screen transitions between provider selection and results
2. **Better UX**: Faster switching between providers (no full re-render)
3. **Code Organization**: Related functionality in single file
4. **State Management**: Cleaner context state handling
5. **Reduced Complexity**: One screen registration instead of two

## Implementation Details

### Render Logic

```python
async def render(self, context: Context) -> ScreenRenderResult:
    state = context.get_context()
    view = state.get("view", "providers")
    
    if view == "providers":
        return await self._render_providers(context)
    elif view == "results":
        return await self._render_results(context)
```

### Search Execution

When a provider is selected:

1. Extract provider name from callback
2. Build search query from movie title + year
3. Execute async search via `self.searcher.search()`
4. Update context with results and switch to "results" view
5. Screen re-renders automatically with results

### Metadata Preservation

Download metadata is preserved exactly as before, including:
- IMDb ID, title, year
- Genres, description, rating
- Director, cast, poster URL
- Torrent quality (720p, 1080p, etc.)
- Series IMDb ID (for episode downloads)

## Testing Notes

- Test navigation flow: movie selection → providers → results → back → providers → back → movie selection
- Test multiple provider selections without leaving screen
- Test pagination in results view
- Test download initiation and metadata
- Test series episode downloads with `series_imdb_id`

## Callback Constants

All existing callback constants remain unchanged in `app/bot/callback_data.py`:
- `MOVIE_BACK`
- `PROVIDER_SELECT`
- `TORRENT_BACK`
- `TORRENT_SELECT`
- `TORRENT_NEXT`
- `TORRENT_PREV`

