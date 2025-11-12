"""Audio output selection screen."""

import asyncio
import logging
import subprocess

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import AUDIO_OUTPUT_BACK, AUDIO_OUTPUT_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)

# Audio output options for Raspberry Pi
AUDIO_OUTPUTS = [
    ("hdmi", "HDMI", "Audio through HDMI (TV speakers)"),
    ("analog", "3.5mm Jack", "Audio through 3.5mm headphone jack"),
    ("auto", "Auto", "Automatic detection"),
]


async def _get_current_audio_output() -> str | None:
    """Get current audio output setting.

    Returns:
        Current output type ("hdmi", "analog", "auto", or None)
    """
    try:
        loop = asyncio.get_event_loop()

        # Check /boot/config.txt for audio settings
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["grep", "-E", "^dtparam=audio|^dtoverlay.*audio", "/boot/config.txt"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode == 0 and result.stdout:
            output = result.stdout.lower()
            if "dtparam=audio=on" in output or "dtoverlay=vc4-kms-v3d" in output:
                # Check for explicit HDMI or analog setting
                if "hdmi" in output and "analog" not in output:
                    return "hdmi"
                elif "analog" in output:
                    return "analog"

        # Try to check current ALSA default device
        result2 = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["aplay", "-l"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result2.returncode == 0 and result2.stdout:
            # Look for HDMI or analog devices
            if "HDMI" in result2.stdout and "card" in result2.stdout:
                return "hdmi"
            elif "Headphones" in result2.stdout or "bcm2835" in result2.stdout:
                return "analog"

        return None

    except Exception as e:
        logger.debug(f"Error getting current audio output: {e}")
        return None


async def _set_audio_output(output_type: str) -> tuple[bool, str]:
    """Set audio output.

    Args:
        output_type: Output type ("hdmi", "analog", or "auto")

    Returns:
        Tuple of (success, message)
    """
    try:
        # For Raspberry Pi, audio output is controlled via /boot/config.txt
        # This requires sudo and is risky, so we'll provide instructions

        config_lines_map = {
            "hdmi": (
                "# For HDMI audio output, add or modify:\n"
                "dtparam=audio=on\n"
                "# Or use:\n"
                "dtoverlay=vc4-kms-v3d\n"
                "# HDMI audio is usually enabled by default"
            ),
            "analog": (
                "# For 3.5mm jack audio output, add:\n"
                "dtparam=audio=on\n"
                "# And ensure HDMI audio is disabled or set:\n"
                "# dtparam=audio=off  # if you want to disable HDMI audio"
            ),
            "auto": (
                "# For automatic audio detection:\n"
                "dtparam=audio=on\n"
                "# System will detect available audio outputs"
            ),
        }

        config_lines = config_lines_map.get(
            output_type,
            "# Add appropriate audio configuration",
        )

        message = (
            f"To set audio output to {output_type.upper()}, edit `/boot/config.txt` and add/modify:\n\n"
            f"```\n{config_lines}\n```\n\n"
            "Then reboot the system.\n\n"
            "**Alternative method (without reboot):**\n"
            "You can also use `raspi-config`:\n"
            "```bash\n"
            "sudo raspi-config\n"
            "# Navigate to: Advanced Options > Audio\n"
            "# Select your preferred output\n"
            "```\n\n"
            "**Quick test (temporary, until reboot):**\n"
            "```bash\n"
            "# For HDMI:\n"
            "amixer cset numid=3 2\n"
            "# For 3.5mm jack:\n"
            "amixer cset numid=3 1\n"
            "# For auto:\n"
            "amixer cset numid=3 0\n"
            "```"
        )

        return False, message

    except Exception as e:
        logger.error(f"Error setting audio output: {e}")
        return False, f"Error: {str(e)}"


class AudioOutputSelectionScreen(Screen):
    """Screen for selecting audio output."""

    def get_name(self) -> str:
        """Get screen name."""
        return "audio_output_selection"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the audio output selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        current_output = await _get_current_audio_output()

        text = "🔊 *Audio Output Selection*\n\n"
        if current_output:
            # Find the label for current output
            current_label = next(
                (label for key, label, _ in AUDIO_OUTPUTS if key == current_output),
                current_output.upper(),
            )
            text += f"Current output: *{current_label}*\n\n"
        else:
            text += "Current output: Unknown\n\n"

        text += "Select audio output destination:\n\n"
        text += "⚠️ *Note*: Changing audio output requires editing `/boot/config.txt` and rebooting.\n"
        text += "The bot will provide instructions after selection.\n\n"
        text += "You can also use the temporary method (until reboot) shown in the instructions."

        keyboard = []
        for key, label, description in AUDIO_OUTPUTS:
            button_text = f"{label}"
            if current_output == key:
                button_text = f"✓ {label}"
            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{AUDIO_OUTPUT_SELECT}{key}")]
            )

        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=AUDIO_OUTPUT_BACK)])

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
        if query.data == AUDIO_OUTPUT_BACK:
            return Navigation(next_screen="system_control")

        elif query.data.startswith(AUDIO_OUTPUT_SELECT):
            output_type = query.data[len(AUDIO_OUTPUT_SELECT) :]
            success, message = await _set_audio_output(output_type)

            if success:
                await query.answer(f"Audio output set to {output_type}")
            else:
                await query.answer(message, show_alert=True)

            # Return to system control after showing message
            return Navigation(next_screen="system_control")

        return None

