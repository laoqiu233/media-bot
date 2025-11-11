"""Constants for callback data used across bot screens."""

# Main Menu callbacks
MAIN_MENU_SEARCH = "main_menu:search:"
MAIN_MENU_LIBRARY = "main_menu:library:"
MAIN_MENU_DOWNLOADS = "main_menu:downloads:"
MAIN_MENU_PLAYER = "main_menu:player:"
MAIN_MENU_TV = "main_menu:tv:"
MAIN_MENU_STATUS = "main_menu:status:"

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
LIBRARY_SERIES = "library:series:"
LIBRARY_MOVIES_PREV = "library:movies_prev:"
LIBRARY_MOVIES_NEXT = "library:movies_next:"
LIBRARY_SERIES_PREV = "library:series_prev:"
LIBRARY_SERIES_NEXT = "library:series_next:"
LIBRARY_SCAN = "library:scan:"
LIBRARY_PLAY_MOVIE = "library:play_movie:"  # Followed by movie_id
LIBRARY_VIEW_SERIES = "library:view_series:"  # Followed by series_id

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
