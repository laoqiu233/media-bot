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
LIBRARY_SEARCH = "library:search:"
LIBRARY_MAIN = "library:main:"
LIBRARY_MOVIES = "library:movies:"
LIBRARY_MOVIES_PREV = "library:movies_prev:"
LIBRARY_MOVIES_NEXT = "library:movies_next:"
LIBRARY_SCAN = "library:scan:"
LIBRARY_FILTER = "library:filter:"
LIBRARY_CLEAR_FILTER = "library:clear_filter:"
LIBRARY_VIEW_MOVIE = "library:view_movie:"  # Followed by movie_id
LIBRARY_PLAY_MOVIE = "library:play_movie:"  # Followed by movie_id
LIBRARY_DELETE_MOVIE = "library:delete_movie:"  # Followed by movie_id
LIBRARY_CONFIRM_DELETE = "library:confirm_delete:"  # Followed by movie_id

# Player screen callbacks
PLAYER_BACK = "player:back:"
PLAYER_LIBRARY = "player:library:"
PLAYER_REFRESH = "player:refresh:"
PLAYER_PAUSE = "player:pause:"
PLAYER_RESUME = "player:resume:"
PLAYER_STOP = "player:stop:"
PLAYER_VOL_UP = "player:vol_up:"
PLAYER_VOL_DOWN = "player:vol_down:"
PLAYER_SEEK = "player:seek:"  # Followed by seconds (can be negative)

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
AUDIO_OUTPUT_SELECT = "audio_output:select:"  # Followed by output type (e.g., "hdmi", "analog", "auto")

# Movie selection screen callbacks
MOVIE_SELECT = "movie:select:"  # Followed by movie index
MOVIE_NEXT = "movie:next:"
MOVIE_PREV = "movie:prev:"
MOVIE_BACK = "movie:back:"

# Torrent provider selection screen callbacks
PROVIDER_SELECT = "provider:select:"  # Followed by provider name

# Torrent results screen callbacks
TORRENT_SELECT = "torrent:select:"  # Followed by result index
TORRENT_NEXT = "torrent:next:"
TORRENT_PREV = "torrent:prev:"
TORRENT_BACK = "torrent:back:"
