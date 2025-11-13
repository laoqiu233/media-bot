from app.bot.screens import (
    AudioOutputSelectionScreen,
    AudioTrackSelectionScreen,
    DownloadsScreen,
    HDMIPortSelectionScreen,
    LibraryScreen,
    MainMenuScreen,
    MovieSelectionScreen,
    PlayerScreen,
    ResolutionSelectionScreen,
    RuTrackerAuthScreen,
    Screen,
    SearchScreen,
    SetupConfirmationScreen,
    StatusScreen,
    SystemControlScreen,
    TorrentScreen,
    TVScreen,
)
from app.library.imdb_client import IMDbClient
from app.library.manager import LibraryManager
from app.player.mpv_controller import MPVController
from app.torrent.downloader import TorrentDownloader
from app.torrent.metadata_fetcher import TorrentMetadataFetcher
from app.torrent.searcher import TorrentSearcher
from app.torrent.validator import TorrentValidator
from app.tv.hdmi_cec import CECController


class ScreenRegistry:
    def __init__(
        self,
        library_manager: LibraryManager,
        mpv_controller: MPVController,
        cec_controller: CECController,
        torrent_searcher: TorrentSearcher,
        torrent_downloader: TorrentDownloader,
        imdb_client: IMDbClient,
    ):
        # Initialize torrent metadata fetcher and validator
        metadata_fetcher = TorrentMetadataFetcher(torrent_downloader.session)
        validator = TorrentValidator(metadata_fetcher, imdb_client)

        self.main_menu = MainMenuScreen()
        self.search_screen = SearchScreen(imdb_client)
        self.movie_selection_screen = MovieSelectionScreen(imdb_client)
        self.rutracker_auth_screen = RuTrackerAuthScreen()
        self.torrent_screen = TorrentScreen(torrent_searcher, torrent_downloader, validator)
        self.library_screen = LibraryScreen(library_manager, mpv_controller)
        self.downloads_screen = DownloadsScreen(torrent_downloader)
        self.player_screen = PlayerScreen(mpv_controller, cec_controller)
        self.audio_track_selection_screen = AudioTrackSelectionScreen(mpv_controller)
        self.status_screen = StatusScreen(
            mpv_controller, cec_controller, torrent_downloader, library_manager
        )
        self.tv_screen = TVScreen(cec_controller)
        self.setup_confirmation_screen = SetupConfirmationScreen()
        self.system_control_screen = SystemControlScreen()
        self.hdmi_port_selection_screen = HDMIPortSelectionScreen()
        self.resolution_selection_screen = ResolutionSelectionScreen()
        self.audio_output_selection_screen = AudioOutputSelectionScreen()
        self.screens = [
            self.main_menu,
            self.search_screen,
            self.movie_selection_screen,
            self.rutracker_auth_screen,
            self.torrent_screen,
            self.library_screen,
            self.downloads_screen,
            self.player_screen,
            self.audio_track_selection_screen,
            self.status_screen,
            self.tv_screen,
            self.setup_confirmation_screen,
            self.system_control_screen,
            self.hdmi_port_selection_screen,
            self.resolution_selection_screen,
            self.audio_output_selection_screen,
        ]
        self.screens_by_name = {screen.get_name(): screen for screen in self.screens}

    def get_screen_or_throw(self, screen_name: str) -> Screen:
        if screen_name not in self.screens_by_name:
            raise ValueError(f"Screen not found: {screen_name}")
        return self.screens_by_name[screen_name]
