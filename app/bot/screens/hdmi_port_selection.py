"""HDMI port selection screen."""

import asyncio
import logging
import subprocess

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import HDMI_PORT_BACK, HDMI_PORT_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


async def _get_current_hdmi_port() -> str | None:
    """Get current HDMI port setting.

    Returns:
        Current port ("0", "1", or None if unable to determine)
    """
    try:
        loop = asyncio.get_event_loop()
        # Check config.txt for hdmi_group and hdmi_mode settings
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["grep", "-E", "^hdmi_(group|mode|drive)", "/boot/config.txt"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode == 0 and result.stdout:
            # Look for hdmi_group=2 (CEA) or hdmi_group=1 (DMT)
            # For now, we'll use a simpler approach - check which HDMI is active
            pass

        # Try vcgencmd to check display power state
        result2 = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["vcgencmd", "display_power"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        # For now, return None (unknown) - user can select manually
        return None

    except Exception as e:
        logger.debug(f"Error getting current HDMI port: {e}")
        return None


async def _set_hdmi_port(port: str) -> tuple[bool, str]:
    """Set HDMI port.

    Args:
        port: Port to use ("0", "1", or "auto")

    Returns:
        Tuple of (success, message)
    """
    try:
        loop = asyncio.get_event_loop()

        if port == "auto":
            # Remove explicit HDMI port settings from config.txt
            # This is complex and requires sudo, so we'll just inform the user
            return (
                False,
                "Auto mode requires manual configuration in /boot/config.txt. Please edit the file and remove hdmi_force_hotplug or set hdmi_group=0.",
            )

        # For HDMI 0 or 1, we need to modify /boot/config.txt
        # This requires sudo and is risky, so we'll provide instructions
        return (
            False,
            f"To set HDMI port {port}, edit /boot/config.txt and add:\nhdmi_force_hotplug=1\nhdmi_group=2\nThen reboot the system.",
        )

    except Exception as e:
        logger.error(f"Error setting HDMI port: {e}")
        return False, f"Error: {str(e)}"


class HDMIPortSelectionScreen(Screen):
    """Screen for selecting HDMI port."""

    def get_name(self) -> str:
        """Get screen name."""
        return "hdmi_port_selection"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the HDMI port selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        current_port = await _get_current_hdmi_port()

        text = "📺 *HDMI Port Selection*\n\n"
        if current_port:
            text += f"Current port: HDMI {current_port}\n\n"
        else:
            text += "Current port: Unknown\n\n"

        text += "Select which HDMI port to use for display output:\n\n"
        text += "⚠️ *Note*: Changing HDMI port requires editing `/boot/config.txt` and rebooting.\n"
        text += "The bot will provide instructions after selection."

        keyboard = [
            [InlineKeyboardButton("HDMI 0", callback_data=f"{HDMI_PORT_SELECT}0")],
            [InlineKeyboardButton("HDMI 1", callback_data=f"{HDMI_PORT_SELECT}1")],
            [InlineKeyboardButton("Auto (Default)", callback_data=f"{HDMI_PORT_SELECT}auto")],
            [InlineKeyboardButton("⬅️ Back", callback_data=HDMI_PORT_BACK)],
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
        if query.data == HDMI_PORT_BACK:
            return Navigation(next_screen="system_control")

        elif query.data.startswith(HDMI_PORT_SELECT):
            port = query.data[len(HDMI_PORT_SELECT) :]
            success, message = await _set_hdmi_port(port)

            if success:
                await query.answer(f"HDMI port set to {port}")
            else:
                await query.answer(message, show_alert=True)

            # Return to system control after showing message
            return Navigation(next_screen="system_control")

        return None

