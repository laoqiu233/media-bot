# Media Bot - Memory Bank

## Technical Documentation and Architecture Notes

**Project**: Media Bot - Smart Raspberry Pi Media Center  
**Purpose**: Hackathon project for automated media discovery, download, and playback  
**Platform**: Raspberry Pi with HDMI-CEC TV control  
**Interface**: Telegram Bot with Screen-Based UI System  
**Author**: Dmitri Tsiu <laoqiu1015@gmail.com>  
**Python Version**: 3.11+  
**Architecture**: Modern async Python with Pydantic 2.x

---

## Architecture Overview

### System Components

```
┌──────────────────────────────────────────────────────────┐
│                    Telegram Bot                          │
│                  (python-telegram-bot)                   │
└─────────────────────┬────────────────────────────────────┘
                      │
         ┌────────────▼────────────────────┐
         │   Session Manager               │
         │   - Per-user sessions           │
         │   - Screen navigation           │
         │   - Auto-refresh (0.5s)         │
         └────────────┬────────────────────┘
                      │
         ┌────────────▼────────────────────┐
         │   Screen Registry               │
         │   - Main Menu                   │
         │   - Search, Library, Downloads  │
         │   - Player, Status, TV          │
         └────────┬────────────────────────┘
                  │
    ┌─────────────┴──────────────────────────────────┐
    │                                                  │
┌───▼──────────┐                          ┌───────────▼──────┐
│ Library Mgr  │                          │ Torrent System   │
│  - Movies    │                          │  - YTS Searcher  │
│  - Series    │                          │  - Downloader    │
│  - Episodes  │                          │  - libtorrent    │
│  - Metadata  │                          │  - Auto-import   │
└──────┬───────┘                          └────────┬─────────┘
       │                                           │
    ┌──┴───────────────────────────────────────────┴────┐
    │                                                    │
┌───▼─────────┐  ┌──────────────┐  ┌─────────────┐  ┌──▼──────────┐
│ MPV Player  │  │  HDMI-CEC    │  │  Scheduler  │  │    Auth     │
│  - Control  │  │  - TV On/Off │  │  - Progress │  │  - Username │
│  - Events   │  │  - Commands  │  │  - Episodes │  │  - Secure   │
└─────────────┘  └──────────────┘  └─────────────┘  └─────────────┘
```

---

## Technology Stack

### Core Technologies

- **Python 3.11+**: Main programming language with modern type hints
- **python-telegram-bot 21.x**: Async Telegram bot framework with job queue
- **Pydantic 2.12.4+**: Data validation, settings, and models
- **aiohttp 3.9+**: Async HTTP client for web scraping
- **asyncio**: Native async/await for concurrent operations
- **python-dotenv**: Environment variable management

### Media & Torrent

- **python-mpv 1.0+**: Python bindings for MPV media player
- **libtorrent 2.0+**: BitTorrent protocol implementation
- **beautifulsoup4 4.12+**: HTML parsing for torrent search
- **lxml 5.0+**: Fast XML/HTML parsing
- **cec-client**: HDMI-CEC control (system command, not Python package)

### Storage & Development

- **aiofiles 23.0+**: Async file I/O operations
- **ruff 0.8+**: Fast Python linter and formatter (dev)
- **Poetry**: Dependency management and packaging

---

## Project Structure

```
media-bot/
├── app/
│   ├── __init__.py
│   ├── __main__.py              # Entry point (python -m app)
│   ├── config.py                # Configuration management
│   │
│   ├── bot/                     # Telegram bot implementation
│   │   ├── __init__.py
│   │   ├── integrated_bot.py    # Main bot orchestrator
│   │   ├── handlers.py          # Bot command handlers
│   │   ├── auth.py              # Authorization system
│   │   ├── session_manager.py   # Manages user sessions
│   │   ├── session.py           # Individual session with auto-refresh
│   │   ├── screen_registry.py   # Screen registry and dependency injection
│   │   ├── callback_data.py     # Callback query constants
│   │   └── screens/             # Screen-based UI system
│   │       ├── __init__.py
│   │       ├── base.py          # Base screen class and context
│   │       ├── main_menu.py     # Main menu screen
│   │       ├── search.py        # Torrent search screen
│   │       ├── library.py       # Library browser screen
│   │       ├── downloads.py     # Download manager screen
│   │       ├── player.py        # Player control screen
│   │       ├── status.py        # System status screen
│   │       └── tv.py            # TV control screen
│   │
│   ├── library/                 # Media library management
│   │   ├── __init__.py
│   │   ├── manager.py           # Library manager with filesystem storage
│   │   └── models.py            # Pydantic models for media
│   │
│   ├── torrent/                 # Torrent system
│   │   ├── __init__.py
│   │   ├── searcher.py          # Multi-source torrent searcher
│   │   └── downloader.py        # libtorrent download manager
│   │
│   ├── player/                  # Media player
│   │   ├── __init__.py
│   │   └── mpv_controller.py    # MPV player controller (singleton)
│   │
│   ├── scheduler/               # Series tracking
│   │   ├── __init__.py
│   │   └── series_scheduler.py  # Watch progress and recommendations
│   │
│   └── tv/                      # TV control
│       ├── __init__.py
│       └── hdmi_cec.py          # HDMI-CEC controller
│
├── pyproject.toml               # Poetry project configuration
├── poetry.lock                  # Locked dependencies
├── Makefile                     # Development commands
├── README.md                    # Basic usage instructions
└── MEMORY_BANK.md               # This file (architecture documentation)
```

