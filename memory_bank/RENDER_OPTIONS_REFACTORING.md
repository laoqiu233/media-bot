# RenderOptions Refactoring

## Overview

Refactored the screen rendering system to use a cleaner, more decoupled architecture where screens explicitly declare their rendering needs through a `RenderOptions` return value instead of using context as a side channel.

## Problem

The initial implementation for displaying movie posters coupled the `Session` class to the specific needs of the `MovieSelectionScreen` by checking for `current_poster_url` in the context. This violated separation of concerns and made the system less flexible.

## Solution

Introduced a `RenderOptions` dataclass that screens return alongside their text and keyboard, explicitly declaring:
- `photo_url`: Optional URL for a photo to display
- `force_new_message`: Whether to send a new message instead of editing

## Changes Made

### 1. Added RenderOptions Dataclass

**File**: `app/bot/screens/base.py`

```python
@dataclass
class RenderOptions:
    """Options for controlling how a screen should be rendered."""
    
    photo_url: str | None = None
    """Optional photo URL to display with the message."""
    
    force_new_message: bool = False
    """If True, forces sending a new message instead of editing the current one."""
```

### 2. Updated ScreenRenderResult Type

**Before**: `tuple[str, InlineKeyboardMarkup]`
**After**: `tuple[str, InlineKeyboardMarkup, RenderOptions]`

### 3. Updated Session.render_screen()

**File**: `app/bot/session.py`

- Now unpacks `RenderOptions` from the screen's render method
- Uses `photo_url` and `force_new_message` from options instead of context
- Automatically handles switching between photo and text messages
- Sends new message when photo changes or force flag is set

### 4. Updated All Screens

All screen render methods now return `RenderOptions`:

**IMDb-related screens** (with photos):
- `movie_selection.py` - Returns `RenderOptions(photo_url=movie.poster_url)`
- `torrent_providers.py` - Returns `RenderOptions()`
- `torrent_results.py` - Returns `RenderOptions()`
- `search.py` - Returns `RenderOptions()`

**Existing screens** (text only):
- `main_menu.py` - Returns `RenderOptions()`
- `downloads.py` - Returns `RenderOptions()`
- `library.py` - Returns `RenderOptions()`
- `player.py` - Returns `RenderOptions()`
- `status.py` - Returns `RenderOptions()`
- `tv.py` - Returns `RenderOptions()`

## Benefits

### 1. Separation of Concerns
- Screens declare their needs explicitly
- Session handles rendering logic generically
- No screen-specific logic in Session

### 2. Type Safety
- Clear contract via `RenderOptions` dataclass
- Type hints make requirements explicit
- IDE autocomplete support

### 3. Extensibility
- Easy to add new rendering options
- Screens can opt-in to features
- No breaking changes to existing screens

### 4. Testability
- Screens can be tested independently
- Render options are explicit return values
- No hidden dependencies on context

## Example Usage

### Screen with Photo

```python
async def render(self, context: Context) -> tuple[str, InlineKeyboardMarkup, RenderOptions]:
    movie = context.get_context().get("current_movie")
    text = f"🎬 {movie.title}"
    keyboard = InlineKeyboardMarkup([[...]])
    
    # Return with photo URL
    return text, keyboard, RenderOptions(photo_url=movie.poster_url)
```

### Screen with Text Only

```python
async def render(self, context: Context) -> tuple[str, InlineKeyboardMarkup, RenderOptions]:
    text = "Welcome to the main menu"
    keyboard = InlineKeyboardMarkup([[...]])
    
    # Return with default (empty) options
    return text, keyboard, RenderOptions()
```

### Screen Forcing New Message

```python
async def render(self, context: Context) -> tuple[str, InlineKeyboardMarkup, RenderOptions]:
    text = "Important notification"
    keyboard = InlineKeyboardMarkup([[...]])
    
    # Force a new message instead of editing
    return text, keyboard, RenderOptions(force_new_message=True)
```

## Future Possibilities

The `RenderOptions` pattern makes it easy to add new features:

- `parse_mode`: Override default Markdown parsing
- `disable_notification`: Silent message updates
- `video_url`: Support for video messages
- `animation_url`: Support for GIFs
- `document_url`: Support for document attachments
- `buttons_per_row`: Control keyboard layout
- `max_width`: Control text wrapping

## Migration Guide

For any new screens:

1. Import `RenderOptions` from `app.bot.screens.base`
2. Update render method signature to return 3-tuple
3. Return `RenderOptions()` for text-only screens
4. Return `RenderOptions(photo_url=url)` for screens with images

## Testing

All linter checks pass:
```bash
poetry run ruff check app/bot/
# ✓ All checks passed!
```

## Credits

This refactoring improves code quality by following clean architecture principles and maintaining a clear separation between screen logic and rendering infrastructure.

