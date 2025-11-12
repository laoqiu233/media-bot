"""Resolution selection screen."""

import asyncio
import logging
import subprocess

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import RESOLUTION_BACK, RESOLUTION_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)

# Common resolutions for Raspberry Pi
COMMON_RESOLUTIONS = [
    ("1920x1080", "1080p (Full HD)"),
    ("1280x720", "720p (HD)"),
    ("3840x2160", "4K (UHD)"),
    ("2560x1440", "1440p (QHD)"),
    ("1600x900", "900p"),
    ("1366x768", "768p"),
    ("1024x768", "XGA"),
]


async def _get_current_resolution() -> str | None:
    """Get current display resolution.

    Returns:
        Current resolution string (e.g., "1920x1080") or None
    """
    try:
        loop = asyncio.get_event_loop()

        # Try tvservice first (Raspberry Pi specific)
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["tvservice", "-s"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode == 0 and result.stdout:
            # Parse output like "state 0x120009 [HDMI CEA (16) RGB lim 16:9], 1920x1080 @ 60Hz"
            output = result.stdout
            if "x" in output:
                import re

                match = re.search(r"(\d+)x(\d+)", output)
                if match:
                    return f"{match.group(1)}x{match.group(2)}"

        # Try xrandr (if X11 is running)
        result2 = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["xrandr"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result2.returncode == 0 and result2.stdout:
            for line in result2.stdout.splitlines():
                if " connected " in line and "x" in line:
                    parts = line.split()
                    for part in parts:
                        if "x" in part and part[0].isdigit():
                            return part

        return None

    except Exception as e:
        logger.debug(f"Error getting current resolution: {e}")
        return None


async def _set_resolution(resolution: str) -> tuple[bool, str]:
    """Set display resolution.

    Args:
        resolution: Resolution string (e.g., "1920x1080")

    Returns:
        Tuple of (success, message)
    """
    try:
        width, height = map(int, resolution.split("x"))

        # For Raspberry Pi, we need to modify /boot/config.txt
        # This requires sudo and is risky, so we'll provide instructions
        # Format: hdmi_group=2 hdmi_mode=XX (for CEA modes) or hdmi_group=1 hdmi_mode=XX (for DMT modes)

        # Common CEA modes:
        # 16: 1920x1080 60Hz
        # 4: 1280x720 60Hz
        # 97: 3840x2160 60Hz

        mode_map = {
            "1920x1080": "hdmi_group=2\nhdmi_mode=16",
            "1280x720": "hdmi_group=2\nhdmi_mode=4",
            "3840x2160": "hdmi_group=2\nhdmi_mode=97",
        }

        config_lines = mode_map.get(
            resolution,
            f"# Add custom resolution:\n# hdmi_group=2\n# hdmi_mode=<mode_number>\n# For {width}x{height}, find appropriate mode in CEA or DMT table",
        )

        message = (
            f"To set resolution to {resolution}, edit `/boot/config.txt` and add:\n\n"
            f"```\n{config_lines}\n```\n\n"
            "Then reboot the system.\n\n"
            "Note: Some resolutions may require specific HDMI modes. "
            "Check Raspberry Pi documentation for available modes."
        )

        return False, message

    except Exception as e:
        logger.error(f"Error setting resolution: {e}")
        return False, f"Error: {str(e)}"


class ResolutionSelectionScreen(Screen):
    """Screen for selecting display resolution."""

    def get_name(self) -> str:
        """Get screen name."""
        return "resolution_selection"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the resolution selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        current_res = await _get_current_resolution()

        text = "🖥 *Resolution Selection*\n\n"
        if current_res:
            text += f"Current resolution: *{current_res}*\n\n"
        else:
            text += "Current resolution: Unknown\n\n"

        text += "Select display resolution:\n\n"
        text += "⚠️ *Note*: Changing resolution requires editing `/boot/config.txt` and rebooting.\n"
        text += "The bot will provide instructions after selection."

        keyboard = []
        for res, label in COMMON_RESOLUTIONS:
            keyboard.append(
                [InlineKeyboardButton(f"{res} ({label})", callback_data=f"{RESOLUTION_SELECT}{res}")]
            )

        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=RESOLUTION_BACK)])

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
        if query.data == RESOLUTION_BACK:
            return Navigation(next_screen="system_control")

        elif query.data.startswith(RESOLUTION_SELECT):
            resolution = query.data[len(RESOLUTION_SELECT) :]
            success, message = await _set_resolution(resolution)

            if success:
                await query.answer(f"Resolution set to {resolution}")
            else:
                await query.answer(message, show_alert=True)

            # Return to system control after showing message
            return Navigation(next_screen="system_control")

        return None

