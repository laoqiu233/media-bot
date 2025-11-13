"""Initialization flow to configure Telegram bot token via QR + web form.

This module is intentionally separate from the main app logic.
If no TELEGRAM_BOT_TOKEN is found, it:
1) Starts a tiny aiohttp web server with a token input form
2) Generates a QR code for the setup URL
3) Displays the QR code using the system `mpv` player (fullscreen, looping)
4) On submit, writes TELEGRAM_BOT_TOKEN to project's .env, stops mpv, and returns
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Optional
import re
import html

import qrcode
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont


def _project_root() -> Path:
    # app/ -> project root
    return Path(__file__).resolve().parents[1]


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _detect_local_ip() -> str:
    """Detect a likely reachable local IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Connect to a public IP without sending to learn the outbound interface
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _detect_interface_ip(interface_name: str) -> str | None:
    """Try to detect IP bound to a specific interface (e.g., wlan0/wlp2s0/wlo1)."""
    try:
        import fcntl
        import struct

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(
            fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", bytes(interface_name[:15], "utf-8")),
            )[20:24]
        )
    except Exception:
        return None


def _detect_wifi_interface() -> str | None:
    """Detect a Wi‑Fi interface name using nmcli or /sys/class/net."""
    # Prefer nmcli when available
    try:
        proc = subprocess.run(
            ["sudo", "nmcli", "-t", "-f", "DEVICE,TYPE", "dev", "status"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout:
            for line in proc.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    dev, typ = parts[0], parts[1]
                    if typ == "wifi":
                        return dev
    except Exception:
        pass
    # Fallback: look for wireless sysfs
    try:
        for iface_path in Path("/sys/class/net").iterdir():
            if (iface_path / "wireless").exists():
                return iface_path.name
    except Exception:
        pass
    return None


def _wifi_qr_payload(ssid: str, password: str, security: str = "WPA") -> str:
    # WIFI:T:WPA;S:mynetwork;P:mypass;;
    escaped_ssid = ssid.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    escaped_pwd = password.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return f"WIFI:T:{security};S:{escaped_ssid};P:{escaped_pwd};;"


async def _start_web_server(
    host: str, port: int, on_token_saved, ap_ssid: str, ap_password: str
) -> tuple[web.AppRunner, int]:
    """Start a minimal aiohttp server that serves a token form and handles submission.

    Returns:
        (runner, actual_port)
    """
    # Shared state for connection status tracking
    connection_status: dict[str, str | None] = {"status": None, "message": None}
    
    # Very lightweight request logging
    @web.middleware
    async def log_requests(request, handler):
        peer = request.transport.get_extra_info("peername")
        print(f"[http] {request.method} {request.path} from {peer}")
        resp = await handler(request)
        print(f"[http] -> {resp.status} {request.method} {request.path}")
        return resp

    async def handle_index(_request: web.Request) -> web.Response:
        html = _render_template("setup_ap.html", AP_SSID=ap_ssid, AP_PASS=ap_password)
        return web.Response(text=html, content_type="text/html")

    async def handle_ap_continue(_request: web.Request) -> web.Response:
        html = _render_template(
            "setup.html",
            ERROR_BOX="",
            WIFI_SSID="",
            WIFI_PASSWORD="",
            TOKEN="",
        )
        return web.Response(text=html, content_type="text/html")

    async def handle_status(_request: web.Request) -> web.Response:
        """Return current connection status as JSON."""
        status = connection_status.get("status", "idle")
        message = connection_status.get("message")
        
        response_data = {"status": status}
        if message:
            response_data["message"] = message
        
        return web.Response(
            text=json.dumps(response_data),
            content_type="application/json"
        )

    async def handle_scan_wifi(_request: web.Request) -> web.Response:
        """Scan for available Wi‑Fi networks and return as JSON."""
        wifi_iface = _detect_wifi_interface() or "wlan0"
        networks = []
        
        try:
            # Run nmcli scan in executor to avoid blocking
            loop = asyncio.get_event_loop()
            scan_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            )
            
            if scan_result.returncode == 0 and scan_result.stdout:
                seen_ssids = set()
                for line in scan_result.stdout.splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2:
                        ssid = parts[0]
                        if ssid and ssid != "--" and ssid not in seen_ssids:
                            seen_ssids.add(ssid)
                            signal = (parts[1] if len(parts) > 1 else "0")
                            security = (parts[2] if len(parts) > 2 else "")
                            networks.append({
                                "ssid": ssid,
                                "signal": signal,
                                "security": security,
                            })
                
                # Sort by signal strength (descending)
                networks.sort(key=lambda x: int(x.get("signal", 0)), reverse=True)
        except Exception as e:
            print(f"[init] Wi‑Fi scan error: {e}")
        
        return web.Response(
            text=json.dumps({"networks": networks}),
            content_type="application/json"
        )

    async def handle_success(_request: web.Request) -> web.Response:
        """Show success page."""
        html_content = _render_template("setup_success.html")
        return web.Response(text=html_content, content_type="text/html")


    async def handle_submit(request: web.Request) -> web.Response:
        data = await request.post()
        token = (data.get("token") or "")
        wifi_ssid = (data.get("wifi_ssid") or "")
        wifi_password = (data.get("wifi_password") or "")
        
        # Validate input (after stripping)
        if wifi_ssid == '' or wifi_password == '' or token == '':
            error_html = "<div class=\"error\">All fields are required.</div>"
            html_content = _render_template(
                "setup.html",
                ERROR_BOX=error_html,
                WIFI_SSID=wifi_ssid,
                WIFI_PASSWORD=wifi_password,
                TOKEN=token,
            )
            return web.Response(text=html_content, content_type="text/html", status=400)
        
        # Reset status and start connection in background
        connection_status["status"] = "connecting"
        connection_status["message"] = "Initializing connection..."
        
        async def connect_async():
            """Run connection in background task with status updates."""
            try:
                # Create wrapper that updates connection_status
                async def on_token_saved_with_status(t, ssid, pwd):
                    # Update status during connection
                    connection_status["status"] = "connecting"
                    connection_status["message"] = "Connecting to Wi‑Fi network..."
                    
                    result = await on_token_saved(t, ssid, pwd)
                    
                    if result[0]:  # success
                        connection_status["status"] = "success"
                        connection_status["message"] = None
                    else:  # error
                        connection_status["status"] = "error"
                        connection_status["message"] = result[1] or "Could not connect to the Wi‑Fi network."
                    
                    return result
                
                await on_token_saved_with_status(token, wifi_ssid, wifi_password)
            except Exception as e:
                connection_status["status"] = "error"
                connection_status["message"] = f"Connection error: {str(e)}"
        
        # Start connection in background
        asyncio.create_task(connect_async())
        
        # Return 200 immediately
        return web.Response(
            text='{"status": "accepted"}',
            content_type="application/json",
            status=200
        )

    async def handle_loading_gif(_request: web.Request) -> web.Response:
        """Serve loading.gif from project root for HTML templates."""
        loading_path = _project_root() / "loading.gif"
        if loading_path.exists():
            return web.Response(
                body=loading_path.read_bytes(),
                content_type="image/gif"
            )
        else:
            # Return 404 if file doesn't exist
            return web.Response(status=404)
    
    app = web.Application(middlewares=[log_requests])
    app.router.add_get("/", handle_index)
    app.router.add_post("/ap-continue", handle_ap_continue)
    app.router.add_post("/submit", handle_submit)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/success", handle_success)
    app.router.add_get("/scan-wifi", handle_scan_wifi)
    app.router.add_get("/loading.gif", handle_loading_gif)

    runner = web.AppRunner(app)
    await runner.setup()
    # Bind to all interfaces to be reachable on LAN
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Discover actual bound port (important if port was 0 or occupied by retry logic)
    sockets = getattr(site._server, "sockets", None)  # type: ignore[attr-defined]
    actual_port = port
    if sockets:
        from contextlib import suppress

        with suppress(Exception):
            actual_port = sockets[0].getsockname()[1]
    print(f"[http] server listening on {host}:{actual_port}")
    return runner, actual_port


def _generate_qr_png(content: str, out_path: Path) -> None:
    img = qrcode.make(content)
    img.save(out_path)

def _render_template(template_name: str, **replacements: str) -> str:
    html = (_templates_dir() / template_name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(f"{{{{{key}}}}}", value)
    # Strip any unreplaced placeholders like {{SOME_TOKEN}}
    return re.sub(r"\{\{[A-Z0-9_]+\}\}", "", html)


def _detect_screen_resolution() -> tuple[int, int]:
    """Detect screen resolution, defaulting to 1920x1080 if detection fails."""
    try:
        # Try xrandr first (Linux/X11)
        result = subprocess.run(
            ["xrandr"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if " connected " in line and "x" in line:
                    # Parse resolution like "1920x1080"
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


def _generate_composite_qr(setup_url: str, ap_ssid: str, ap_password: str, out_path: Path) -> None:
    """Create a stunningly beautiful composite image with two QRs optimized for different display sizes.
    
    Automatically adapts to screen resolution for optimal display on TV and other screens.
    """
    # Detect screen resolution for responsive design
    screen_width, screen_height = _detect_screen_resolution()
    
    # Generate QR codes with high error correction for mobile scanning
    qr_factory = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction for mobile
        box_size=14,
        border=4,
    )
    qr_factory.add_data(_wifi_qr_payload(ap_ssid, ap_password))
    qr_factory.make(fit=True)
    wifi_qr = qr_factory.make_image(fill_color="black", back_color="white").convert("RGB")
    
    qr_factory = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction for mobile
        box_size=14,
        border=4,
    )
    qr_factory.add_data(setup_url)
    qr_factory.make(fit=True)
    url_qr = qr_factory.make_image(fill_color="black", back_color="white").convert("RGB")
    
    # Responsive sizing based on screen resolution
    # Use screen width as base, but ensure QR codes are large enough for scanning
    base_size = min(screen_width, screen_height) * 0.25  # 25% of smaller dimension
    qr_size = max(int(base_size), 400)  # Minimum 400px for scanning, scales up for TV
    
    # Scale QR codes
    url_qr = url_qr.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    wifi_qr = wifi_qr.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    
    # Responsive spacing and layout (scale with screen size)
    scale_factor = min(screen_width / 1920, screen_height / 1080, 1.5)  # Cap at 1.5x
    padding = int(60 * scale_factor)
    section_padding = int(40 * scale_factor)
    title_height = int(120 * scale_factor)
    label_height = int(70 * scale_factor)
    text_height = int(140 * scale_factor)
    qr_spacing = int(60 * scale_factor)
    card_border = int(20 * scale_factor)
    shadow_offset = int(12 * scale_factor)
    
    # Calculate layout - use full screen width/height
    width = screen_width
    height = screen_height
    
    # Center content vertically and horizontally
    content_width = padding * 2 + qr_size * 2 + qr_spacing
    content_height = padding * 2 + title_height + qr_size + label_height + text_height + section_padding
    
    # If content is smaller than screen, center it
    offset_x = (width - content_width) // 2 if content_width < width else 0
    offset_y = (height - content_height) // 2 if content_height < height else 0
    
    # Create base image with form-style dark gradient background (FAST gradient approach)
    # Match the form's radial gradient: #1e293b -> #0f172a -> #020617
    # Use linear gradient approach instead of circles for much better performance
    img = Image.new("RGB", (width, height), color=(2, 6, 23))  # #020617
    draw = ImageDraw.Draw(img)
    
    # Fast linear gradient from top to bottom (matching form's radial gradient effect)
    # Colors: #1e293b (30, 41, 59) at top -> #0f172a (15, 23, 42) at middle -> #020617 (2, 6, 23) at bottom
    step = max(4, height // 200)  # Much larger step for performance
    for y in range(0, height, step):
        ratio = y / height if height > 0 else 0
        if ratio < 0.45:  # Top area - #1e293b transitioning to #0f172a
            local_ratio = ratio / 0.45 if 0.45 > 0 else 0
            r = int(30 - (30 - 15) * local_ratio)
            g = int(41 - (41 - 23) * local_ratio)
            b = int(59 - (59 - 42) * local_ratio)
        else:  # Bottom area - #0f172a transitioning to #020617
            local_ratio = (ratio - 0.45) / 0.55 if 0.55 > 0 else 0
            r = int(15 - (15 - 2) * local_ratio)
            g = int(23 - (23 - 6) * local_ratio)
            b = int(42 - (42 - 23) * local_ratio)
        
        draw.rectangle([(0, y), (width, min(y + step, height))], fill=(r, g, b))
    
    # Subtle diagonal gradient accent (matching form's button gradient style)
    # Light green to cyan gradient: #16a34a -> #22d3ee (135deg like form buttons)
    # Apply as a subtle overlay in center area
    accent_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    accent_draw = ImageDraw.Draw(accent_overlay)
    
    # Create diagonal gradient effect (top-left to bottom-right, 135deg)
    center_x, center_y = width // 2, height // 2
    gradient_size = min(width, height) // 2
    
    for i in range(gradient_size, 0, -max(4, gradient_size // 50)):
        # Distance from center
        dist_ratio = i / gradient_size if gradient_size > 0 else 0
        alpha = int(12 * (1 - dist_ratio) ** 2)  # Subtle accent
        
        if alpha > 0:
            # Diagonal gradient colors (green to cyan)
            color_ratio = 1 - dist_ratio
            r = int(22 + (16 - 22) * color_ratio)  # 16a34a to 22d3ee
            g = int(211 + (163 - 211) * color_ratio)
            b = int(238 + (74 - 238) * color_ratio)
            
            # Draw diagonal gradient rectangle
            size = gradient_size - i
            accent_draw.rectangle(
                [center_x - size, center_y - size, center_x + size, center_y + size],
                fill=(r, g, b, alpha)
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), accent_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Load fonts with responsive sizing
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
    
    # Title with form-style button gradient colors (light green to cyan)
    title_text = "Media Bot Setup"
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = offset_x + (content_width - title_width) // 2 if content_width < width else (width - title_width) // 2
    title_y = offset_y + padding
    
    # Create title with gradient effect (matching form button: #16a34a -> #22d3ee)
    # Use simplified glow for performance
    title_glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    title_glow_draw = ImageDraw.Draw(title_glow)
    
    # Simplified glow (fewer layers for performance)
    for offset in range(4, 0, -1):
        alpha = int(20 * (1 - offset / 4))
        if alpha > 0:
            # Use button gradient colors for glow
            r = int(22 + (16 - 22) * (offset / 4))  # Cyan to green
            g = int(211 + (163 - 211) * (offset / 4))
            b = int(238 + (74 - 238) * (offset / 4))
            title_glow_draw.text(
                (title_x + offset, title_y + offset),
                title_text,
                fill=(r, g, b, alpha),
                font=font_title,
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), title_glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw title shadow for depth
    draw.text((title_x + 2, title_y + 2), title_text, fill=(0, 0, 0), font=font_title)
    # Draw main title with white color (matching form text style)
    draw.text((title_x, title_y), title_text, fill=(255, 255, 255), font=font_title)
    
    # Add QR code labels with stunning styling and decorative elements
    wifi_label = "1. Join Wi‑Fi"
    url_label = "2. Open Setup"
    
    wifi_label_bbox = draw.textbbox((0, 0), wifi_label, font=font_label)
    wifi_label_width = wifi_label_bbox[2] - wifi_label_bbox[0]
    wifi_label_x = offset_x + padding + (qr_size - wifi_label_width) // 2
    
    url_label_bbox = draw.textbbox((0, 0), url_label, font=font_label)
    url_label_width = url_label_bbox[2] - url_label_bbox[0]
    url_label_x = offset_x + padding + qr_size + qr_spacing + (qr_size - url_label_width) // 2
    
    label_y = offset_y + padding + title_height + 20
    
    # Create label glow effects (matching form button gradient)
    label_glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    label_glow_draw = ImageDraw.Draw(label_glow)
    
    # Simplified glow for performance
    for offset in range(2, 0, -1):
        alpha = int(15 * (1 - offset / 2))
        if alpha > 0:
            # Use button gradient colors
            r = int(22 + (16 - 22) * (offset / 2))
            g = int(211 + (163 - 211) * (offset / 2))
            b = int(238 + (74 - 238) * (offset / 2))
            label_glow_draw.text(
                (wifi_label_x + offset, label_y + offset),
                wifi_label,
                fill=(r, g, b, alpha),
                font=font_label,
            )
            label_glow_draw.text(
                (url_label_x + offset, label_y + offset),
                url_label,
                fill=(r, g, b, alpha),
                font=font_label,
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), label_glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw label shadows
    draw.text((wifi_label_x + 1, label_y + 1), wifi_label, fill=(0, 0, 0), font=font_label)
    draw.text((url_label_x + 1, label_y + 1), url_label, fill=(0, 0, 0), font=font_label)
    # Draw main labels with white color (matching form text style)
    draw.text((wifi_label_x, label_y), wifi_label, fill=(255, 255, 255), font=font_label)
    draw.text((url_label_x, label_y), url_label, fill=(255, 255, 255), font=font_label)
    
    # Calculate QR code positions (with offset for centering)
    qr_y = offset_y + padding + title_height + label_height + 25
    wifi_qr_x = offset_x + padding
    url_qr_x = offset_x + padding + qr_size + qr_spacing
    
    # Create card containers matching form style (rgba(15, 23, 42, 0.92) with backdrop blur effect)
    card_bg_color = (15, 23, 42)  # Matching form card background
    card_border_color = (148, 163, 184)  # Matching form border rgba(148, 163, 184, 0.25)
    
    # Draw card backgrounds with form-style shadow
    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    
    # Form-style shadow (softer, more subtle)
    shadow_offset = int(8 * scale_factor)
    for offset in range(shadow_offset, 0, -2):
        alpha = int(65 * (1 - offset / shadow_offset) ** 0.5)  # Softer shadow
        if alpha > 0:
            # WiFi card shadow
            wifi_shadow_rect = [
                wifi_qr_x - card_border + offset,
                qr_y - card_border + offset,
                wifi_qr_x + qr_size + card_border + offset,
                qr_y + qr_size + card_border + offset,
            ]
            shadow_draw.rectangle(wifi_shadow_rect, fill=(0, 0, 0, alpha))
            # URL card shadow
            url_shadow_rect = [
                url_qr_x - card_border + offset,
                qr_y - card_border + offset,
                url_qr_x + qr_size + card_border + offset,
                qr_y + qr_size + card_border + offset,
            ]
            shadow_draw.rectangle(url_shadow_rect, fill=(0, 0, 0, alpha))
    
    img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw card backgrounds (matching form card style)
    wifi_card_rect = [
        wifi_qr_x - card_border,
        qr_y - card_border,
        wifi_qr_x + qr_size + card_border,
        qr_y + qr_size + card_border,
    ]
    url_card_rect = [
        url_qr_x - card_border,
        qr_y - card_border,
        url_qr_x + qr_size + card_border,
        qr_y + qr_size + card_border,
    ]
    
    # Card background with slight transparency effect
    card_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card_overlay)
    card_draw.rectangle(wifi_card_rect, fill=(*card_bg_color, 235))  # ~0.92 opacity
    card_draw.rectangle(url_card_rect, fill=(*card_bg_color, 235))
    img = Image.alpha_composite(img.convert("RGBA"), card_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Card borders (matching form border style)
    border_width = max(1, int(scale_factor))
    draw.rectangle(
        [wifi_qr_x - card_border, qr_y - card_border,
         wifi_qr_x + qr_size + card_border, qr_y + qr_size + card_border],
        outline=card_border_color, width=border_width
    )
    draw.rectangle(
        [url_qr_x - card_border, qr_y - card_border,
         url_qr_x + qr_size + card_border, qr_y + qr_size + card_border],
        outline=card_border_color, width=border_width
    )
    
    # Paste QR codes on white backgrounds
    img.paste(wifi_qr, (wifi_qr_x, qr_y))
    img.paste(url_qr, (url_qr_x, qr_y))
        
    # Stunning text below QR codes with glow effects
    text_y = qr_y + qr_size + section_padding
    wifi_text = f"SSID: {ap_ssid}\nPassword: {ap_password}"
    url_text = f"URL:\n{setup_url}"
    
    # Center text under each QR with beautiful shadows and glows
    wifi_text_lines = wifi_text.split("\n")
    url_text_lines = url_text.split("\n")
    
    # Create text glow layer
    text_glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text_glow_draw = ImageDraw.Draw(text_glow)
    
    line_height = int(36 * scale_factor)
    for i, line in enumerate(wifi_text_lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_text)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = wifi_qr_x + (qr_size - line_width) // 2
        
        # Glow effect for text
        for offset in range(3, 0, -1):
            alpha = int(15 * (1 - offset / 3))
            if alpha > 0:
                text_glow_draw.text(
                    (line_x + offset, text_y + i * line_height + offset),
                    line,
                    fill=(200, 240, 255, alpha),
                    font=font_text,
                )
    
    for i, line in enumerate(url_text_lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_text)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = url_qr_x + (qr_size - line_width) // 2
        
        # Glow effect for text
        for offset in range(3, 0, -1):
            alpha = int(15 * (1 - offset / 3))
            if alpha > 0:
                text_glow_draw.text(
                    (line_x + offset, text_y + i * line_height + offset),
                    line,
                    fill=(200, 240, 255, alpha),
                    font=font_text,
                )
    
    img = Image.alpha_composite(img.convert("RGBA"), text_glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw text shadows and main text
    for i, line in enumerate(wifi_text_lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_text)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = wifi_qr_x + (qr_size - line_width) // 2
        # Text shadow
        draw.text((line_x + 2, text_y + i * line_height + 2), line, fill=(0, 0, 0), font=font_text)
        # Main text with vibrant color
        draw.text((line_x, text_y + i * line_height), line, fill=(220, 240, 255), font=font_text)
    
    for i, line in enumerate(url_text_lines):
        line_bbox = draw.textbbox((0, 0), line, font=font_text)
        line_width = line_bbox[2] - line_bbox[0]
        line_x = url_qr_x + (qr_size - line_width) // 2
        # Text shadow
        draw.text((line_x + 2, text_y + i * line_height + 2), line, fill=(0, 0, 0), font=font_text)
        # Main text with vibrant color
        draw.text((line_x, text_y + i * line_height), line, fill=(220, 240, 255), font=font_text)
    
    # Save with maximum quality
    img.save(out_path, quality=100, optimize=False)


async def _display_with_mpv(image_path: Path) -> subprocess.Popen:
    """Launch mpv to display the provided image fullscreen in a loop.
    
    Returns the process. The caller should wait for the image to actually load
    before stopping any loading screens.
    """
    cmd = [
        "mpv",
        "--no-terminal",
        "--force-window=yes",
        "--image-display-duration=inf",
        "--loop-file=inf",
        "--fs",
        "--ontop",
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
    return proc


def _append_or_replace_env_line(lines: list[str], key: str, value: str) -> list[str]:
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    return new_lines


def _remove_env_line(lines: list[str], key: str) -> list[str]:
    """Remove a line from .env file content that starts with key=.
    
    Args:
        lines: List of lines from .env file
        key: The environment variable key to remove
        
    Returns:
        New list of lines with the key removed
    """
    new_lines: list[str] = []
    for line in lines:
        if not line.startswith(f"{key}="):
            new_lines.append(line)
    return new_lines


def remove_telegram_token_from_env() -> None:
    """Remove TELEGRAM_BOT_TOKEN from .env file.
    
    This is useful when the bot token is in conflict (another instance is running).
    """
    env_path = _project_root() / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_content = _remove_env_line(content, "TELEGRAM_BOT_TOKEN")
        env_path.write_text("".join(new_content), encoding="utf-8")
        # Also remove from os.environ
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        print("[init] Removed TELEGRAM_BOT_TOKEN from .env")


async def ensure_telegram_token(force: bool = False) -> None:
    """Ensure TELEGRAM_BOT_TOKEN is available; if not, run the QR+form setup flow."""
    if os.getenv("TELEGRAM_BOT_TOKEN") and not force:
        return

    if os.environ.get("MEDIA_BOT_SETUP_ACTIVE") == "1":
        print("[init] Setup flow already running; ignoring duplicate request.")
        return
    os.environ["MEDIA_BOT_SETUP_ACTIVE"] = "1"

    # Start loading.gif first to avoid gap (before QR code screen)
    loading_proc: subprocess.Popen | None = None
    loading_path = _project_root() / "loading.gif"
    if loading_path.exists():
        try:
            loading_proc = await _display_with_mpv(loading_path)
            print("[init] Showing loading.gif...")
        except Exception as e:
            print(f"[init] Could not show loading.gif: {e}")

    host_ip = _detect_local_ip()
    desired_port = 8765

    mpv_proc: subprocess.Popen | None = None
    mpv_failed = False
    setup_completed = False
    current_ap_ssid = os.getenv("SETUP_AP_SSID", "media-bot-setup")
    current_ap_password = os.getenv("SETUP_AP_PASSWORD", "mediabot1234")

    async def on_token_saved(token: str, wifi_ssid: str, wifi_password: str) -> tuple[bool, Optional[str]]:
        nonlocal mpv_proc, setup_completed, current_ap_ssid, current_ap_password
        wifi_iface = _detect_wifi_interface() or "wlan0"
        
        # Run subprocess in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        connect_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["sudo", "nmcli", "dev", "wifi", "connect", wifi_ssid, "password", wifi_password, "ifname", wifi_iface],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
            )
        )
        
        if connect_result.returncode != 0:
            error = (connect_result.stderr if connect_result.stderr else "") or "Failed to connect to the provided Wi‑Fi network."
            print(f"[init] Wi‑Fi connect failed: {error}")
            # Make sure hotspot stays active so the user can retry
            print("Reconnecting after wrong creds\n", "sudo", "nmcli", "dev", "wifi", "hotspot", "ifname", wifi_iface, "ssid", current_ap_ssid, "password", current_ap_password)
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["sudo", "nmcli", "dev", "wifi", "hotspot", "ifname", wifi_iface, "ssid", current_ap_ssid, "password", current_ap_password],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            return False, error

        # Persist to .env at project root
        env_path = _project_root() / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            content = []
        new_lines = _append_or_replace_env_line(content, "TELEGRAM_BOT_TOKEN", token)
        new_lines = _append_or_replace_env_line(new_lines, "WIFI_SSID", wifi_ssid)
        new_lines = _append_or_replace_env_line(new_lines, "WIFI_PASSWORD", wifi_password)
        env_path.write_text("".join(new_lines), encoding="utf-8")

        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["WIFI_SSID"] = wifi_ssid
        os.environ["WIFI_PASSWORD"] = wifi_password

        setup_completed = True
        print("[init] Wi‑Fi connection established successfully.")

        # Don't close QR code screen here - let the main flow handle it
        # The finally block will show loading3.gif before closing the QR code screen

        return True, None

    async def run_flow():
        import os
        nonlocal mpv_proc, mpv_failed, current_ap_ssid, current_ap_password, loading_proc, loading_path
        # Ensure hotspot is up BEFORE generating QR
        current_ap_ssid = os.getenv("SETUP_AP_SSID", "media-bot-setup")
        current_ap_password = os.getenv("SETUP_AP_PASSWORD", "mediabot1234")
        wifi_iface = _detect_wifi_interface() or "wlan0"
        print(f"[init] Using Wi‑Fi interface: {wifi_iface}")
        print(f"[init] Starting hotspot SSID={current_ap_ssid}")
        try:
            subprocess.run(
                ["sudo", "nmcli", "radio", "wifi", "on"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["sudo", "nmcli", "dev", "set", wifi_iface, "managed", "yes"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("Hosting hotspot\n", "sudo", "nmcli", "dev", "wifi", "hotspot", "ifname", wifi_iface, "ssid", current_ap_ssid, "password", current_ap_password)
            result = subprocess.run(
                ["sudo", "nmcli", "dev", "wifi", "hotspot", "ifname", wifi_iface, "ssid", current_ap_ssid, "password", current_ap_password],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:  
                error_msg = result.stderr or result.stdout or "Unknown error"
                print(f"[init] FATAL: Failed to create hotspot: {error_msg}")
                print("[init] Cannot continue without hotspot. Exiting application.")
                sys.exit(1)
            else:
                print(f"[init] nmcli hotspot started: {result.stdout}")
                # NetworkManager's hotspot command already sets up most things automatically
                # Only apply essential settings if needed - most are handled by default
                # Skip the lengthy modify/up/down cycle for better performance
                # The hotspot command already configures:
                # - AP mode, SSID, password, WPA2 security
                # - IP sharing (10.42.0.1/24)
                # - Basic connectivity settings
        except Exception as e:
            print(f"Error creating hotspot: {e}")
            pass

        # Wait briefly for Wi‑Fi iface to get AP IP (e.g., 10.42.0.1)
        ap_ip = None
        for _ in range(20):
            ap_ip = _detect_interface_ip(wifi_iface)
            if ap_ip:
                break
            await asyncio.sleep(0.25)
        if not ap_ip:
            ap_ip = host_ip  # fallback
        print(f"[init] AP IP resolved: {ap_ip}")

        # Start server; if desired port is busy, fall back to ephemeral port 0
        try:
            runner, bound_port = await _start_web_server("0.0.0.0", desired_port, on_token_saved, current_ap_ssid, current_ap_password)
        except OSError:
            runner, bound_port = await _start_web_server("0.0.0.0", 0, on_token_saved, current_ap_ssid, current_ap_password)
        setup_url = f"http://{ap_ip}:{bound_port}/"
        print(setup_url)
        
        # Store setup server info
        os.environ["SETUP_SERVER_PORT"] = str(bound_port)
        os.environ["SETUP_SERVER_HOST"] = ap_ip
        
        # Prepare QR image under project data dir
        project = _project_root()
        tmp_dir = project / ".setup"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Generate dual QR (Wi‑Fi join + setup URL)
        qr_png = tmp_dir / "setup_qr.png"
        _generate_composite_qr(setup_url, current_ap_ssid, current_ap_password, qr_png)
        
        try:
            # Try to show QR with mpv; fallback to printing URL if mpv missing
            try:
                mpv_proc = await _display_with_mpv(qr_png)
                # QR code screen is now loaded - _display_with_mpv already waited up to 1.5 seconds
                # Give it just a tiny moment more to ensure it's fully rendered and visible
                await asyncio.sleep(1.5)
                
                # NOW stop loading.gif after QR code screen is confirmed loaded and visible
                # Do this immediately while we know mpv_proc is still running
                if loading_proc is not None and mpv_proc.poll() is None:
                    try:
                        loading_proc.terminate()
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(loading_proc.wait), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            loading_proc.kill()
                            await asyncio.to_thread(loading_proc.wait)
                        print("[init] Stopped loading.gif after QR code screen loaded")
                    except Exception as e:
                        print(f"[init] Error stopping loading.gif: {e}")
                        try:
                            if loading_proc.poll() is None:
                                loading_proc.kill()
                        except Exception:
                            pass
                elif mpv_proc.poll() is not None:
                    # QR code screen already closed (user submitted form), will show loading3.gif in finally
                    print("[init] QR code screen already closed")
            except FileNotFoundError:
                mpv_failed = True
                print(
                    f"[init] mpv not found. Open this URL to configure: {setup_url}",
                    file=sys.stderr,
                )

            # Wait until setup completes successfully
            while not setup_completed:
                await asyncio.sleep(0.5)
        finally:
            # Stop QR code screen - show loading3.gif before closing to avoid gaps
            if mpv_proc is not None:
                try:
                    # Stop the initial loading.gif if it's still running
                    if loading_proc is not None and loading_proc.poll() is None:
                        try:
                            loading_proc.terminate()
                            try:
                                await asyncio.wait_for(
                                    asyncio.to_thread(loading_proc.wait), timeout=0.5
                                )
                            except asyncio.TimeoutError:
                                loading_proc.kill()
                                await asyncio.to_thread(loading_proc.wait)
                        except Exception:
                            pass
                    
                    # Now show loading3.gif before closing QR code screen
                    loading3_path = _project_root() / "loading3.gif"
                    if loading3_path.exists():
                        try:
                            loading_proc = await _display_with_mpv(loading3_path)
                            print("[init] Started loading3.gif before closing QR code screen")
                            # Wait for loading3.gif to be fully visible
                            await asyncio.sleep(1.5)
                        except Exception as e:
                            print(f"[init] Could not show loading3.gif: {e}")
                    
                    # Now close QR code screen (loading3.gif is already visible and covering it)
                    mpv_proc.terminate()
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(mpv_proc.wait), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        mpv_proc.kill()
                        await asyncio.to_thread(mpv_proc.wait)
                except Exception as e:
                    print(f"[init] Error stopping QR code screen: {e}")
                    try:
                        if mpv_proc.poll() is None:
                            mpv_proc.kill()
                    except Exception:
                        pass
            
            # Don't stop init_flow's loading3.gif - let MPV player take ownership
            # Store the process in an environment variable so MPV player can check it
            if loading_proc is not None and loading_proc.poll() is None:
                # Store PID so MPV player knows loading3.gif is already running
                import os
                os.environ["MEDIA_BOT_LOADING_PID"] = str(loading_proc.pid)
                print(f"[init] Leaving loading3.gif running (PID {loading_proc.pid}) - MPV player will manage it")
            
            await runner.cleanup()

    try:
        await run_flow()
    finally:
        os.environ.pop("MEDIA_BOT_SETUP_ACTIVE", None)


async def ensure_rutracker_credentials(force: bool = False) -> None:
    """Ensure TRACKER_USERNAME and TRACKER_PASSWORD are available; if not, run the web form setup flow."""
    tracker_username = os.getenv("TRACKER_USERNAME")
    tracker_password = os.getenv("TRACKER_PASSWORD")
    
    if tracker_username and tracker_password and not force:
        return

    if os.environ.get("RUTRACKER_SETUP_ACTIVE") == "1":
        print("[init] RuTracker setup flow already running; ignoring duplicate request.")
        return
    os.environ["RUTRACKER_SETUP_ACTIVE"] = "1"

    host_ip = _detect_local_ip()
    desired_port = 8766  # Different port from main setup

    async def on_credentials_saved(username: str, password: str) -> tuple[bool, Optional[str]]:
        """Save credentials to .env file."""
        try:
            # Persist to .env at project root
            env_path = _project_root() / ".env"
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
            else:
                content = []
            new_lines = _append_or_replace_env_line(content, "TRACKER_USERNAME", username)
            new_lines = _append_or_replace_env_line(new_lines, "TRACKER_PASSWORD", password)
            env_path.write_text("".join(new_lines), encoding="utf-8")

            os.environ["TRACKER_USERNAME"] = username
            os.environ["TRACKER_PASSWORD"] = password

            print("[init] RuTracker credentials saved successfully.")
            return True, None
        except Exception as e:
            error_msg = f"Failed to save credentials: {str(e)}"
            print(f"[init] {error_msg}")
            return False, error_msg

    async def _start_rutracker_web_server(
        host: str, port: int, on_credentials_saved
    ) -> tuple[web.AppRunner, int]:
        """Start a minimal aiohttp server that serves a RuTracker credentials form and handles submission.

        Returns:
            (runner, actual_port)
        """
        # Very lightweight request logging
        @web.middleware
        async def log_requests(request, handler):
            peer = request.transport.get_extra_info("peername")
            print(f"[http] {request.method} {request.path} from {peer}")
            resp = await handler(request)
            print(f"[http] -> {resp.status} {request.method} {request.path}")
            return resp

        async def handle_index(_request: web.Request) -> web.Response:
            html = _render_template(
                "rutracker_setup.html",
                ERROR_BOX="",
                TRACKER_USERNAME=tracker_username or "",
                TRACKER_PASSWORD="",
            )
            return web.Response(text=html, content_type="text/html")

        async def handle_success(_request: web.Request) -> web.Response:
            """Show success page."""
            html_content = _render_template("rutracker_success.html")
            return web.Response(text=html_content, content_type="text/html")

        async def handle_submit(request: web.Request) -> web.Response:
            data = await request.post()
            username = (data.get("tracker_username") or "").strip()
            password = (data.get("tracker_password") or "").strip()
            
            # Validate input
            if not username or not password:
                error_html = "<div class=\"error\">Both username and password are required.</div>"
                html_content = _render_template(
                    "rutracker_setup.html",
                    ERROR_BOX=error_html,
                    TRACKER_USERNAME=username,
                    TRACKER_PASSWORD="",
                )
                return web.Response(text=html_content, content_type="text/html", status=400)
            
            # Save credentials
            success, error_msg = await on_credentials_saved(username, password)
            
            if success:
                return web.Response(
                    text='{"status": "success"}',
                    content_type="application/json",
                    status=200
                )
            else:
                error_html = f"<div class=\"error\">{html.escape(error_msg or 'Failed to save credentials')}</div>"
                html_content = _render_template(
                    "rutracker_setup.html",
                    ERROR_BOX=error_html,
                    TRACKER_USERNAME=username,
                    TRACKER_PASSWORD="",
                )
                return web.Response(text=html_content, content_type="text/html", status=500)
        
        app = web.Application(middlewares=[log_requests])
        app.router.add_get("/", handle_index)
        app.router.add_post("/submit", handle_submit)
        app.router.add_get("/success", handle_success)

        runner = web.AppRunner(app)
        await runner.setup()
        # Bind to all interfaces to be reachable on LAN
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        # Discover actual bound port
        sockets = getattr(site._server, "sockets", None)  # type: ignore[attr-defined]
        actual_port = port
        if sockets:
            with suppress(Exception):
                actual_port = sockets[0].getsockname()[1]
        print(f"[http] RuTracker setup server listening on {host}:{actual_port}")
        return runner, actual_port

    runner: web.AppRunner | None = None
    
    async def run_flow():
        nonlocal host_ip, desired_port, runner
        
        # Start server; if desired port is busy, fall back to ephemeral port 0
        try:
            runner, bound_port = await _start_rutracker_web_server("0.0.0.0", desired_port, on_credentials_saved)
        except OSError:
            runner, bound_port = await _start_rutracker_web_server("0.0.0.0", 0, on_credentials_saved)
        
        setup_url = f"http://{host_ip}:{bound_port}/"
        print(f"[init] RuTracker setup URL: {setup_url}")
        print(f"[init] Please open this URL in your browser to enter RuTracker credentials.")
        
        # Wait for credentials with a timeout check in background
        async def wait_for_credentials():
            nonlocal runner
            max_wait = 300  # 5 minutes max wait
            waited = 0
            while waited < max_wait and runner is not None:
                await asyncio.sleep(1)
                waited += 1
                # Reload environment from .env file
                # Note: dotenv is loaded in config.py, but we need to reload it here
                # We'll read the .env file directly to check for credentials
                env_path = _project_root() / ".env"
                if env_path.exists():
                    content = env_path.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("TRACKER_USERNAME="):
                            os.environ["TRACKER_USERNAME"] = line.split("=", 1)[1].strip()
                        elif line.startswith("TRACKER_PASSWORD="):
                            os.environ["TRACKER_PASSWORD"] = line.split("=", 1)[1].strip()
                if os.getenv("TRACKER_USERNAME") and os.getenv("TRACKER_PASSWORD"):
                    print("[init] RuTracker credentials saved, cleaning up server...")
                    try:
                        await runner.cleanup()
                    except Exception as e:
                        print(f"[init] Error cleaning up server: {e}")
                    runner = None
                    os.environ.pop("RUTRACKER_SETUP_ACTIVE", None)
                    print("[init] RuTracker setup completed.")
                    return
            # Timeout - keep server running but log
            if runner is not None:
                print(f"[init] RuTracker setup timeout after {max_wait} seconds. Server will keep running.")
        
        # Start waiting in background (non-blocking)
        asyncio.create_task(wait_for_credentials())

    try:
        await run_flow()
    except Exception as e:
        print(f"[init] Error in RuTracker setup flow: {e}")
        os.environ.pop("RUTRACKER_SETUP_ACTIVE", None)


