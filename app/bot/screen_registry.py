from app.bot.screens import (
    DownloadsScreen,
    LibraryScreen,
    MainMenuScreen,
    PlayerScreen,
    Screen,
    SearchScreen,
    StatusScreen,
    TVScreen,
)
from app.library.manager import LibraryManager
from app.player.mpv_controller import MPVController
from app.torrent.downloader import TorrentDownloader
from app.torrent.searcher import TorrentSearcher
from app.tv.hdmi_cec import CECController


class ScreenRegistry:
    def __init__(
        self,
        library_manager: LibraryManager,
        mpv_controller: MPVController,
        cec_controller: CECController,
        torrent_searcher: TorrentSearcher,
        torrent_downloader: TorrentDownloader,
    ):
        self.main_menu = MainMenuScreen()
        self.search_screen = SearchScreen(torrent_searcher, torrent_downloader)
        self.library_screen = LibraryScreen(library_manager, mpv_controller)
        self.downloads_screen = DownloadsScreen(torrent_downloader)
        self.player_screen = PlayerScreen(mpv_controller)
        self.status_screen = StatusScreen(mpv_controller, cec_controller, torrent_downloader)
        self.tv_screen = TVScreen(cec_controller)
        self.screens = [
            self.main_menu,
            self.search_screen,
            self.library_screen,
            self.downloads_screen,
            self.player_screen,
            self.status_screen,
            self.tv_screen,
        ]
        self.screens_by_name = {screen.get_name(): screen for screen in self.screens}

    def get_screen_or_throw(self, screen_name: str) -> Screen:
        if screen_name not in self.screens_by_name:
            raise ValueError(f"Screen not found: {screen_name}")
        return self.screens_by_name[screen_name]
