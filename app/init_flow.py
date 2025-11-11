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
            for line in proc.stdout.strip().splitlines():
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

    async def handle_success(_request: web.Request) -> web.Response:
        """Show success page."""
        html_content = _render_template("setup_success.html")
        return web.Response(text=html_content, content_type="text/html")

    async def handle_submit(request: web.Request) -> web.Response:
        data = await request.post()
        token = (data.get("token") or "").strip()
        wifi_ssid = (data.get("wifi_ssid") or "").strip()
        wifi_password = (data.get("wifi_password") or "").strip()
        
        # Validate input
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

    app = web.Application(middlewares=[log_requests])
    app.router.add_get("/", handle_index)
    app.router.add_post("/ap-continue", handle_ap_continue)
    app.router.add_post("/submit", handle_submit)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/success", handle_success)

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


def _generate_composite_qr(setup_url: str, ap_ssid: str, ap_password: str, out_path: Path) -> None:
    """Create a stunningly beautiful composite image with two QRs optimized for mobile scanning."""
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
    
    # Mobile-optimized sizing (larger QR codes for easier scanning)
    qr_size = 520
    url_qr = url_qr.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    wifi_qr = wifi_qr.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
    
    # Beautiful spacing and layout
    padding = 60
    section_padding = 40
    title_height = 120
    label_height = 70
    text_height = 140
    qr_spacing = 60
    card_border = 20
    shadow_offset = 12
    
    width = padding * 2 + qr_size * 2 + qr_spacing
    height = padding * 2 + title_height + qr_size + label_height + text_height + section_padding
    
    # Create base image with stunning multi-layer gradient background
    img = Image.new("RGB", (width, height), color=(8, 8, 18))
    draw = ImageDraw.Draw(img)
    
    # Layer 1: Beautiful diagonal gradient background (purple to blue to cyan)
    for y in range(height):
        ratio = y / height if height > 0 else 0
        # Rich color transitions with more vibrant colors
        r = int(8 + (25 - 8) * ratio + 12 * (1 - abs(ratio - 0.3) * 2))
        g = int(8 + (35 - 8) * ratio + 15 * (1 - abs(ratio - 0.5) * 2))
        b = int(18 + (55 - 18) * ratio + 20 * (1 - abs(ratio - 0.7) * 2))
        # Add horizontal variation for more depth
        for x in range(0, width, 2):
            h_ratio = x / width if width > 0 else 0
            r_var = int(r + 3 * (1 - abs(h_ratio - 0.5) * 2))
            g_var = int(g + 4 * (1 - abs(h_ratio - 0.5) * 2))
            b_var = int(b + 5 * (1 - abs(h_ratio - 0.5) * 2))
            draw.line([(x, y), (min(x + 2, width), y)], fill=(r_var, g_var, b_var))
    
    # Layer 2: Multiple radial glows for depth and atmosphere
    center_x, center_y = width // 2, height // 2
    max_radius = int((width ** 2 + height ** 2) ** 0.5)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # Primary center glow (cyan-blue)
    for radius in range(max_radius, 0, -15):
        alpha = int(25 * (1 - radius / max_radius) ** 1.5)
        if alpha > 0:
            overlay_draw.ellipse(
                [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                fill=(100, 180, 255, alpha)
            )
    
    # Secondary glow (purple, offset)
    glow2_x, glow2_y = width // 4, height // 3
    for radius in range(max_radius // 2, 0, -12):
        alpha = int(15 * (1 - radius / (max_radius // 2)) ** 1.5)
        if alpha > 0:
            overlay_draw.ellipse(
                [glow2_x - radius, glow2_y - radius, glow2_x + radius, glow2_y + radius],
                fill=(180, 100, 255, alpha)
            )
    
    # Tertiary glow (teal, offset)
    glow3_x, glow3_y = width * 3 // 4, height * 2 // 3
    for radius in range(max_radius // 2, 0, -12):
        alpha = int(15 * (1 - radius / (max_radius // 2)) ** 1.5)
        if alpha > 0:
            overlay_draw.ellipse(
                [glow3_x - radius, glow3_y - radius, glow3_x + radius, glow3_y + radius],
                fill=(100, 255, 220, alpha)
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Load fonts with better fallbacks
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
        font_label = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 24)
    except Exception:
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
            font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            font_title = ImageFont.load_default()
            font_label = ImageFont.load_default()
            font_text = ImageFont.load_default()
    
    # Stunning title with multiple glow effects
    title_text = "Media Bot Setup"
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    title_y = padding
    
    # Create title glow layer
    title_glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    title_glow_draw = ImageDraw.Draw(title_glow)
    
    # Multiple glow layers for title
    for offset in range(8, 0, -1):
        alpha = int(30 * (1 - offset / 8))
        if alpha > 0:
            title_glow_draw.text(
                (title_x + offset, title_y + offset),
                title_text,
                fill=(100, 200, 255, alpha),
                font=font_title,
            )
            title_glow_draw.text(
                (title_x - offset, title_y + offset),
                title_text,
                fill=(100, 200, 255, alpha),
                font=font_title,
            )
            title_glow_draw.text(
                (title_x + offset, title_y - offset),
                title_text,
                fill=(100, 200, 255, alpha),
                font=font_title,
            )
            title_glow_draw.text(
                (title_x - offset, title_y - offset),
                title_text,
                fill=(100, 200, 255, alpha),
                font=font_title,
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), title_glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw title shadow for depth
    draw.text((title_x + 3, title_y + 3), title_text, fill=(0, 0, 0, 180), font=font_title)
    # Draw main title with gradient-like effect (white to light cyan)
    draw.text((title_x, title_y), title_text, fill=(255, 255, 255), font=font_title)
    
    # Add QR code labels with stunning styling and decorative elements
    wifi_label = "1. Join Wi‑Fi"
    url_label = "2. Open Setup"
    
    wifi_label_bbox = draw.textbbox((0, 0), wifi_label, font=font_label)
    wifi_label_width = wifi_label_bbox[2] - wifi_label_bbox[0]
    wifi_label_x = padding + (qr_size - wifi_label_width) // 2
    
    url_label_bbox = draw.textbbox((0, 0), url_label, font=font_label)
    url_label_width = url_label_bbox[2] - url_label_bbox[0]
    url_label_x = padding + qr_size + qr_spacing + (qr_size - url_label_width) // 2
    
    label_y = padding + title_height + 20
    
    # Create label glow effects
    label_glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    label_glow_draw = ImageDraw.Draw(label_glow)
    
    for offset in range(4, 0, -1):
        alpha = int(20 * (1 - offset / 4))
        if alpha > 0:
            label_glow_draw.text(
                (wifi_label_x + offset, label_y + offset),
                wifi_label,
                fill=(148, 220, 255, alpha),
                font=font_label,
            )
            label_glow_draw.text(
                (url_label_x + offset, label_y + offset),
                url_label,
                fill=(148, 220, 255, alpha),
                font=font_label,
            )
    
    img = Image.alpha_composite(img.convert("RGBA"), label_glow).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw label shadows
    draw.text((wifi_label_x + 2, label_y + 2), wifi_label, fill=(0, 0, 0), font=font_label)
    draw.text((url_label_x + 2, label_y + 2), url_label, fill=(0, 0, 0), font=font_label)
    # Draw main labels with vibrant accent color
    draw.text((wifi_label_x, label_y), wifi_label, fill=(148, 220, 255), font=font_label)
    draw.text((url_label_x, label_y), url_label, fill=(148, 220, 255), font=font_label)
    
    # Calculate QR code positions
    qr_y = padding + title_height + label_height + 25
    wifi_qr_x = padding
    url_qr_x = padding + qr_size + qr_spacing
    
    # Create stunning card containers with multiple shadow layers and highlights
    # Create shadow layer for QR cards with multiple shadow passes
    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    
    # Multiple shadow layers for depth (WiFi card)
    for i, (offset, alpha) in enumerate([(12, 150), (8, 100), (4, 60)]):
        wifi_shadow_rect = [
            wifi_qr_x - card_border + offset,
            qr_y - card_border + offset,
            wifi_qr_x + qr_size + card_border + offset,
            qr_y + qr_size + card_border + offset,
        ]
        shadow_draw.rectangle(wifi_shadow_rect, fill=(0, 0, 0, alpha))
    
    # Multiple shadow layers for depth (URL card)
    for i, (offset, alpha) in enumerate([(12, 150), (8, 100), (4, 60)]):
        url_shadow_rect = [
            url_qr_x - card_border + offset,
            qr_y - card_border + offset,
            url_qr_x + qr_size + card_border + offset,
            qr_y + qr_size + card_border + offset,
        ]
        shadow_draw.rectangle(url_shadow_rect, fill=(0, 0, 0, alpha))
    
    # Composite shadow layer
    img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # Draw WiFi QR card background with subtle gradient (white to very light blue)
    wifi_card_rect = [
        wifi_qr_x - card_border,
        qr_y - card_border,
        wifi_qr_x + qr_size + card_border,
        qr_y + qr_size + card_border,
    ]
    # Draw gradient background for card
    for y_offset in range(card_border * 2 + qr_size):
        ratio = y_offset / (card_border * 2 + qr_size) if (card_border * 2 + qr_size) > 0 else 0
        color_val = int(255 - 2 * ratio)  # Subtle gradient from white to very light
        draw.line(
            [
                (wifi_qr_x - card_border, qr_y - card_border + y_offset),
                (wifi_qr_x + qr_size + card_border, qr_y - card_border + y_offset),
            ],
            fill=(color_val, color_val, 255),
        )
    
    # Draw URL QR card background with subtle gradient
    url_card_rect = [
        url_qr_x - card_border,
        qr_y - card_border,
        url_qr_x + qr_size + card_border,
        qr_y + qr_size + card_border,
    ]
    for y_offset in range(card_border * 2 + qr_size):
        ratio = y_offset / (card_border * 2 + qr_size) if (card_border * 2 + qr_size) > 0 else 0
        color_val = int(255 - 2 * ratio)
        draw.line(
            [
                (url_qr_x - card_border, qr_y - card_border + y_offset),
                (url_qr_x + qr_size + card_border, qr_y - card_border + y_offset),
            ],
            fill=(color_val, 255, color_val),
        )
    
    # Add subtle highlight on top edge of cards
    highlight_width = 2
    draw.rectangle(
        [
            wifi_qr_x - card_border,
            qr_y - card_border,
            wifi_qr_x + qr_size + card_border,
            qr_y - card_border + highlight_width,
        ],
        fill=(255, 255, 255),
    )
    draw.rectangle(
        [
            url_qr_x - card_border,
            qr_y - card_border,
            url_qr_x + qr_size + card_border,
            qr_y - card_border + highlight_width,
        ],
        fill=(255, 255, 255),
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
    
    line_height = 36
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
    """Launch mpv to display the provided image fullscreen in a loop."""
    cmd = [
        "mpv",
        "--no-terminal",
        "--force-window=yes",
        "--image-display-duration=inf",
        "--loop-file=inf",
        "--fs",
        str(image_path),
    ]
    # Start detached so we can kill later
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await asyncio.sleep(0.5)
    return proc


def _append_or_replace_env_line(lines: list[str], key: str, value: str) -> list[str]:
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    return new_lines


async def ensure_telegram_token(force: bool = False) -> None:
    """Ensure TELEGRAM_BOT_TOKEN is available; if not, run the QR+form setup flow."""
    if os.getenv("TELEGRAM_BOT_TOKEN") and not force:
        return

    if os.environ.get("MEDIA_BOT_SETUP_ACTIVE") == "1":
        print("[init] Setup flow already running; ignoring duplicate request.")
        return
    os.environ["MEDIA_BOT_SETUP_ACTIVE"] = "1"

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
            error = connect_result.stderr.strip() or "Failed to connect to the provided Wi‑Fi network."
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

        if mpv_proc and mpv_proc.poll() is None:
            with suppress(Exception):
                mpv_proc.terminate()

        return True, None

    async def run_flow():
        nonlocal mpv_proc, mpv_failed, current_ap_ssid, current_ap_password
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
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                print(f"[init] FATAL: Failed to create hotspot: {error_msg}")
                print("[init] Cannot continue without hotspot. Exiting application.")
                sys.exit(1)
            else:
                print(f"[init] nmcli hotspot started: {result.stdout.strip()}")
                con_name = None
                con_list = subprocess.run(
                    ["sudo", "nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "con", "show", "--active"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if con_list.returncode == 0 and con_list.stdout:
                    for line in con_list.stdout.strip().splitlines():
                        parts = line.split(":")
                        if len(parts) >= 3:
                            name, dev, typ = parts[0], parts[1], parts[2]
                            if dev == wifi_iface and typ == "wifi":
                                con_name = name
                                break
                if not con_name:
                    # Default NM creates a "Hotspot" profile; try that as fallback
                    con_name = "Hotspot"
                print(f"[init] Using connection profile: {con_name}")
                # Apply sharing and static addressing; ignore errors if fields unsupported
                # Use common NetworkManager shared subnet 10.42.0.0/24 with gateway .1
                for args in [
                    ["sudo", "nmcli", "con", "modify", con_name, "ipv4.method", "shared"],
                    ["sudo", "nmcli", "con", "modify", con_name, "ipv4.addresses", "10.42.0.1/24"],
                    ["sudo", "nmcli", "con", "modify", con_name, "ipv4.gateway", "10.42.0.1"],
                    ["sudo", "nmcli", "con", "modify", con_name, "ipv4.never-default", "yes"],
                    ["sudo", "nmcli", "con", "modify", con_name, "ipv6.method", "ignore"],
                    # Force 2.4GHz band and stable channel; some clients can't use 5GHz APs
                    ["sudo", "nmcli", "con", "modify", con_name, "802-11-wireless.band", "bg"],
                    ["sudo", "nmcli", "con", "modify", con_name, "802-11-wireless.channel", "6"],
                    # Ensure AP mode and SSID are correct
                    ["sudo", "nmcli", "con", "modify", con_name, "802-11-wireless.mode", "ap"],
                    ["sudo", "nmcli", "con", "modify", con_name, "802-11-wireless.ssid", current_ap_ssid],
                    # Improve compatibility: WPA2-PSK (RSN) with CCMP only
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi-sec.key-mgmt", "wpa-psk"],
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi-sec.proto", "rsn"],
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi-sec.group", "ccmp"],
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi-sec.pairwise", "ccmp"],
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi-sec.psk", current_ap_password],
                    # Disable MAC randomization to avoid reconnect loops on some devices
                    ["sudo", "nmcli", "con", "modify", con_name, "wifi.mac-address-randomization", "0"],
                    [
                        "sudo", "nmcli",
                        "con",
                        "modify",
                        con_name,
                        "802-11-wireless.cloned-mac-address",
                        "preserve",
                    ],
                    # Reduce powersave issues
                    ["sudo", "nmcli", "con", "modify", con_name, "802-11-wireless.powersave", "2"],
                ]:
                    r = subprocess.run(args, check=False, capture_output=True, text=True)
                    if r.returncode != 0:
                        print(
                            f"[init] nmcli modify warn: {' '.join(args[3:])} -> {r.stderr.strip()}"
                        )
                # Reload the connection to apply changes
                r1 = subprocess.run(
                    ["sudo", "nmcli", "con", "down", con_name], check=False, capture_output=True, text=True
                )
                r2 = subprocess.run(
                    ["sudo", "nmcli", "con", "up", con_name], check=False, capture_output=True, text=True
                )
                if r1.returncode != 0:
                    print(f"[init] nmcli down warn: {r1.stderr.strip()}")
                if r2.returncode != 0:
                    print(f"[init] nmcli up warn: {r2.stderr.strip()}")
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
            await runner.cleanup()
            if mpv_proc and mpv_proc.poll() is None:
                try:
                    mpv_proc.terminate()
                except Exception:
                    pass

    try:
        await run_flow()
    finally:
        os.environ.pop("MEDIA_BOT_SETUP_ACTIVE", None)


