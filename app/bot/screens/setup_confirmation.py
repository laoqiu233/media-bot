"""Setup confirmation screen for Wi-Fi/Token setup."""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import SETUP_CANCEL, SETUP_CONFIRM
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)
from app.init_flow import ensure_telegram_token

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).resolve().parents[2]


async def _get_current_wifi() -> str | None:
    """Get current active Wi-Fi connection SSID.

    Returns:
        SSID string or None if not connected or unable to determine
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )

        if result.returncode == 0 and result.stdout:
            for line in result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    active, ssid = parts[0], parts[1]
                    if active == "yes" and ssid and ssid != "--":
                        return ssid

        # Alternative: check connection show
        result2 = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )

        if result2.returncode == 0 and result2.stdout:
            for line in result2.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    name, conn_type = parts[0], parts[1]
                    if conn_type == "802-11-wireless" and name:
                        return name

    except Exception as e:
        logger.debug(f"Error getting current Wi-Fi: {e}")

    return None


def _has_token() -> bool:
    """Check if Telegram bot token exists in environment or .env file.

    Returns:
        True if token exists, False otherwise
    """
    # Check environment variable first
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        return True

    # Check .env file
    env_path = _project_root() / ".env"
    if env_path.exists():
        try:
            content = env_path.read_text(encoding="utf-8")
            # Simple check for TELEGRAM_BOT_TOKEN line
            if "TELEGRAM_BOT_TOKEN" in content:
                for line in content.splitlines():
                    if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                        token_value = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if token_value:
                            return True
        except Exception as e:
            logger.debug(f"Error reading .env file: {e}")

    return False


class SetupConfirmationScreen(Screen):
    """Screen for confirming Wi-Fi/Token setup with warnings."""

    def get_name(self) -> str:
        """Get screen name."""
        return "setup_confirmation"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the setup confirmation screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        # Get current Wi-Fi connection
        current_wifi = await _get_current_wifi()
        has_token = _has_token()

        # Build warning text
        text = "⚠️ *Setup Confirmation*\n\n"
        text += "Before proceeding, please note:\n\n"

        warnings = []
        if current_wifi:
            warnings.append(f"📶 Current Wi‑Fi: *{current_wifi}*")
            warnings.append("⚠️ Your current Wi‑Fi connection will be *reset*")
        else:
            warnings.append("📶 No active Wi‑Fi connection detected")

        if has_token:
            warnings.append("⚠️ Your Telegram bot token will be *erased*")

        text += "\n".join(warnings)
        text += "\n\n"
        text += "The setup wizard will:\n"
        text += "• Create a new Wi‑Fi hotspot\n"
        text += "• Display QR codes on your TV\n"
        text += "• Allow you to configure new Wi‑Fi and token\n\n"
        text += "Do you want to continue?"

        keyboard = [
            [
                InlineKeyboardButton("✅ Continue", callback_data=SETUP_CONFIRM),
                InlineKeyboardButton("❌ Cancel", callback_data=SETUP_CANCEL),
            ],
        ]

        return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle button callbacks.

        Args:
            query: The callback query
            context: The context object

        Returns:
            Navigation or None
        """
        if query.data == SETUP_CONFIRM:
            await query.answer("Starting setup wizard. Check the display for QR codes.")
            # Start setup in background
            asyncio.create_task(ensure_telegram_token(force=True))
            return Navigation(next_screen="main_menu")

        elif query.data == SETUP_CANCEL:
            await query.answer("Setup cancelled.")
            return Navigation(next_screen="main_menu")

        return None