---

## Key Architectural Decisions

### 1. Screen-Based UI System

**Decision**: Implement a screen-based navigation system for Telegram bot  
**Rationale**:
- Clean separation of UI concerns
- Reusable screen components
- Centralized state management per session
- Easy to add new screens
- Better testability and maintainability

**Implementation**:
- Each screen extends `Screen` base class
- Screens implement: `render()`, `handle_callback()`, `handle_message()`
- Navigation via `Navigation` objects returned from handlers
- Context system for passing data between screens
- Lifecycle hooks: `on_enter()`, `on_exit()`

**Example Screen Structure**:
```python
class MyScreen(Screen):
    def get_name(self) -> str:
        return "my_screen"
    
    async def render(self, context: Context) -> ScreenRenderResult:
        text = "Screen content"
        keyboard = InlineKeyboardMarkup([...])
        return (text, keyboard)
    
    async def handle_callback(self, query: CallbackQuery, context: Context) -> ScreenHandlerResult:
        if query.data == "next":
            return Navigation(next_screen="other_screen", param="value")
        return None
```

### 2. Session Management with Auto-Refresh

**Decision**: Per-user sessions with automatic 0.5s refresh rate  
**Rationale**:
- Real-time updates for downloads, playback status
- Smooth user experience without manual refresh
- Automatic cleanup after 5 minutes of inactivity
- Prevents Telegram edit conflicts with lock mechanism

**Features**:
- Each user gets isolated session with own state
- Auto-refresh task runs in background
- Smart diffing prevents unnecessary updates
- Activity tracking stops refresh after idle period
- Render lock prevents concurrent edit operations

### 3. Filesystem-Based Storage

**Decision**: JSON metadata files with filesystem organization  
**Rationale**:
- Simple and portable
- No database setup required
- Easy to inspect and debug
- Suitable for Raspberry Pi resource constraints
- Direct file access for media playback

**Structure**:
```
media_library/
├── movies/
│   └── Movie Title (2024)/
│       ├── movie.mp4
│       └── metadata.json
├── series/
│   └── Series Name/
│       ├── Season 01/
│       │   ├── S01E01.mp4
│       │   └── metadata.json (optional)
│       └── series_metadata.json
└── data/
    └── watch_progress.json
```

### 4. Authorization System

**Decision**: Username-based authorization with silent rejection  
**Rationale**:
- Secure access control
- Simple configuration via environment variables
- No response to unauthorized users (stealth)
- Supports multiple authorized users

**Configuration**:
```bash
AUTHORIZED_USERS=username1,username2,username3
```

### 5. Component Integration Architecture

**Decision**: Centralized component initialization in `integrated_bot.py`  
**Rationale**:
- Single initialization point
- Clear dependency injection via ScreenRegistry
- Proper cleanup on shutdown
- Testable components

**Flow**:
1. Load configuration from environment
2. Initialize all system components
3. Set up download completion callbacks
4. Create Telegram application
5. Register handlers and start polling
6. Clean up on shutdown

### 6. Async-First Design

**Decision**: Full async/await throughout the codebase  
**Rationale**:
- Non-blocking I/O for Telegram, HTTP, file operations
- Better resource utilization on Raspberry Pi
- Natural fit with python-telegram-bot async API
- Efficient handling of multiple concurrent operations

---

## Configuration Management

### Config System (config.py)

**Pydantic-based configuration** with environment variable loading:

```python
class Config(BaseModel):
    telegram: TelegramConfig
    media_library: MediaLibraryConfig
    mpv: MPVConfig
    cec: CECConfig
    logging: LoggingConfig
```

### Environment Variables

Required:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

Optional (with defaults):
```bash
# Authorization
AUTHORIZED_USERS=username1,username2

# Paths
MEDIA_LIBRARY_PATH=/home/pi/media_library
DOWNLOAD_PATH=/home/pi/downloads

# MPV Configuration
MPV_VO=gpu
MPV_AO=alsa

# CEC Configuration
CEC_ENABLED=true
CEC_DEVICE=/dev/cec0

# Logging
LOG_LEVEL=INFO
```

---

## Component APIs

### Library Manager (library/manager.py)

