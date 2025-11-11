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


async def _start_web_server(host: str, port: int, on_token_saved) -> tuple[web.AppRunner, int]:
    """Start a minimal aiohttp server that serves a token form and handles submission.
    
    Returns:
        (runner, actual_port)
    """

    async def handle_index(_request: web.Request) -> web.Response:
        html_path = _templates_dir() / "setup.html"
        html = html_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def handle_submit(request: web.Request) -> web.Response:
        data = await request.post()
        token = (data.get("token") or "").strip()
        if not token:
            return web.Response(text="Token is required", status=400)
        await on_token_saved(token)
        return web.Response(
            text="Token saved. You can close this page. The app will continue.",
            content_type="text/plain",
        )

    app = web.Application()
    app.router.add_get("/", handle_index)
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
    return runner, actual_port


def _generate_qr_png(content: str, out_path: Path) -> None:
    img = qrcode.make(content)
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

    mpv_proc: Optional[subprocess.Popen] = None
    mpv_failed = False

    async def on_token_saved(token: str):
        # Persist to .env at project root
        env_path = project / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            content = []
        new_lines = _append_or_replace_env_line(content, "TELEGRAM_BOT_TOKEN", token)
        env_path.write_text("".join(new_lines), encoding="utf-8")

        # Also set for this process so we can proceed immediately
        os.environ["TELEGRAM_BOT_TOKEN"] = token

        # Close mpv window if running
        if mpv_proc and mpv_proc.poll() is None:
            try:
                mpv_proc.terminate()
            except Exception:
                pass

    async def run_flow():
        nonlocal mpv_proc, mpv_failed
        # Start server; if desired port is busy, fall back to ephemeral port 0
        try:
            runner, bound_port = await _start_web_server("0.0.0.0", desired_port, on_token_saved)
        except OSError:
            runner, bound_port = await _start_web_server("0.0.0.0", 0, on_token_saved)
        setup_url = f"http://{host_ip}:{bound_port}/"
        print(setup_url)
        # Prepare QR image file under project data dir
        project = _project_root()
        tmp_dir = project / ".setup"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        qr_png = tmp_dir / "setup_qr.png"
        _generate_qr_png(setup_url, qr_png)
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


