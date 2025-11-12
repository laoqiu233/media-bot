# Torrent Download System Optimization

**Date**: November 12, 2025  
**Author**: Dmitri Tsiu

## Overview

Optimized the torrent download system to eliminate redundant downloads and improve separation of concerns following SOLID principles.

## Key Improvements

### 1. **Eliminated Redundant Torrent File Downloads**

**Problem**: The system was downloading the same torrent file twice:
- Once during validation (to check contents)
- Again during actual download (to start the download)

**Solution**: Cache the torrent file during validation and reuse it during download.

**Changes**:
- Added `torrent_file_path: Path | None` to `ValidationResult` dataclass
- Validator now keeps the downloaded torrent file and stores its path in `ValidationResult`
- Downloader checks for cached torrent file before downloading again
- Only cleans up temp file on validation error

### 2. **Removed Tracker-Specific Logic from Generic Components**

**Problem**: The `TorrentSearcher.download_torrent_file()` method was parsing URLs to detect RuTracker, violating single responsibility principle.

**Solution**: Encode tracker information in the data model.

**Changes**:
- Added `requires_auth: bool` field to `TorrentSearchResult` model
- RuTracker results are marked with `requires_auth=True` during search
- `download_torrent_file()` accepts `requires_auth` parameter instead of parsing URLs
- Validator passes `requires_auth` flag through the call chain

## Architecture Flow

### Before Optimization

```
1. User selects torrent result
2. TorrentScreen → Validator.validate_torrent(url)
3. Validator downloads torrent file (parses URL for tracker type)
4. Validator parses and validates content
5. Validator deletes temp file
6. User confirms download
7. TorrentScreen → Downloader.add_download()
8. Downloader downloads same torrent file AGAIN (parses URL again)
9. Downloader starts libtorrent session
```

### After Optimization

```
1. User selects torrent result (with requires_auth flag)
2. TorrentScreen → Validator.validate_torrent(url, requires_auth)
3. Validator → Searcher.download_torrent_file(url, requires_auth)
4. Validator parses and validates content
5. Validator KEEPS temp file, stores path in ValidationResult
6. User confirms download
7. TorrentScreen → Downloader.add_download(validation_result)
8. Downloader REUSES cached torrent file from validation_result.torrent_file_path
9. Downloader starts libtorrent session
```

## Code Changes

### Models (`app/library/models.py`)

```python
class TorrentSearchResult(BaseModel):
    # ... existing fields ...
    requires_auth: bool = Field(
        default=False, 
        description="Whether this tracker requires authentication"
    )

@dataclass
class ValidationResult:
    # ... existing fields ...
    torrent_file_path: Path | None = None  # Path to downloaded torrent file (for reuse)
```

### Searcher (`app/torrent/searcher.py`)

```python
# Set requires_auth when creating RuTracker results
results.append(
    TorrentSearchResult(
        # ... other fields ...
        requires_auth=True,  # RuTracker requires authentication
    )
)

# Updated download method signature
async def download_torrent_file(self, url: str, requires_auth: bool = False) -> bytes:
    if requires_auth:
        # Use AsyncRuTrackerClient for authenticated download
        ...
    else:
        # Use regular HTTP download
        ...
```

### Validator (`app/torrent/validator.py`)

```python
async def validate_torrent(
    self, 
    magnet_or_file: str, 
    download_metadata: DownloadMetadata, 
    requires_auth: bool = False  # NEW PARAMETER
) -> ValidationResult:
    torrent_file_path = None
    try:
        if magnet_or_file.startswith("http"):
            # Download with auth flag
            torrent_file_path = await self._download_torrent_file(
                magnet_or_file, requires_auth
            )
            torrent_info = await self.metadata_fetcher.fetch_from_file(torrent_file_path)
        
        # ... validation logic ...
        
        # Store file path for reuse
        result.torrent_file_path = torrent_file_path
        return result
    except Exception as e:
        # Clean up only on error
        if torrent_file_path and torrent_file_path.exists():
            torrent_file_path.unlink()
        raise
```

### Downloader (`app/torrent/downloader.py`)

```python
async def add_download(
    self,
    magnet_link: str | None,
    torrent_file_link: str | None,
    name: str,
    metadata: DownloadMetadata,
    validation_result: ValidationResult,
) -> str:
    # ...
    if torrent_file_link:
        # Check for cached file from validation
        if validation_result and validation_result.torrent_file_path:
            logger.info("Using cached torrent file from validation")
            file_path = validation_result.torrent_file_path
        else:
            # Download torrent file
            logger.info("Downloading torrent file")
            # ... download logic ...
```

### TorrentScreen (`app/bot/screens/torrent.py`)

```python
# Pass requires_auth flag from result to validator
validation = await self.validator.validate_torrent(
    magnet_or_file, 
    download_metadata, 
    requires_auth=result.requires_auth  # NEW PARAMETER
)
```

## Benefits

### 1. **Performance**
- ✅ Eliminates redundant network requests (50% reduction in downloads)
- ✅ Faster download initiation (reuses parsed metadata)
- ✅ Reduces bandwidth usage

### 2. **SOLID Principles**
- ✅ **Single Responsibility**: Searcher knows about trackers, validator validates, downloader downloads
- ✅ **Dependency Inversion**: Components depend on abstractions (flags) not implementations (URL parsing)
- ✅ **Open/Closed**: Easy to add new trackers by setting `requires_auth` flag

### 3. **Maintainability**
- ✅ No duplicate URL parsing logic
- ✅ Tracker-specific logic centralized in searcher
- ✅ Clear data flow through the system
- ✅ Easy to add new tracker types

### 4. **Resource Management**
- ✅ Explicit file lifecycle management
- ✅ Clean up on errors
- ✅ Reuse validated resources

## Testing

Verified that:
- ✅ Models accept new fields correctly
- ✅ RuTracker results have `requires_auth=True`
- ✅ Validator caches torrent file
- ✅ Downloader reuses cached file
- ✅ Fallback download works if cache missing
- ✅ Cleanup happens on validation errors

## Future Enhancements

1. **Tracker Registry**: Create a tracker registry pattern for different tracker types
2. **Cache Management**: Implement automatic cleanup of old validation cache files
3. **Progress Tracking**: Show validation progress for large torrent files
4. **Retry Logic**: Add retry mechanism for failed authentication

## Migration Notes

- No database migrations required (dataclass changes only)
- Backward compatible (new fields have defaults)
- No user-facing changes (internal optimization)

## Related Files

- `app/library/models.py` - Data models
- `app/torrent/searcher.py` - Torrent search and download
- `app/torrent/validator.py` - Torrent validation
- `app/torrent/downloader.py` - Torrent download management
- `app/bot/screens/torrent.py` - Torrent UI screen