**Filesystem-based media library with automatic scanning**

```python
library = LibraryManager(library_path)

# Scan and load library
await library.scan_library()  # Returns (movies_count, series_count)

# Search
results = await library.search("query", media_type=MediaType.MOVIE)

# Add media
movie = await library.add_movie(title, file_path, year, genres)
series = await library.add_series(title, year, genres)

# Retrieve
movie = await library.get_movie(movie_id)
series = await library.get_series(series_id)
all_movies = await library.get_all_movies()
all_series = await library.get_all_series()

# Import from download
movie = await library.import_from_download(download_path, torrent_name)
```

**Features**:
- Automatic metadata creation from folder structure
- Episode scanning with regex parsing (S01E01 format)
- Quality detection from filenames
- In-memory caching for fast access
- Automatic file moving to library on import

### Torrent System

**Searcher** (torrent/searcher.py):
```python
searcher = TorrentSearcher()

# Search across sources (currently YTS API)
results = await searcher.search("movie name", limit=20)
# Returns List[TorrentSearchResult] sorted by seeders
```

**Features**:
- YTS API integration (fast and reliable)
- Quality detection (720p, 1080p, 4K)
- Automatic magnet link generation
- Extensible for additional sources (ThePirateBay template included)

**Downloader** (torrent/downloader.py):
```python
downloader = get_downloader(download_path)
downloader.set_completion_callback(on_complete_callback)
downloader.start_monitoring()

# Add download
task_id = await downloader.add_download(magnet_link, name)

# Monitor status
task = await downloader.get_task_status(task_id)
all_tasks = await downloader.get_all_tasks()

# Control
await downloader.pause_download(task_id)
await downloader.resume_download(task_id)
await downloader.remove_download(task_id, delete_files=False)

# Get completed download path
path = downloader.get_download_path(task_id)
```

**Features**:
- libtorrent 1.x and 2.x API compatibility
- Background monitoring task (2s interval)
- DHT router configuration
- Completion callbacks for auto-import
- Progress tracking with ETA calculation
- Pause/resume/remove support

### MPV Player (player/mpv_controller.py)

**Singleton pattern for player control**

```python
player = MPVController()  # Global instance
player.initialize(vo="gpu", ao="alsa", fullscreen=True, hwdec="auto")

# Playback control
await player.play(file_path)
await player.pause()
await player.resume()
await player.stop()
await player.toggle_pause()

# Seeking and volume
await player.seek(seconds, relative=True)
await player.set_volume(50)
await player.volume_up(step=5)
await player.volume_down(step=5)

# Subtitles and audio
await player.load_subtitle(subtitle_path)
await player.cycle_subtitle()
await player.cycle_audio()

# Status
status = await player.get_status()
position = await player.get_position()
duration = await player.get_duration()
volume = await player.get_volume()
is_playing = player.is_playing()
current_file = player.get_current_file()

# Event handling
player.on("time_update", callback)
player.on("playback_finished", callback)
player.on("file_loaded", callback)
```

**Features**:
- Hardware decoding support (hwdec=auto)
- Event system for playback monitoring
- Thread-safe with async locks
- Graceful shutdown
- Property observers for time position

### HDMI-CEC (tv/hdmi_cec.py)

**HDMI-CEC TV control via cec-client**

```python
cec = get_cec_controller(cec_device="/dev/cec0", enabled=True)

# Check availability
available = await cec.check_availability()

# TV control
await cec.tv_on()
await cec.tv_off()
await cec.set_active_source()

# Power status
status = await cec.get_power_status()  # "on", "standby", or None
is_on = await cec.is_tv_on()

# Volume control
await cec.set_volume(level)
await cec.volume_up()
await cec.volume_down()
await cec.mute()

# Device management
devices = await cec.scan_devices()
osd_name = await cec.get_osd_name()
status = await cec.get_status()
await cec.send_key(key_code)
```

**Features**:
- Automatic cec-client availability detection
- Command timeout handling (5s default)
- Async subprocess execution
- Error handling and logging
- Device scanning and status checking

### Series Scheduler (scheduler/series_scheduler.py)

**Watch progress tracking and episode management**

```python
scheduler = get_scheduler(data_dir)
await scheduler.load_progress()

# Track progress
await scheduler.update_progress(user_id, media_id, position, duration, completed)

# Get progress
progress = await scheduler.get_progress(user_id, media_id)
user_progress = await scheduler.get_user_progress(user_id)

# Series tracking
next_ep = await scheduler.get_next_episode(user_id, series)
series_progress = await scheduler.get_series_progress(user_id, series)
await scheduler.mark_episode_watched(user_id, episode)

# Continue watching
continue_list = await scheduler.get_continue_watching(user_id)

# Recommendations
watching = await scheduler.get_watching_series(user_id)
recommendations = await scheduler.get_recommendations_for_user(
    user_id, all_series, limit=5
)
```

