"""Constants for callback data used across bot screens."""

# Main Menu callbacks
MAIN_MENU_SEARCH = "main_menu:search:"
MAIN_MENU_LIBRARY = "main_menu:library:"
MAIN_MENU_DOWNLOADS = "main_menu:downloads:"
MAIN_MENU_PLAYER = "main_menu:player:"
MAIN_MENU_TV = "main_menu:tv:"
MAIN_MENU_STATUS = "main_menu:status:"
MAIN_MENU_SYSTEM_CONTROL = "main_menu:system_control:"

# Search screen callbacks
SEARCH_BACK = "search:back:"
SEARCH_PREV_PAGE = "search:prev_page:"
SEARCH_NEXT_PAGE = "search:next_page:"
SEARCH_DOWNLOAD = "search:download:"  # Followed by result index

# Downloads screen callbacks
DOWNLOADS_BACK = "downloads:back:"
DOWNLOADS_SEARCH = "downloads:search:"
DOWNLOADS_PAUSE = "downloads:pause:"  # Followed by task_id
DOWNLOADS_RESUME = "downloads:resume:"  # Followed by task_id
DOWNLOADS_CANCEL = "downloads:cancel:"  # Followed by task_id

# Library screen callbacks
LIBRARY_BACK = "library:back:"
LIBRARY_SHOW_MOVIES = "library:show_movies:"
LIBRARY_SHOW_SERIES = "library:show_series:"
LIBRARY_RESCAN = "library:rescan:"
LIBRARY_SELECT_ENTITY = "library:select_entity:"  # Followed by entity_id
LIBRARY_LIST_VIDEOS = "library:list_videos:"  # Followed by entity_id
LIBRARY_NEXT_PAGE = "library:next_page:"
LIBRARY_PREV_PAGE = "library:prev_page:"
LIBRARY_CLEAR_FILTER = "library:clear_filter:"
LIBRARY_DELETE = "library:delete:"  # Followed by entity_id
LIBRARY_BACK = "library:back"
LIBRARY_PLAY = "library:play"  # Followed by file id

# Player screen callbacks
PLAYER_BACK = "player:back:"
PLAYER_REFRESH = "player:refresh:"
PLAYER_PAUSE = "player:pause:"
PLAYER_RESUME = "player:resume:"
PLAYER_STOP = "player:stop:"
PLAYER_VOL_UP = "player:vol_up:"
PLAYER_VOL_DOWN = "player:vol_down:"
PLAYER_SEEK = "player:seek:"  # Followed by seconds (can be negative)
PLAYER_TRACKS = "player:tracks:"
PLAYER_SUBTITLES = "player:subtitles:"

# Audio track selection callbacks
AUDIO_TRACK_BACK = "audio_track:back:"
AUDIO_TRACK_SELECT = "audio_track:select:"  # Followed by track_id

# Subtitle selection callbacks
SUBTITLE_BACK = "subtitle:back:"
SUBTITLE_SELECT = "subtitle:select:"  # Followed by track_id
SUBTITLE_REMOVE = "subtitle:remove:"

# TV screen callbacks
TV_BACK = "tv:back:"
TV_REFRESH = "tv:refresh:"
TV_ON = "tv:on:"
TV_OFF = "tv:off:"
TV_ACTIVE_SOURCE = "tv:active_source:"
TV_VOL_UP = "tv:vol_up:"
TV_VOL_DOWN = "tv:vol_down:"
TV_MUTE = "tv:mute:"

# Status screen callbacks
STATUS_BACK = "status:back:"

# Setup confirmation screen callbacks
SETUP_CONFIRM = "setup:confirm:"
SETUP_CANCEL = "setup:cancel:"

# System control screen callbacks
SYSTEM_CONTROL_BACK = "system_control:back:"
SYSTEM_CONTROL_SETUP = "system_control:setup:"
SYSTEM_CONTROL_HDMI_PORT = "system_control:hdmi_port:"
SYSTEM_CONTROL_RESOLUTION = "system_control:resolution:"
SYSTEM_CONTROL_AUDIO_OUTPUT = "system_control:audio_output:"

# HDMI port selection callbacks
HDMI_PORT_BACK = "hdmi_port:back:"
HDMI_PORT_SELECT = "hdmi_port:select:"  # Followed by port (0, 1, or auto)

# Resolution selection callbacks
RESOLUTION_BACK = "resolution:back:"
RESOLUTION_SELECT = "resolution:select:"  # Followed by resolution (e.g., "1920x1080")

# Audio output selection callbacks
AUDIO_OUTPUT_BACK = "audio_output:back:"
AUDIO_OUTPUT_SELECT = (
    "audio_output:select:"  # Followed by output type (e.g., "hdmi", "analog", "auto")
)

# Movie selection screen callbacks
MOVIE_SELECT = "movie:select:"  # Followed by movie index
MOVIE_NEXT = "movie:next:"
MOVIE_PREV = "movie:prev:"
MOVIE_BACK = "movie:back:"

MOVIE_SELECT_SEASON = "movie:select_season:"  # Followed by season index
MOVIE_SELECT_EPISODE = "movie:select_episode:"  # Followed by episode index

MOVIE_SEASONS_BACK = "movie:seasons_back:"
MOVIE_SEASONS_PREV = "movie:seasons_prev:"
MOVIE_SEASONS_NEXT = "movie:seasons_next:"
MOVIE_DOWNLOAD_SEASON = "movie:download_season:"  # Followed by season index

MOVIE_EPISODES_BACK = "movie:episodes_back:"
MOVIE_EPISODES_PREV = "movie:episodes_prev:"
MOVIE_EPISODES_NEXT = "movie:episodes_next:"
MOVIE_DOWNLOAD_SERIES = "movie:download_series:"  # Followed by series index

# Torrent provider selection screen callbacks
PROVIDER_SELECT = "provider:select:"  # Followed by provider name

# Torrent results screen callbacks
TORRENT_SELECT = "torrent:select:"  # Followed by result index
TORRENT_NEXT = "torrent:next:"
TORRENT_PREV = "torrent:prev:"
TORRENT_BACK = "torrent:back:"
TORRENT_DOWNLOAD_CONFIRM = "torrent:download_confirm:"  # Confirm download after validation warning
TORRENT_DOWNLOAD_CANCEL = "torrent:download_cancel:"  # Cancel download after validation warning

# RuTracker authorization screen callbacks
RUTRACKER_AUTH_BACK = "rutracker_auth:back:"
RUTRACKER_AUTH_QR = "rutracker_auth:qr:"
RUTRACKER_AUTH_CHECK = "rutracker_auth:check:"
