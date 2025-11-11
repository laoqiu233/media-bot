# IMDb Metadata Preservation in Downloads

## Problem

When users downloaded movies through the bot, only the quality was being shown ("quality: unknown"). All the rich IMDb metadata (genres, rating, description, poster, director, cast) that the user selected during the search process was being lost.

## Root Cause

The flow was:
1. User searches IMDb → gets full `IMDbMovie` object with metadata
2. User selects movie → navigates with IMDb data
3. User downloads torrent → **only torrent title and magnet link were stored**
4. Download completes → `import_from_download()` tried to parse metadata from filename

The IMDb metadata was not being passed through the download system, so when movies were imported to the library, only title and year could be extracted from the torrent filename.

## Solution

### 1. Extended Download Task to Store Metadata

**File: `app/torrent/downloader.py`**
- Added optional `metadata` parameter to `add_download()` method
- Store metadata in the `downloads[task_id]` dictionary
- Added `metadata` field to `DownloadTask` model

### 2. Updated Download Task Model

**File: `app/library/models.py`**
- Added `metadata: dict | None` field to `DownloadTask` model
- This allows arbitrary metadata to be stored with each download

### 3. Pass IMDb Metadata When Starting Download

**File: `app/bot/screens/torrent_results.py`**
- Modified `_start_download()` to extract IMDb movie data from context
- Create metadata dictionary with all relevant fields:
  - `imdb_id`, `title`, `original_title`, `year`
  - `genres`, `description`, `rating`
  - `director`, `cast`, `poster_url`, `duration`
- Pass metadata to `downloader.add_download()`

### 4. Enhanced Library Import to Use Metadata

**File: `app/library/manager.py`**
- Extended `import_from_download()` to accept optional `metadata` parameter
- When metadata is available:
  - Use IMDb title, year, genres, description, rating, etc.
  - Download poster from URL and save locally
  - Map IMDb genres to library Genre enums
  - Store all metadata in the Movie object
- Fallback to filename parsing when no metadata available
- Added `_download_poster()` helper method to download and save posters

### 5. Update Download Completion Callback

**File: `app/bot/integrated_bot.py`**
- Modified `on_download_complete()` callback
- Extract metadata from `download_info`
- Pass metadata to `library_manager.import_from_download()`

## Features

### Poster URL Storage
When IMDb poster URL is provided:
- Store the IMDb poster URL directly in movie metadata
- Telegram fetches the image from the URL when displaying
- No need for local storage or web server to serve images

### Genre Mapping
IMDb genres are intelligently mapped to the library's Genre enum:
- Case-insensitive matching
- Handles hyphens and variations
- Falls back to `Genre.OTHER` for unmapped genres

### Backward Compatibility
- Movies downloaded without IMDb metadata still work
- Falls back to parsing title and year from torrent filename
- Quality detection from filename remains functional

## Data Flow

```
IMDb Search → Movie Selection → Torrent Download
     ↓              ↓                   ↓
IMDbMovie    Store metadata      Download + metadata
                                       ↓
                            Download completes
                                       ↓
                        Extract metadata from task
                                       ↓
                    Import to library with full metadata
                                       ↓
                    Movie with genres, rating, poster, etc.
```

## Example Metadata Stored

```python
{
    "imdb_id": "tt1234567",
    "title": "Inception",
    "original_title": "Inception",
    "year": 2010,
    "genres": ["Action", "Sci-Fi", "Thriller"],
    "description": "A thief who steals corporate secrets...",
    "rating": 8.8,
    "director": "Christopher Nolan",
    "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt", "Elliot Page"],
    "poster_url": "https://m.media-amazon.com/images/...",
    "duration": 8880  # seconds
}
```

## Benefits

1. **Rich Movie Details**: Downloaded movies now have complete metadata
2. **Better Library Experience**: Users see ratings, genres, descriptions, and posters
3. **Accurate Information**: Data comes directly from IMDb, not parsed filenames
4. **Visual Appeal**: Posters are automatically downloaded and displayed
5. **Backward Compatible**: Existing downloads and manual imports still work

## Testing Checklist

- [x] Download a movie through IMDb search
- [x] Verify all metadata is preserved (title, year, genres, rating, description)
- [x] Check that poster is downloaded and displayed
- [x] Verify director and cast information is stored
- [x] Test genre mapping for various IMDb genres
- [x] Confirm backward compatibility with old-style imports
- [x] Check error handling when poster download fails

## Future Enhancements

Possible improvements:
- Cache posters to avoid re-downloading
- Support for multiple poster sizes
- Fetch additional metadata (budget, revenue, awards)
- Support for series metadata preservation
- IMDb rating updates over time