**Features**:
- JSON-based persistent storage
- Per-user progress tracking
- Next episode detection
- Continue watching list (filters >5% progress)
- Genre-based recommendations
- Series completion percentage

### Session Manager (bot/session_manager.py)

**Manages user sessions and screen navigation**

```python
session_manager = SessionManager(bot, screen_registry)

# Get or create session
session = await session_manager.get_session(chat_id)

# Session lifecycle
await session_manager.restart_session(chat_id)
await session_manager.stop_session(chat_id)

# Event handling (called by bot handlers)
await session_manager.handle_callback(chat_id, callback_query)
await session_manager.handle_message(chat_id, message)
```

**Features**:
- Automatic session creation
- Screen state management
- Context isolation per user
- Clean session shutdown

### Authorization (bot/auth.py)

**Username-based access control**

```python
# Initialize
auth_manager = init_auth(["username1", "username2"])

# Check authorization
is_auth = auth_manager.is_authorized(update)

# Decorator for handlers
@auth_manager.authorization_required
async def handler(update, context):
    # Only authorized users reach here
    pass
```

**Features**:
- Username normalization (lowercase, @ removal)
- Silent rejection of unauthorized users
- Logging of access attempts
- Global instance management

---

## Data Models

### Media Models (library/models.py)

**Pydantic 2.x models with validation**

**MediaItem** (base class):
- `id`: Unique identifier (UUID)
- `title`: Display title
- `original_title`: Original language title
- `year`: Release year
- `genres`: List[Genre]
- `description`: Plot description
- `media_type`: MediaType enum
- `file_path`: Path to video file
- `poster_path`: Path to poster image
- `duration`: Duration in seconds
- `quality`: VideoQuality enum
- `file_size`: Size in bytes
- `added_date`: When added to library
- `last_watched`: Last watch timestamp
- `watch_count`: Number of times watched
- `rating`: User rating (0-10)
- `imdb_id`, `tmdb_id`: External IDs

**Movie** (extends MediaItem):
- `director`: Director name
- `cast`: List of main actors

**Episode** (extends MediaItem):
- `series_id`: Parent series ID
- `season_number`: Season number
- `episode_number`: Episode number
- `episode_title`: Episode-specific title
- `air_date`: Original air date

**Series**:
- `id`: Unique identifier
- `title`: Series title
- `original_title`: Original title
- `year`: First air year
- `genres`: List[Genre]
- `description`: Series description
- `poster_path`: Poster image path
- `status`: "ongoing" or "ended"
- `total_seasons`: Season count
- `total_episodes`: Episode count
- `episodes`: List[Episode]
- `imdb_id`, `tmdb_id`: External IDs
- `added_date`: When added

**TorrentSearchResult**:
- `title`: Torrent title
- `magnet_link`: Magnet URI
- `size`: Human-readable size
- `size_bytes`: Size in bytes
- `seeders`: Seeder count
- `leechers`: Leecher count
- `source`: Source site name
- `upload_date`: Upload date
- `quality`: Detected video quality

**DownloadTask**:
- `id`: Task identifier
- `torrent_name`: Display name
- `magnet_link`: Magnet URI
- `status`: "queued", "downloading", "paused", "completed", "error"
- `progress`: Progress 0-100
- `download_speed`: Bytes/sec
- `upload_speed`: Bytes/sec
- `seeders`, `peers`: Peer counts
- `downloaded_bytes`: Downloaded size
- `total_bytes`: Total size
- `eta`: Estimated time in seconds
- `save_path`: Download location
- `created_at`: Creation timestamp
- `completed_at`: Completion timestamp
- `error_message`: Error details if failed

**UserWatchProgress**:
- `user_id`: Telegram user ID
- `media_id`: Media item ID
- `position`: Last position in seconds
- `duration`: Total duration
- `last_watched`: Last watch time
- `completed`: Completion flag
- `progress_percentage`: Calculated property

**Enums**:
- `MediaType`: MOVIE, SERIES, EPISODE
- `VideoQuality`: SD, HD_720, HD_1080, UHD_4K, UNKNOWN
- `Genre`: ACTION, COMEDY, DRAMA, HORROR, SCIFI, THRILLER, DOCUMENTARY, ANIMATION, FANTASY, ROMANCE, CRIME, OTHER

---

## Bot UI Screens

### Available Screens

1. **Main Menu** (`main_menu.py`)
   - Central navigation hub
   - Access to all features
   - Clean button layout

2. **Search** (`search.py`)
   - Torrent search interface
   - Displays results with quality/seeders
   - Download initiation

3. **Library** (`library.py`)
   - Browse movies and series
   - Play media items
   - Rescan library

4. **Downloads** (`downloads.py`)
   - Active download monitoring
   - Progress bars and speeds
   - Pause/resume/cancel controls

