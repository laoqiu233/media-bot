# Media Bot - Memory Bank

## Technical Documentation and Architecture Notes

**Project**: Media Bot - Smart Raspberry Pi Media Center  
**Purpose**: Hackathon project for automated media discovery, download, and playback  
**Platform**: Raspberry Pi with HDMI-CEC TV control  
**Interface**: Telegram Bot

---

## Architecture Overview

### System Components

```
┌──────────────────┐
│  Telegram Bot    │  ← User Interface
└────────┬─────────┘
         │
    ┌────▼─────────────────────────────────┐
    │   MediaBotApplication (Coordinator)   │
    └────┬─────────────────────────────────┘
         │
    ┌────┴──────────────────────────────────┐
    │                                        │
┌───▼──────────┐                   ┌────────▼────────┐
│ Library Mgr  │                   │ Torrent System  │
│  - Movies    │                   │  - Searcher     │
│  - Series    │                   │  - Downloader   │
│  - Metadata  │                   │  - libtorrent   │
└──────────────┘                   └─────────────────┘
         │                                  │
    ┌────┴──────────────────────────────────┴────┐
    │                                             │
┌───▼─────────┐      ┌──────────────┐    ┌──────▼──────┐
│ MPV Player  │      │  HDMI-CEC    │    │  Scheduler  │
│  - Control  │      │  - TV On/Off │    │  - Episodes │
│  - Playback │      │  - Commands  │    │  - Progress │
└─────────────┘      └──────────────┘    └─────────────┘
```

---

## Technology Stack

### Core Technologies

- **Python 3.11+**: Main programming language
- **python-telegram-bot**: Async Telegram bot framework
- **Pydantic 2.x**: Data validation and models
- **aiohttp**: Async HTTP client for web scraping
- **asyncio**: Asynchronous programming

### Media & Torrent

- **python-mpv**: Python bindings for MPV media player
- **libtorrent**: BitTorrent protocol implementation
- **beautifulsoup4 + lxml**: HTML parsing for torrent search
- **cec-client**: HDMI-CEC control (system command)

### Storage

- **Filesystem-based**: No database, JSON metadata files
- **aiofiles**: Async file I/O operations

---

## Technical Decisions

### 1. Storage Architecture

**Decision**: Filesystem-based with JSON metadata  
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

### 2. Torrent Client

**Decision**: libtorrent Python bindings  
**Rationale**:
- Direct Python integration (no external daemon)
- Full control over download parameters
- Good performance on Raspberry Pi
- Active development and support

**Alternative Considered**: transmission-rpc (rejected due to external daemon requirement)

### 3. Video Player

**Decision**: MPV with python-mpv bindings  
**Rationale**:
- Hardware acceleration support (crucial for RPi)
- Excellent codec support
- Low resource usage
- Scriptable via Python API
- Reliable HDMI output

### 4. Bot Framework

**Decision**: python-telegram-bot (async version)  
**Rationale**:
- Most mature and stable
- Excellent async/await support
- Built-in job queue for scheduling
- Active community and documentation
- Type hints and modern Python features

### 5. Web Scraping

**Decision**: Custom scrapers with BeautifulSoup  
**Rationale**:
- No API keys required
- Multiple torrent source support
- Full control over parsing logic
- Resilient to site changes

**Sources**:
- 1337x.to
- ThePirateBay mirrors
- Extensible for additional sources

---

## API References

### Configuration (config.py)

```python
config = load_config()  # Load from environment variables

# Access configuration
config.telegram.bot_token
config.media_library.library_path
config.media_library.download_path
config.mpv.vo  # Video output driver
config.mpv.ao  # Audio output driver
config.cec.enabled
config.cec.device
```

### Library Manager (library/manager.py)

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
```

### Torrent System

**Searcher** (torrent/searcher.py):
```python
searcher = TorrentSearcher()

# Search across multiple sources
results = await searcher.search("movie name", limit=20)
# Returns List[TorrentSearchResult]
```

**Downloader** (torrent/downloader.py):
```python
downloader = get_downloader(download_path)
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
```

### MPV Player (player/mpv_controller.py)

```python
player = MPVController()  # Singleton
player.initialize(vo="gpu", ao="alsa", fullscreen=True, hwdec="auto")

# Playback control
await player.play(file_path)
await player.pause()
await player.resume()
await player.stop()

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
is_playing = player.is_playing()
```

### HDMI-CEC (tv/hdmi_cec.py)

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
await cec.volume_up()
await cec.volume_down()
await cec.mute()

# Device info
devices = await cec.scan_devices()
status = await cec.get_status()
```

### Series Scheduler (scheduler/series_scheduler.py)

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

# Continue watching
continue_list = await scheduler.get_continue_watching(user_id)

