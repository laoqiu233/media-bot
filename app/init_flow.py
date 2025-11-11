"""Initialization flow to configure Telegram bot token via QR + web form.

This module is intentionally separate from the main app logic.
If no TELEGRAM_BOT_TOKEN is found, it:
1) Starts a tiny aiohttp web server with a token input form
2) Generates a QR code for the setup URL
3) Displays the QR code using the system `mpv` player (fullscreen, looping)
4) On submit, writes TELEGRAM_BOT_TOKEN to project's .env, stops mpv, and returns
"""

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from aiohttp import web
import qrcode
from PIL import Image, ImageDraw, ImageFont
import logging


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

def _detect_interface_ip(interface_name: str) -> Optional[str]:
    """Try to detect IP bound to a specific interface (e.g., wlan0/wlp2s0/wlo1)."""
    try:
        import fcntl
        import struct
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(
            fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack('256s', bytes(interface_name[:15], 'utf-8'))
            )[20:24]
        )
    except Exception:
        return None

def _detect_wifi_interface() -> Optional[str]:
    """Detect a Wi‑Fi interface name using nmcli or /sys/class/net."""
    # Prefer nmcli when available
    try:
        proc = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "dev", "status"],
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


async def _start_web_server(host: str, port: int, on_token_saved, ap_ssid: str, ap_password: str) -> tuple[web.AppRunner, int]:
    """Start a minimal aiohttp server that serves a token form and handles submission.
    
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
        # Stage 1: AP connect page
        html_path = _templates_dir() / "setup_ap.html"
        html = html_path.read_text(encoding="utf-8")
        html = html.replace("{{AP_SSID}}", ap_ssid).replace("{{AP_PASS}}", ap_password)
        return web.Response(text=html, content_type="text/html")

    async def handle_ap_continue(_request: web.Request) -> web.Response:
        # Stage 2: Wi‑Fi + token form
        html_path = _templates_dir() / "setup.html"
        html = html_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def handle_submit(request: web.Request) -> web.Response:
        data = await request.post()
        token = (data.get("token") or "").strip()
        wifi_ssid = (data.get("wifi_ssid") or "").strip()
        wifi_password = (data.get("wifi_password") or "").strip()
        # Optional: only accept submissions from clients on AP subnet (best-effort)
        peer_ip = request.transport.get_extra_info("peername")[0] if request.transport else None  # type: ignore[index]
        if peer_ip and peer_ip.startswith("10.42."):
            pass  # likely NetworkManager hotspot subnet
        if not token or not wifi_ssid or not wifi_password:
            return web.Response(text="Wi‑Fi SSID, password and token are required", status=400)
        await on_token_saved(token, wifi_ssid, wifi_password)
        return web.Response(
            text="Token saved. You can close this page. The app will continue.",
            content_type="text/plain",
        )

    app = web.Application(middlewares=[log_requests])
    app.router.add_get("/", handle_index)
    app.router.add_post("/ap-continue", handle_ap_continue)
    app.router.add_post("/submit", handle_submit)

    runner = web.AppRunner(app)
    await runner.setup()
    # Bind to all interfaces to be reachable on LAN
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    # Discover actual bound port (important if port was 0 or occupied by retry logic)
    sockets = getattr(site._server, "sockets", None)  # type: ignore[attr-defined]
    actual_port = port
    if sockets:
        try:
            actual_port = sockets[0].getsockname()[1]
        except Exception:
            pass
    print(f"[http] server listening on {host}:{actual_port}")
    return runner, actual_port


def _generate_qr_png(content: str, out_path: Path) -> None:
    img = qrcode.make(content)
    img.save(out_path)

def _generate_url_qr_with_caption(setup_url: str, out_path: Path, note: str | None = None) -> None:
    """Generate a single QR for the setup URL with a short caption."""
    qr_img = qrcode.make(setup_url).convert("RGB")
    qr_size = 420
    qr_img = qr_img.resize((qr_size, qr_size))
    padding = 24
    title_height = 60
    text_height = 60
    canvas_h = padding * 3 + title_height + qr_size + (text_height if note else 0)
    canvas_w = padding * 2 + qr_size
    img = Image.new("RGB", (canvas_w, canvas_h), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
    draw.text((padding, padding), "Media Bot Setup", fill=(230, 230, 230), font=font_title)
    img.paste(qr_img, (padding, padding + title_height))
    if note:
        draw.text(
            (padding, padding * 2 + title_height + qr_size),
            note,
            fill=(220, 220, 220),
            font=font_text,
        )
    img.save(out_path)

def _generate_composite_qr(setup_url: str, ap_ssid: str, ap_password: str, out_path: Path) -> None:
    """Create a composite image with two QRs: Wi‑Fi join and setup URL, plus brief text."""
    url_qr = qrcode.make(setup_url).convert("RGB")
    wifi_qr = qrcode.make(_wifi_qr_payload(ap_ssid, ap_password)).convert("RGB")
    qr_size = 360
    url_qr = url_qr.resize((qr_size, qr_size))
    wifi_qr = wifi_qr.resize((qr_size, qr_size))
    padding = 24
    title_height = 60
    text_height = 80
    width = padding * 3 + qr_size * 2
    height = padding * 3 + title_height + qr_size + text_height
    img = Image.new("RGB", (width, height), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
    draw.text((padding, padding), "Media Bot Setup", fill=(230, 230, 230), font=font_title)
    img.paste(wifi_qr, (padding, padding + title_height))
    img.paste(url_qr, (padding * 2 + qr_size, padding + title_height))
    wifi_text = f"1) Join AP: {ap_ssid}  Pass: {ap_password}"
    url_text = f"2) Open setup: {setup_url}"
    draw.text((padding, padding * 2 + title_height + qr_size), wifi_text, fill=(220, 220, 220), font=font_text)
    draw.text((padding * 2 + qr_size, padding * 2 + title_height + qr_size), url_text, fill=(220, 220, 220), font=font_text)
    img.save(out_path)

def _generate_wifi_qr_with_caption(ap_ssid: str, ap_password: str, setup_url: str, out_path: Path) -> None:
    """Generate a single Wi‑Fi QR (join AP) with caption including the setup URL."""
    wifi_qr = qrcode.make(_wifi_qr_payload(ap_ssid, ap_password)).convert("RGB")
    qr_size = 420
    wifi_qr = wifi_qr.resize((qr_size, qr_size))
    padding = 24
    title_height = 60
    text_height = 80
    width = padding * 2 + qr_size
    height = padding * 3 + title_height + qr_size + text_height
    img = Image.new("RGB", (width, height), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
    draw.text((padding, padding), "Media Bot Setup", fill=(230, 230, 230), font=font_title)
    img.paste(wifi_qr, (padding, padding + title_height))
    caption = f"Join Wi‑Fi: {ap_ssid}  Pass: {ap_password}\nThen open: {setup_url}"
    draw.text((padding, padding * 2 + title_height + qr_size), caption, fill=(220, 220, 220), font=font_text)
    img.save(out_path)

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


async def ensure_telegram_token() -> None:
    """Ensure TELEGRAM_BOT_TOKEN is available; if not, run the QR+form setup flow."""
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        return

    host_ip = _detect_local_ip()
    desired_port = 8765
    # Check whether Wi-Fi and bot token exist
    have_token = bool(os.getenv("TELEGRAM_BOT_TOKEN"))

    mpv_proc: Optional[subprocess.Popen] = None
    mpv_failed = False

    async def on_token_saved(token: str, wifi_ssid: str, wifi_password: str):
        # Persist to .env at project root
        env_path = project / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            content = []
        new_lines = _append_or_replace_env_line(content, "TELEGRAM_BOT_TOKEN", token)
        new_lines = _append_or_replace_env_line(new_lines, "WIFI_SSID", wifi_ssid)
        new_lines = _append_or_replace_env_line(new_lines, "WIFI_PASSWORD", wifi_password)
        env_path.write_text("".join(new_lines), encoding="utf-8")

        # Also set for this process so we can proceed immediately
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        os.environ["WIFI_SSID"] = wifi_ssid
        os.environ["WIFI_PASSWORD"] = wifi_password

        # Try to connect to provided Wi‑Fi
        wifi_iface = _detect_wifi_interface() or "wlan0"
        try:
            subprocess.run(
                ["nmcli", "dev", "wifi", "connect", wifi_ssid, "password", wifi_password, "ifname", wifi_iface],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

        # Close mpv window if running
        if mpv_proc and mpv_proc.poll() is None:
            try:
                mpv_proc.terminate()
            except Exception:
                pass

    async def run_flow():
        nonlocal mpv_proc, mpv_failed
        # Ensure hotspot is up BEFORE generating QR
        ap_ssid = os.getenv("SETUP_AP_SSID", "media-bot-setup")
        ap_password = os.getenv("SETUP_AP_PASSWORD", "mediabot1234")
        wifi_iface = _detect_wifi_interface() or "wlan0"
        print(f"[init] Using Wi‑Fi interface: {wifi_iface}")
        print(f"[init] Starting hotspot SSID={ap_ssid}")
        try:
            subprocess.run(
                ["nmcli", "radio", "wifi", "on"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["nmcli", "dev", "set", wifi_iface, "managed", "yes"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result = subprocess.run(
                ["nmcli", "dev", "wifi", "hotspot", "ifname", wifi_iface, "ssid", ap_ssid, "password", ap_password],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"[init] nmcli hotspot error: {result.stderr.strip()}")
            else:
                print(f"[init] nmcli hotspot started: {result.stdout.strip()}")
                con_name = None
                con_list = subprocess.run(
                    ["nmcli", "-t", "-f", "NAME,DEVICE,TYPE", "con", "show", "--active"],
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
                    ["nmcli", "con", "modify", con_name, "ipv4.method", "shared"],
                    ["nmcli", "con", "modify", con_name, "ipv4.addresses", "10.42.0.1/24"],
                    ["nmcli", "con", "modify", con_name, "ipv4.gateway", "10.42.0.1"],
                    ["nmcli", "con", "modify", con_name, "ipv4.never-default", "yes"],
                    ["nmcli", "con", "modify", con_name, "ipv6.method", "ignore"],
                    # Force 2.4GHz band and stable channel; some clients can't use 5GHz APs
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.band", "bg"],
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.channel", "6"],
                    # Ensure AP mode and SSID are correct
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.mode", "ap"],
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.ssid", ap_ssid],
                    # Improve compatibility: WPA2-PSK (RSN) with CCMP only
                    ["nmcli", "con", "modify", con_name, "wifi-sec.key-mgmt", "wpa-psk"],
                    ["nmcli", "con", "modify", con_name, "wifi-sec.proto", "rsn"],
                    ["nmcli", "con", "modify", con_name, "wifi-sec.group", "ccmp"],
                    ["nmcli", "con", "modify", con_name, "wifi-sec.pairwise", "ccmp"],
                    ["nmcli", "con", "modify", con_name, "wifi-sec.psk", ap_password],
                    # Disable MAC randomization to avoid reconnect loops on some devices
                    ["nmcli", "con", "modify", con_name, "wifi.mac-address-randomization", "0"],
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.cloned-mac-address", "preserve"],
                    # Reduce powersave issues
                    ["nmcli", "con", "modify", con_name, "802-11-wireless.powersave", "2"],
                ]:
                    r = subprocess.run(args, check=False, capture_output=True, text=True)
                    if r.returncode != 0:
                        print(f"[init] nmcli modify warn: {' '.join(args[3:])} -> {r.stderr.strip()}")
                # Reload the connection to apply changes
                r1 = subprocess.run(
                    ["nmcli", "con", "down", con_name],
                    check=False, capture_output=True, text=True
                )
                r2 = subprocess.run(
                    ["nmcli", "con", "up", con_name],
                    check=False, capture_output=True, text=True
                )
                if r1.returncode != 0: print(f"[init] nmcli down warn: {r1.stderr.strip()}")
                if r2.returncode != 0: print(f"[init] nmcli up warn: {r2.stderr.strip()}")
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
            runner, bound_port = await _start_web_server("0.0.0.0", desired_port, on_token_saved, ap_ssid, ap_password)
        except OSError:
            runner, bound_port = await _start_web_server("0.0.0.0", 0, on_token_saved, ap_ssid, ap_password)
        setup_url = f"http://{ap_ip}:{bound_port}/"
        print(setup_url)
        # Prepare QR image under project data dir
        project = _project_root()
        tmp_dir = project / ".setup"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Generate single Wi‑Fi QR with caption (SSID/Pass + URL text)
        qr_png = tmp_dir / "setup_qr.png"
        _generate_wifi_qr_with_caption(ap_ssid, ap_password, setup_url, qr_png)
        try:
            # Try to show QR with mpv; fallback to printing URL if mpv missing
            try:
                mpv_proc = await _display_with_mpv(qr_png)
            except FileNotFoundError:
                mpv_failed = True
                print(f"[init] mpv not found. Open this URL to configure: {setup_url}", file=sys.stderr)

            # Wait until TELEGRAM_BOT_TOKEN appears in env (set by on_token_saved)
            while not os.getenv("TELEGRAM_BOT_TOKEN"):
                await asyncio.sleep(0.5)
        finally:
            await runner.cleanup()

    await run_flow()