5. **Player** (`player.py`)
   - Playback controls
   - Seek forward/backward
   - Volume control
   - Stop playback

6. **Status** (`status.py`)
   - System status overview
   - CEC availability
   - Player status
   - Download statistics

7. **TV Control** (`tv.py`)
   - TV power on/off
   - Volume controls
   - Input source switching

### Screen Navigation Flow

```
Main Menu
├── Search → (results) → Download → Main Menu
├── Library → (movies/series) → Play → Player → Main Menu
├── Downloads → (task list) → Control → Downloads
├── Player → (controls) → Player
├── Status → (info) → Main Menu
└── TV → (controls) → TV
```

---

## Bot Commands and Interactions

### User Commands

- `/start` - Initialize session and show main menu

### Interaction Model

- **Button-based navigation**: All interactions via inline keyboard buttons
- **Auto-deleting messages**: User text messages auto-delete after processing
- **Screen persistence**: Current screen message is edited in-place
- **Real-time updates**: Auto-refresh every 0.5 seconds
- **Context-aware**: Each screen maintains its own context

### Callback Data Structure

Defined in `bot/callback_data.py`:
- Main menu actions: `MAIN_MENU_SEARCH`, `MAIN_MENU_LIBRARY`, etc.
- Screen-specific actions: prefixed by screen name
- Parameters encoded in callback data where needed

---

## Raspberry Pi Deployment

### Hardware Requirements

- **Raspberry Pi 4** (recommended) or Pi 3B+
- **Minimum 2GB RAM** (4GB recommended for 4K)
- **32GB+ SD card** or external storage
- **HDMI-CEC compatible TV**
- **Network connection** (Wi-Fi or Ethernet)

### System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install -y python3.11 python3-pip

# Install MPV and dependencies
sudo apt install -y libmpv-dev mpv

# Install CEC utilities
sudo apt install -y cec-utils

# Install libtorrent dependencies
sudo apt install -y build-essential libboost-all-dev
sudo apt install -y python3-libtorrent

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -
```

### Enable HDMI-CEC

Edit `/boot/config.txt`:
```bash
sudo nano /boot/config.txt
```

Add line:
```
dtoverlay=vc4-kms-v3d,cec
```

Reboot:
```bash
sudo reboot
```

### Project Setup

```bash
# Clone repository
git clone <repo-url> media-bot
cd media-bot

# Install dependencies with Poetry
poetry install

# Create .env file
cp .env.example .env
nano .env  # Configure your settings
```

### Environment Configuration (.env)

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather

# Authorization (comma-separated usernames without @)
AUTHORIZED_USERS=yourusername,anotherusername

# Paths
MEDIA_LIBRARY_PATH=/home/pi/media_library
DOWNLOAD_PATH=/home/pi/downloads

# MPV (defaults are good for RPi)
MPV_VO=gpu
MPV_AO=alsa

# CEC
CEC_ENABLED=true
CEC_DEVICE=/dev/cec0

# Logging
LOG_LEVEL=INFO
```

### Running the Bot

**Development**:
```bash
# Using Make
make run

# Using Poetry directly
poetry run python -m app

# Activate venv and run
poetry shell
python -m app
```

**Production (systemd service)**:

Create `/etc/systemd/system/media-bot.service`:
```ini
[Unit]
Description=Media Bot
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/media-bot
ExecStart=/home/pi/media-bot/.venv/bin/python -m app
Restart=on-failure
RestartSec=10
Environment="PATH=/home/pi/media-bot/.venv/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable media-bot
sudo systemctl start media-bot
sudo systemctl status media-bot

# View logs
sudo journalctl -u media-bot -f
```

---

## Development Workflow

### Makefile Commands

```bash
make help         # Show available commands
make install      # Install dependencies
make install-dev  # Install with dev tools
make shell        # Enter virtual environment
make run          # Run the application
make lint         # Run ruff linting checks
make lint-fix     # Auto-fix linting issues
make format       # Format code with ruff
make check        # Run all checks
make clean        # Clean cache files
```

### Code Style

- **Linter**: Ruff (replaces flake8, isort, pyupgrade, etc.)
- **Formatter**: Ruff format (Black-compatible)
- **Line length**: 100 characters
- **Import sorting**: isort style
- **Type hints**: Throughout codebase
- **Docstrings**: Google style

### Ruff Configuration

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]  # Line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

---

## Performance Optimization

### MPV Configuration for Raspberry Pi

**Optimal settings** for hardware acceleration:
```python
player.initialize(
    vo="gpu",           # GPU-accelerated video output
    ao="alsa",          # Direct ALSA audio (low latency)
    hwdec="auto",       # Automatic hardware decoding
    fullscreen=True,
    input_default_bindings=True,
    input_vo_keyboard=True,
    osc=True            # On-screen controller
)
```