# Recommendations
recommendations = await scheduler.get_recommendations_for_user(
    user_id, all_series, limit=5
)
```

---

## Data Models

### Media Models (library/models.py)

**MediaItem** (base class):
- id, title, original_title, year
- genres, description, media_type
- file_path, poster_path
- duration, quality, file_size
- added_date, last_watched, watch_count, rating
- imdb_id, tmdb_id

**Movie** (extends MediaItem):
- director, cast

**Episode** (extends MediaItem):
- series_id, season_number, episode_number
- episode_title, air_date

**Series**:
- id, title, original_title, year
- genres, description, poster_path
- status, total_seasons, total_episodes
- episodes (List[Episode])
- imdb_id, tmdb_id, added_date

**TorrentSearchResult**:
- title, magnet_link, size, size_bytes
- seeders, leechers, source
- upload_date, quality

**DownloadTask**:
- id, torrent_name, magnet_link
- status, progress, download_speed, upload_speed
- seeders, peers, downloaded_bytes, total_bytes
- eta, save_path, created_at, completed_at

---

## Bot Commands

### User Commands

- `/start` - Welcome message and help
- `/help` - Show available commands
- `/search <query>` - Search for torrents
- `/library` - Browse media library
- `/downloads` - View download status
- `/play` - Player controls
- `/tv_on` - Turn TV on via CEC
- `/tv_off` - Turn TV off via CEC
- `/status` - System status

### Callback Actions

**Search**:
- `download_{index}` - Start download
- `search_next` - Next page of results

**Library**:
- `lib_movies` - View movies
- `lib_series` - View series
- `lib_scan` - Rescan library
- `play_movie_{id}` - Play movie
- `view_series_{id}` - View series details

**Player**:
- `player_pause` - Pause playback
- `player_resume` - Resume playback
- `player_stop` - Stop playback
- `player_vol_up` - Increase volume
- `player_vol_down` - Decrease volume
- `player_seek_{seconds}` - Seek relative
- `player_status` - Get current status

---

## Environment Variables

Required in `.env` file:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Optional (with defaults)
MEDIA_LIBRARY_PATH=/home/pi/media_library
DOWNLOAD_PATH=/home/pi/downloads
MPV_VO=gpu
MPV_AO=alsa
CEC_ENABLED=true
CEC_DEVICE=/dev/cec0
LOG_LEVEL=INFO
```

---

## Raspberry Pi Setup Notes

### Hardware Requirements

- **Raspberry Pi 4** (recommended) or Pi 3B+
- **Minimum 2GB RAM** (4GB recommended for 4K)
- **32GB+ SD card** or external storage
- **HDMI-CEC compatible TV**

### System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install system packages
sudo apt install -y python3.11 python3-pip git
sudo apt install -y libmpv-dev mpv
sudo apt install -y cec-utils
sudo apt install -y libtorrent-rasterbar-dev

# Enable CEC
echo "dtoverlay=vc4-kms-v3d,cec" | sudo tee -a /boot/config.txt

# Reboot
sudo reboot
```

### Python Setup

```bash
# Clone repository
git clone <repo-url> media-bot
cd media-bot

# Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Configure environment
cp .env.example .env
nano .env  # Edit with your settings
```

### Running on Boot (systemd)

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

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable media-bot
sudo systemctl start media-bot
sudo systemctl status media-bot
```

---

## Performance Optimization

### MPV Configuration

For best performance on Raspberry Pi:
```python
mpv.initialize(
    vo="gpu",           # GPU-accelerated video output
    ao="alsa",          # Direct ALSA audio
    hwdec="auto",       # Hardware decoding
    fullscreen=True
)
```

### Torrent Settings

libtorrent automatically optimizes for available resources, but you can tune:
- Limit active downloads: `max_active_downloads`
- Connection limits: `connections_limit`
- Upload rate limits: `upload_rate_limit`

### Library Scanning

- First scan can be slow for large libraries
- Results are cached in memory
- Periodic rescans recommended for new content
- Use `/library` → "Scan Library" to refresh

---

## Known Limitations

1. **CEC Support**: Varies by TV manufacturer; test compatibility
2. **Hardware Decoding**: Some codecs may not have HW acceleration
3. **Torrent Sites**: Public sites may be blocked or down
4. **Single User**: No multi-user support in current version
5. **4K Performance**: Requires Pi 4 with 4GB+ RAM

---

## Future Enhancements

### High Priority
- [ ] Automatic subtitle download (OpenSubtitles API)
- [ ] TMDB/IMDB metadata integration
- [ ] Download queue management
- [ ] Disk space monitoring

### Medium Priority
- [ ] Multi-user support with permissions
- [ ] Series episode auto-tracking
- [ ] Watchlist and favorites
- [ ] FTP server for remote access

### Low Priority
- [ ] Web interface (alternative to bot)
- [ ] Chromecast support
- [ ] Plex/Jellyfin integration
- [ ] Audio-only mode for music

---

## Troubleshooting

### Bot Not Responding
1. Check bot token in `.env`
2. Verify internet connection
3. Check logs: `journalctl -u media-bot -f`

### MPV Playback Issues
1. Test MPV directly: `mpv /path/to/video.mp4`
2. Check HDMI connection
3. Verify video codec support
4. Try software decoding: `hwdec="no"`

### CEC Not Working
1. Verify CEC device: `ls /dev/cec*`
2. Test cec-client: `echo 'scan' | cec-client -s -d 1`
3. Check TV CEC settings (may be called "HDMI-CEC", "Anynet+", "Bravia Sync", etc.)
4. Try different HDMI port

### Downloads Stuck
1. Check magnet link validity
2. Verify DHT is working: `session.add_dht_router(...)`
3. Try different torrent source
4. Check disk space

### Library Not Showing Content
1. Run `/library` → "Scan Library"
2. Check file permissions
3. Verify library path in `.env`
4. Check metadata.json files for errors

---

## Development Notes

### Code Style
- PEP 8 compliant
- Type hints throughout
- Async/await for I/O operations
- Docstrings in Google style

### Testing
- Manual testing on target hardware
- Integration testing with real Telegram bot
- Mock torrent sites for development

### Logging
- INFO level for user actions
- DEBUG level for detailed operations
- ERROR level with stack traces
- Configurable via `LOG_LEVEL` env var

---

## Contributors

Developed for hackathon project by [Team Name]

## License

[To be determined]

