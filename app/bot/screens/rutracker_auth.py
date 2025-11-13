"""RuTracker authorization screen."""

import asyncio
import logging
import os
import socket
import subprocess
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    RUTRACKER_AUTH_BACK,
    RUTRACKER_AUTH_CHECK,
    RUTRACKER_AUTH_QR,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.init_flow import ensure_rutracker_credentials


def _project_root() -> Path:
    """Get project root directory."""
    # app/bot/screens/ -> project root
    return Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """Detect a likely reachable local IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _detect_screen_resolution() -> tuple[int, int]:
    """Detect screen resolution, defaulting to 1920x1080 if detection fails."""
    try:
        result = subprocess.run(
            ["xrandr"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if " connected " in line and "x" in line:
                    parts = line.split()
                    for part in parts:
                        if "x" in part and part[0].isdigit():
                            try:
                                w, h = map(int, part.split("x"))
                                if w > 0 and h > 0:
                                    return w, h
                            except ValueError:
                                continue
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    
    # Default to 1920x1080 (common TV resolution)
    return 1920, 1080


def _generate_styled_qr_png(url: str, out_path: Path) -> None:
    """Generate a styled QR code PNG image similar to init_flow.
    
    Args:
        url: URL to encode in QR code
        out_path: Path where to save the PNG image
    """
    # Detect screen resolution for responsive design
    screen_width, screen_height = _detect_screen_resolution()
    
    # Generate QR code with high error correction for mobile scanning
    qr_factory = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=4,
    )
    qr_factory.add_data(url)
    qr_factory.make(fit=True)
    url_qr = qr_factory.make_image(fill_color="black", back_color="white").convert("RGB")
    
    # Responsive sizing based on screen resolution
    base_size = min(screen_width, screen_height) * 0.3  # 30% of smaller dimension
    qr_size = max(int(base_size), 500)  # Minimum 500px for scanning, scales up for TV
    
    # Scale QR code
    url_qr = url_qr.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    
    # Responsive spacing and layout
    scale_factor = min(screen_width / 1920, screen_height / 1080, 1.5)
    padding = int(60 * scale_factor)
    title_height = int(120 * scale_factor)
    label_height = int(70 * scale_factor)
    text_height = int(100 * scale_factor)
    card_border = int(20 * scale_factor)
    
    # Calculate layout
    width = screen_width
    height = screen_height
    
    # Center content
    content_width = padding * 2 + qr_size
    content_height = padding * 2 + title_height + qr_size + label_height + text_height
    
    offset_x = (width - content_width) // 2 if content_width < width else 0
    offset_y = (height - content_height) // 2 if content_height < height else 0
    
    # Create base image with gradient background (matching init_flow style)
    img = Image.new("RGB", (width, height), color=(2, 6, 23))  # #020617
    draw = ImageDraw.Draw(img)
    
    # Fast linear gradient
    step = max(4, height // 200)
    for y in range(0, height, step):
        ratio = y / height if height > 0 else 0
        if ratio < 0.45:
            local_ratio = ratio / 0.45 if 0.45 > 0 else 0
            r = int(30 - (30 - 15) * local_ratio)
            g = int(41 - (41 - 23) * local_ratio)
            b = int(59 - (59 - 42) * local_ratio)
        else:
            local_ratio = (ratio - 0.45) / 0.55 if 0.55 > 0 else 0
            r = int(15 - (15 - 2) * local_ratio)
            g = int(23 - (23 - 6) * local_ratio)
            b = int(42 - (42 - 23) * local_ratio)
        
        draw.rectangle([(0, y), (width, min(y + step, height))], fill=(r, g, b))
    
    # Load fonts
    font_size_title = int(44 * scale_factor)
    font_size_label = int(30 * scale_factor)
    font_size_text = int(24 * scale_factor)
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size_title)
        font_label = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size_label)
        font_text = ImageFont.truetype("DejaVuSans.ttf", font_size_text)
    except Exception:
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size_title)
            font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size_label)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size_text)
        except Exception:
            font_title = ImageFont.load_default()
            font_label = ImageFont.load_default()
            font_text = ImageFont.load_default()
    
    # Title
    title_text = "RuTracker Setup"
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = offset_x + (content_width - title_width) // 2 if content_width < width else (width - title_width) // 2
    title_y = offset_y + padding
    
    # Draw title shadow and main title
    draw.text((title_x + 2, title_y + 2), title_text, fill=(0, 0, 0), font=font_title)
    draw.text((title_x, title_y), title_text, fill=(255, 255, 255), font=font_title)
    
    # Label
    label_text = "Scan QR Code"
    label_bbox = draw.textbbox((0, 0), label_text, font=font_label)
    label_width = label_bbox[2] - label_bbox[0]
    label_x = offset_x + padding + (qr_size - label_width) // 2
    label_y = offset_y + padding + title_height + 20
    
    draw.text((label_x + 1, label_y + 1), label_text, fill=(0, 0, 0), font=font_label)
    draw.text((label_x, label_y), label_text, fill=(255, 255, 255), font=font_label)
    
    # QR code position
    qr_y = offset_y + padding + title_height + label_height + 25
    qr_x = offset_x + padding
    
    # Card background
    card_bg_color = (15, 23, 42)
    card_border_color = (148, 163, 184)
    
    # Draw card shadow
    shadow_offset = int(8 * scale_factor)
    for offset in range(shadow_offset, 0, -2):
        alpha = int(65 * (1 - offset / shadow_offset) ** 0.5)
        if alpha > 0:
            shadow_rect = [
                qr_x - card_border + offset,
                qr_y - card_border + offset,
                qr_x + qr_size + card_border + offset,
                qr_y + qr_size + card_border + offset,
            ]
            shadow_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_overlay)
            shadow_draw.rectangle(shadow_rect, fill=(0, 0, 0, alpha))
            img = Image.alpha_composite(img.convert("RGBA"), shadow_overlay).convert("RGB")
            draw = ImageDraw.Draw(img)
    
    # Draw card background
    card_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card_overlay)
    card_rect = [
        qr_x - card_border,
        qr_y - card_border,
        qr_x + qr_size + card_border,
        qr_y + qr_size + card_border,
    ]
    card_draw.rectangle(card_rect, fill=(*card_bg_color, 235))
    img = Image.alpha_composite(img.convert("RGBA"), card_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Card border
    border_width = max(1, int(scale_factor))
    draw.rectangle(
        [qr_x - card_border, qr_y - card_border,
         qr_x + qr_size + card_border, qr_y + qr_size + card_border],
        outline=card_border_color, width=border_width
    )
    
    # Paste QR code
    img.paste(url_qr, (qr_x, qr_y))
    
    # Text below QR code
    text_y = qr_y + qr_size + int(40 * scale_factor)
    url_text = f"URL:\n{url}"
    url_lines = url_text.split("\n")
    
    line_height = int(36 * scale_factor)
    for i, line in enumerate(url_lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_text)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = qr_x + (qr_size - line_width) // 2
        draw.text((line_x + 2, text_y + i * line_height + 2), line, fill=(0, 0, 0), font=font_text)
        draw.text((line_x, text_y + i * line_height), line, fill=(220, 240, 255), font=font_text)
    
    # Save with maximum quality
    img.save(out_path, quality=100, optimize=False)


async def _load_file_in_mpv(mpv_proc: subprocess.Popen, ipc_socket: Path, file_path: Path) -> None:
    """Load a file in an existing mpv process using IPC.
    
    Args:
        mpv_proc: The mpv process
        ipc_socket: Path to the IPC socket
        file_path: Path to the file to load
    """
    import socket as socket_lib
    import json
    
    # Wait a bit for socket to be ready
    await asyncio.sleep(0.3)
    
    # Check if socket exists
    if not ipc_socket.exists():
        logger.warning(f"IPC socket does not exist: {ipc_socket}")
        return
    
    try:
        # Connect to mpv IPC socket and send loadfile command
        sock = socket_lib.socket(socket_lib.AF_UNIX, socket_lib.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(str(ipc_socket))
        
        # Send loadfile command (JSON will handle escaping)
        command = {"command": ["loadfile", str(file_path), "replace"]}
        command_json = json.dumps(command) + "\n"
        sock.sendall(command_json.encode())
        
        # Read response (optional, but good for debugging)
        try:
            response = sock.recv(1024)
            logger.debug(f"MPV IPC response: {response}")
        except Exception:
            pass
        
        sock.close()
    except Exception as e:
        logger.warning(f"Could not send loadfile command via IPC: {e}")


async def _display_with_mpv(image_path: Path, ipc_socket: Path | None = None, mpv_proc: subprocess.Popen | None = None) -> tuple[subprocess.Popen, Path]:
    """Launch mpv to display the provided image fullscreen in a loop, or load it in existing process.
    
    Returns:
        (process, ipc_socket_path) - The mpv process and IPC socket path
    """
    # If we have an existing process, use IPC to load the new file
    if mpv_proc is not None and ipc_socket is not None and mpv_proc.poll() is None:
        await _load_file_in_mpv(mpv_proc, ipc_socket, image_path)
        # Wait for file to load
        await asyncio.sleep(1.0)
        return mpv_proc, ipc_socket
    
    # Create new mpv process with IPC
    import tempfile
    ipc_socket_path = Path(tempfile.gettempdir()) / f"mpv_rutracker_{os.getpid()}.sock"
    
    cmd = [
        "mpv",
        "--no-terminal",
        "--force-window=yes",
        "--image-display-duration=inf",
        "--loop-file=inf",
        "--fs",
        "--no-border",
        "--no-window-dragging",
        "--no-input-default-bindings",
        "--no-input-vo-keyboard",
        "--keepaspect=no",  # Stretch to fill screen (no black bars)
        "--video-unscaled=no",  # Allow scaling
        "--panscan=1.0",  # Fill screen completely
        "--video-margin-ratio-left=0",
        "--video-margin-ratio-right=0",
        "--video-margin-ratio-top=0",
        "--video-margin-ratio-bottom=0",
        "--fullscreen",
        "--video-zoom=0",  # No zoom
        "--video-pan-x=0",  # No horizontal pan
        "--video-pan-y=0",  # No vertical pan
        "--video-align-x=0",  # Center horizontally
        "--video-align-y=0",  # Center vertically
        f"--input-ipc-server={ipc_socket_path}",
        str(image_path),
    ]
    # Start detached so we can kill later
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for mpv to start and display the image
    # Check process is running and wait for display to be ready
    for _ in range(15):  # Check up to 1.5 seconds to ensure image is visible
        await asyncio.sleep(0.1)
        if proc.poll() is not None:
            # Process exited, something went wrong
            break
    return proc, ipc_socket_path


class RuTrackerAuthScreen(Screen):
    """Screen for RuTracker authorization setup."""

    def __init__(self):
        """Initialize RuTracker auth screen."""
        self._mpv_proc: subprocess.Popen | None = None
        self._mpv_ipc_socket: Path | None = None

    def get_name(self) -> str:
        """Get screen name."""
        return "rutracker_auth"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen.
        
        Expects kwargs:
            movie: IMDbMovie object (for back navigation)
            movies: List of all movies (for back navigation)
            detailed_movies: Dict of detailed movie data (for back navigation)
            query: Search query (for back navigation)
            page: Current page (for back navigation)
        """
        movie = kwargs.get("movie")
        movies = kwargs.get("movies", [])
        detailed_movies = kwargs.get("detailed_movies", {})
        query = kwargs.get("query", "")
        page = kwargs.get("page", 0)
        
        context.update_context(
            movie=movie,
            movies=movies,
            detailed_movies=detailed_movies,
            query=query,
            page=page,
        )
        
        # Start setup server in background if not already running
        if os.environ.get("RUTRACKER_SETUP_ACTIVE") != "1":
            asyncio.create_task(ensure_rutracker_credentials())

    async def on_exit(self, context: Context) -> None:
        """Called when leaving the screen."""
        # Show loading3.gif in the same mpv process, then close it (like init_flow does)
        if self._mpv_proc is not None and self._mpv_proc.poll() is None:
            try:
                project_root = _project_root()
                loading3_path = project_root / "loading3.gif"
                if loading3_path.exists() and self._mpv_ipc_socket is not None:
                    # Load loading3.gif in the same mpv process
                    await _load_file_in_mpv(self._mpv_proc, self._mpv_ipc_socket, loading3_path)
                    logger.info("Loaded loading3.gif in mpv process")
                    # Wait for loading3.gif to be fully visible
                    await asyncio.sleep(1.5)
                
                # Don't stop mpv - let MPV player or system manage it
                # Store PID so MPV player knows loading3.gif is already running
                os.environ["MEDIA_BOT_LOADING_PID"] = str(self._mpv_proc.pid)
                logger.info(f"Leaving mpv process running (PID {self._mpv_proc.pid})")
                self._mpv_proc = None
                self._mpv_ipc_socket = None
            except Exception as e:
                logger.error(f"Error closing QR code display: {e}")
                if self._mpv_proc is not None:
                    try:
                        if self._mpv_proc.poll() is None:
                            self._mpv_proc.kill()
                    except Exception:
                        pass
                    self._mpv_proc = None
                self._mpv_ipc_socket = None

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the RuTracker authorization screen."""
        state = context.get_context()
        movie = state.get("movie")
        
        # Check if credentials are already configured
        tracker_username = os.getenv("TRACKER_USERNAME")
        tracker_password = os.getenv("TRACKER_PASSWORD")
        has_credentials = bool(tracker_username and tracker_password)
        
        # Detect IP and build setup URL
        host_ip = _detect_local_ip()
        setup_url = f"http://{host_ip}:8766/"
        
        text = "🏴‍☠️ *RuTracker Authorization*\n\n"
        
        if has_credentials:
            text += "✅ Credentials are configured.\n\n"
            text += "You can now use RuTracker to search for torrents.\n\n"
            text += "Click 'Continue' to proceed with RuTracker search."
        else:
            text += "⚠️ RuTracker credentials are required.\n\n"
            text += f"Please open this URL in your browser:\n`{setup_url}`\n\n"
            text += "After submitting your credentials, click 'Check Status' to verify."
        
        keyboard = []
        
        if has_credentials:
            # Continue button - proceed to search
            keyboard.append(
                [InlineKeyboardButton("▶️ Continue", callback_data="rutracker_auth:continue:")]
            )
        else:
            # Display QR code button
            keyboard.append(
                [InlineKeyboardButton("📱 Display QR Code", callback_data=RUTRACKER_AUTH_QR)]
            )
            # Check status button
            keyboard.append(
                [InlineKeyboardButton("🔄 Check Status", callback_data=RUTRACKER_AUTH_CHECK)]
            )
        
        # Back button
        keyboard.append([InlineKeyboardButton("« Back", callback_data=RUTRACKER_AUTH_BACK)])
        
        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle callback queries."""
        state = context.get_context()
        
        if query.data == RUTRACKER_AUTH_BACK:
            # Navigate back to provider selection
            return Navigation(
                next_screen="torrent_providers",
                movie=state.get("movie"),
                movies=state.get("movies", []),
                detailed_movies=state.get("detailed_movies", {}),
                query=state.get("query", ""),
                page=state.get("page", 0),
            )
        
        elif query.data == RUTRACKER_AUTH_QR:
            # Generate and display QR code on TV screen (following init_flow pattern)
            host_ip = _detect_local_ip()
            setup_url = f"http://{host_ip}:8766/"
            
            try:
                await query.answer("Displaying QR code on screen...", show_alert=False)
                
                project_root = _project_root()
                
                # Show loading.gif first (like init_flow does)
                loading_path = project_root / "loading.gif"
                if loading_path.exists():
                    # Start mpv with loading.gif (or load it if mpv is already running)
                    self._mpv_proc, self._mpv_ipc_socket = await _display_with_mpv(
                        loading_path, self._mpv_ipc_socket, self._mpv_proc
                    )
                    logger.info("Showing loading.gif before QR code...")
                    await asyncio.sleep(0.5)  # Brief pause
                
                # Prepare QR code image path
                tmp_dir = project_root / ".setup"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                qr_png = tmp_dir / "rutracker_qr.png"
                
                # Generate styled QR code image (like init_flow)
                _generate_styled_qr_png(setup_url, qr_png)
                
                # Load QR code in the same mpv process
                if self._mpv_proc is not None and self._mpv_ipc_socket is not None:
                    await _load_file_in_mpv(self._mpv_proc, self._mpv_ipc_socket, qr_png)
                    logger.info("Loaded QR code in mpv process")
                    # Wait for QR code to be visible
                    await asyncio.sleep(1.5)
                else:
                    # Fallback: start new mpv process if something went wrong
                    self._mpv_proc, self._mpv_ipc_socket = await _display_with_mpv(qr_png)
                    await asyncio.sleep(1.5)
                
                logger.info(f"Displaying RuTracker QR code on screen: {setup_url}")
                
            except Exception as e:
                logger.error(f"Error displaying QR code: {e}", exc_info=True)
                await query.answer("Error displaying QR code", show_alert=True)
            
            # Stay on current screen
            return None
        
        elif query.data == RUTRACKER_AUTH_CHECK:
            # Check if credentials have been loaded
            await query.answer("Checking status...", show_alert=False)
            
            # Reload environment from .env file
            env_path = _project_root() / ".env"
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("TRACKER_USERNAME="):
                        os.environ["TRACKER_USERNAME"] = line.split("=", 1)[1].strip()
                    elif line.startswith("TRACKER_PASSWORD="):
                        os.environ["TRACKER_PASSWORD"] = line.split("=", 1)[1].strip()
            
            tracker_username = os.getenv("TRACKER_USERNAME")
            tracker_password = os.getenv("TRACKER_PASSWORD")
            
            if tracker_username and tracker_password:
                await query.answer("✅ Credentials loaded successfully!", show_alert=True)
                # Re-render screen to show updated status
                return None
            else:
                await query.answer("❌ Credentials not found. Please submit them via the web form.", show_alert=True)
                # Stay on current screen
                return None
        
        elif query.data == "rutracker_auth:continue:":
            # Credentials are configured, proceed to search
            movie = state.get("movie")
            if movie:
                await query.answer("Searching RuTracker...", show_alert=False)
                return Navigation(
                    next_screen="torrent_results",
                    movie=movie,
                    provider="rutracker",
                    movies=state.get("movies", []),
                    detailed_movies=state.get("detailed_movies", {}),
                    query=state.get("query", ""),
                    movie_page=state.get("page", 0),
                )
        
        return None