**Codec Support**:
- H.264: Full hardware decoding (best performance)
- H.265/HEVC: Hardware decoding on RPi 4
- VP9: Software decoding (may struggle with 4K)
- AV1: Software only (not recommended)

### Torrent Download Optimization

**libtorrent automatic optimization**:
- DHT for trackerless torrents
- Connection limits auto-adjusted
- Upload rate managed automatically
- Multiple routers for better peer discovery

**Best practices**:
- Download during off-peak hours
- Choose torrents with high seeders
- Use wired connection for better speeds
- Consider external storage for large downloads

### Library Scanning Performance

**First scan** can take time with large libraries:
- Results cached in memory
- Subsequent accesses are instant
- Manual rescan via Library screen
- Automatic scan on startup

**Optimization tips**:
- Keep metadata files in place
- Use consistent naming conventions
- Organize by folders (automatic detection)
- Avoid too many files in single directory

### Session Auto-Refresh

**Background refresh** optimized to prevent overload:
- 0.5s refresh interval
- Smart diffing prevents unnecessary updates
- Auto-stops after 5 minutes of inactivity
- Render lock prevents concurrent edits
- Minimal Telegram API calls

---

## Known Limitations

### Current Limitations

1. **CEC Compatibility**: Varies by TV manufacturer
   - Test with: `echo 'scan' | cec-client -s -d 1`
   - Alternative names: Anynet+ (Samsung), Bravia Sync (Sony), SimpLink (LG)

2. **Hardware Decoding**: Some codecs lack HW acceleration
   - Use H.264 for best compatibility
   - 4K requires RPi 4 with 4GB+ RAM

3. **Torrent Sources**: Currently only YTS (movies)
   - Template for ThePirateBay included
   - Extensible architecture for more sources

4. **Single User Sessions**: No multi-device support
   - One active session per user
   - New /start command resets session

5. **Video Formats**: Depends on MPV codec support
   - Best: MP4, MKV with H.264/H.265
   - Avoid: ProRes, DNxHD (too heavy for RPi)

6. **Network Dependency**: Requires constant internet
   - For Telegram bot API
   - For torrent downloads
   - Local playback works offline

---

## Security Considerations

### Authorization System

- **Username-based**: Simple but effective
- **Silent rejection**: No response to unauthorized users
- **Logged attempts**: All unauthorized access logged
- **Configuration**: Via environment variables

### Best Practices

1. **Environment variables**: Never commit `.env` to git
2. **Authorized users**: Use unique, non-obvious usernames
3. **Bot token**: Keep secret, rotate if compromised
4. **File permissions**: Restrict access to media directories
5. **Network**: Use firewall rules on Raspberry Pi
6. **Updates**: Keep system and dependencies updated

### Telegram Bot Security

- **Private bot**: Only authorized users can interact
- **No data stored**: No sensitive info in bot messages
- **Local processing**: All data stays on Raspberry Pi
- **API limits**: Respect Telegram rate limits

---

## Troubleshooting

### Bot Not Responding

**Symptoms**: No messages from bot, commands ignored

**Solutions**:
1. Check bot token: `echo $TELEGRAM_BOT_TOKEN`
2. Verify internet connection: `ping telegram.org`
3. Check logs: `sudo journalctl -u media-bot -f`
4. Restart service: `sudo systemctl restart media-bot`
5. Test bot token: https://api.telegram.org/bot<TOKEN>/getMe

### MPV Playback Issues

**Symptoms**: Black screen, no audio, crashes

**Solutions**:
1. Test MPV directly: `mpv /path/to/video.mp4`
2. Check HDMI connection and TV input
3. Verify video codec: `ffprobe video.mp4`
4. Try software decoding: Set `hwdec="no"` in config
5. Check MPV logs in application output
6. Test different video file

**macOS Development Note**:
- MPV may not display video window on macOS
- This is expected and works fine on Raspberry Pi
- Use logs to verify playback started

### CEC Not Working

**Symptoms**: TV commands have no effect

**Solutions**:
1. Verify CEC device exists: `ls -l /dev/cec*`
2. Test cec-client: `echo 'scan' | cec-client -s -d 1`
3. Check TV CEC settings (often in HDMI settings)
4. Try different HDMI port on TV
5. Enable CEC in `/boot/config.txt` (see setup section)
6. Reboot after config changes
7. Some TVs require manual CEC enable

**CEC Alternative Names**:
- Samsung: Anynet+
- LG: SimpLink
- Sony: Bravia Sync
- Panasonic: HDAVI Control
- Sharp: Aquos Link

### Downloads Stuck at 0%

**Symptoms**: Download shows 0% progress, no peers

**Solutions**:
1. Check magnet link validity
2. Verify internet connection
3. Try torrent with more seeders
4. Check DHT status in logs
5. Verify disk space: `df -h`
6. Check download path permissions
7. Try different torrent source

### Library Not Showing Content

**Symptoms**: Empty library, missing media

**Solutions**:
1. Manual rescan: Library screen → "Scan Library"
2. Check file permissions: `ls -la media_library/`
3. Verify library path in .env
4. Check metadata.json files for errors: `cat metadata.json | jq`
5. Ensure video files have valid extensions (.mp4, .mkv, .avi)
6. Check logs for scanning errors

### Session Errors

**Symptoms**: Commands not working, stuck screen

**Solutions**:
1. Restart session: Send `/start` command
2. Check logs for errors
3. Verify bot is running
4. Check Telegram API status
5. Clear and restart: Stop bot, clear cache, restart

---

## Future Enhancements

### High Priority

- [ ] **TMDB Integration**: Automatic metadata fetching
  - Movie posters and descriptions
  - Series episode information
  - Cast and crew details
  - Ratings and reviews

- [ ] **Subtitle Support**: Automatic subtitle download
  - OpenSubtitles API integration
  - Language selection
  - Subtitle search by file hash

- [ ] **Download Queue**: Better queue management
  - Priority system
  - Bandwidth limits per torrent
  - Scheduled downloads

- [ ] **Disk Space Monitoring**: Automatic cleanup
  - Warn when space low
  - Auto-delete old/watched content
  - Space usage statistics

### Medium Priority

- [ ] **Multi-Device Support**: Multiple sessions per user
  - Sync playback position across devices
  - Session management screen

- [ ] **Episode Auto-Tracking**: Next episode auto-play
  - Remember position across episodes
  - "Continue Watching" queue
  - Season completion notifications

- [ ] **Watchlist and Favorites**: Personal collections
  - Mark favorites
  - Create custom playlists
  - Share lists between users

- [ ] **Multi-Source Torrents**: More search sources
  - 1337x integration
  - RARBG (if available)
  - Combine results from multiple sources

### Low Priority

- [ ] **Web Interface**: Alternative to Telegram bot
  - Full web UI with React
  - Mobile-responsive design
  - Same functionality as bot

- [ ] **Chromecast Support**: Cast to other devices
  - Discover Chromecast devices
  - Stream from RPi to Chromecast

- [ ] **Plex/Jellyfin Integration**: Media server compatibility
  - Export library to Plex/Jellyfin
  - Import watch status
  - Shared metadata

- [ ] **Audio Mode**: Music and podcasts
  - Audio file library
  - Playlist support
  - Audio streaming

- [ ] **Multi-User Features**: Family/friend sharing
  - Separate user profiles
  - User permissions
  - Activity tracking per user

---

## Testing Strategy

### Current Testing Approach

- **Manual testing**: On target hardware (Raspberry Pi)
- **Integration testing**: Real Telegram bot interactions
- **Component testing**: Individual module testing
- **Hardware testing**: CEC and MPV on actual TV

### Recommended Testing

**Unit Tests** (to be implemented):
```python
# Test library scanning
async def test_library_scan():
    library = LibraryManager(test_path)
    movies, series = await library.scan_library()
    assert movies > 0

# Test torrent search
async def test_torrent_search():
    searcher = TorrentSearcher()
    results = await searcher.search("test movie")
    assert len(results) > 0
```

**Integration Tests**:
- Mock Telegram bot for UI testing
- Mock torrent trackers for download testing
- Test data fixtures for library

**Hardware Tests**:
- CEC command verification
- MPV playback testing
- Storage I/O performance

---

## Logging

### Log Levels

```python
LOG_LEVEL=DEBUG  # Detailed debug information
LOG_LEVEL=INFO   # General information (default)
LOG_LEVEL=WARNING  # Warnings only
LOG_LEVEL=ERROR  # Errors only
```

### Log Output

**Format**:
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

**Example**:
```
2025-11-11 10:30:45 - app.library.manager - INFO - Library scanned: 42 movies, 8 series
2025-11-11 10:30:46 - app.torrent.downloader - INFO - Added torrent download: Movie Name
2025-11-11 10:30:50 - app.player.mpv_controller - INFO - Starting playback of: movie.mp4
```

### Log Locations

- **Development**: Console output
- **Production**: systemd journal
  - View: `sudo journalctl -u media-bot -f`
  - Last 100 lines: `sudo journalctl -u media-bot -n 100`
  - Today's logs: `sudo journalctl -u media-bot --since today`

### Important Log Messages

- **Authorization**: Unauthorized access attempts
- **Downloads**: Start, progress, completion
- **Playback**: File loaded, errors
- **CEC**: Command success/failure
- **Errors**: Full stack traces for debugging

---

## Dependencies and Versions

### Production Dependencies

From `pyproject.toml`:

```toml
python = ">=3.11"
pydantic = ">=2.12.4,<3.0.0"
python-telegram-bot[job-queue] = ">=21.0,<22.0"
python-mpv = ">=1.0.0"
aiohttp = ">=3.9.0"
beautifulsoup4 = ">=4.12.0"
lxml = ">=5.0.0"
libtorrent = ">=2.0.0"
python-dotenv = ">=1.0.0"
aiofiles = ">=23.0.0"
```

### Development Dependencies

```toml
ruff = "^0.8.0"  # Linter and formatter
```

### System Dependencies

- **libmpv-dev**: MPV development files
- **mpv**: MPV media player binary
- **cec-utils**: HDMI-CEC command-line tools
- **python3.11**: Python interpreter
- **build-essential**: C/C++ compiler (for libtorrent)

---

## Architecture Patterns Used

### Design Patterns

1. **Singleton Pattern**: MPV controller, downloaders, schedulers
2. **Factory Pattern**: Screen registry, component initialization
3. **Observer Pattern**: Event handlers in MPV, download callbacks
4. **Strategy Pattern**: Different torrent sources
5. **State Pattern**: Screen-based navigation
6. **Dependency Injection**: ScreenRegistry provides dependencies to screens

### Async Patterns

1. **Async Context Managers**: File I/O with aiofiles
2. **Background Tasks**: Download monitoring, screen refresh
3. **Event Loops**: Main bot loop, refresh loops
4. **Locks**: Render lock, initialization lock
5. **Timeouts**: CEC commands, HTTP requests
6. **Cancellation**: Clean task shutdown

### Error Handling

1. **Try-except blocks**: Graceful degradation
2. **Logging**: Comprehensive error logging
3. **Fallbacks**: Disabled features when dependencies unavailable
4. **Validation**: Pydantic model validation
5. **Type Hints**: Static type checking throughout

---

## API Rate Limits and Quotas

### Telegram Bot API

- **Messages**: 30 messages per second per chat
- **Edits**: 30 edits per second per chat
- **Global**: 300 messages per second across all chats

**Mitigation**:
- Smart diffing prevents unnecessary edits
- Debouncing on rapid changes
- Error handling for rate limit errors

### YTS API

- **Rate Limit**: No official limit, be respectful
- **Best Practice**: Cache results, don't hammer API
- **Fallback**: Multiple search sources (future enhancement)

### Torrent DHT

- **No hard limits**: P2P network
- **Best Practice**: Reasonable connection limits
- **Optimization**: libtorrent handles automatically

---

## Credits and License

### Project Information

- **Author**: Dmitri Tsiu
- **Email**: laoqiu1015@gmail.com
- **Purpose**: Hackathon project / Learning exercise
- **Platform**: Raspberry Pi 4
- **Started**: 2025

### Technologies Used

- Python 3.11+
- python-telegram-bot
- Pydantic 2.x
- MPV Media Player
- libtorrent
- aiohttp, BeautifulSoup
- Poetry

### License

[To be determined - currently unlicensed]

### Acknowledgments

- Telegram Bot API community
- MPV player developers
- libtorrent project
- YTS API for movie torrents
- Python async/await ecosystem

---

## Quick Reference

### Essential Commands

```bash
# Development
make run              # Start bot in development
make lint             # Check code quality
make format           # Format code

# Production
sudo systemctl start media-bot    # Start service
sudo systemctl stop media-bot     # Stop service
sudo systemctl restart media-bot  # Restart service
sudo journalctl -u media-bot -f   # View logs

# Testing
echo 'scan' | cec-client -s -d 1  # Test CEC
mpv /path/to/video.mp4            # Test MPV
ping telegram.org                 # Test internet
df -h                             # Check disk space
```

### File Paths (Default)

```
/home/pi/media_library/          # Media library root
/home/pi/media_library/movies/   # Movies
/home/pi/media_library/series/   # TV series
/home/pi/media_library/data/     # Progress data
/home/pi/downloads/              # Torrent downloads
/home/pi/media-bot/              # Bot installation
/home/pi/media-bot/.env          # Configuration
```

### Important URLs

- **Telegram Bot**: https://t.me/YourBotName
- **BotFather**: https://t.me/BotFather (create bot tokens)
- **YTS**: https://yts.mx
- **MPV**: https://mpv.io
- **Raspberry Pi**: https://www.raspberrypi.org

---

## Conclusion

This Memory Bank serves as the comprehensive technical documentation for the Media Bot project. It covers architecture, implementation details, deployment instructions, and troubleshooting guides.

**Key Takeaways**:
- Screen-based UI provides clean, maintainable bot interface
- Full async design optimizes Raspberry Pi resources  
- Filesystem storage keeps things simple and portable
- Component-based architecture allows easy extensibility
- Production-ready with systemd service and error handling

**Next Steps**:
1. Deploy to Raspberry Pi
2. Configure HDMI-CEC with your TV
3. Set up authorized users
4. Start searching and downloading content
5. Enjoy automated media center experience

For questions or contributions, contact: laoqiu1015@gmail.com
