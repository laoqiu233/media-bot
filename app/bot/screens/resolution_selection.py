"""Resolution selection screen using xrandr."""

import asyncio
import logging
import re
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


class DisplayMode:
    """Represents a display resolution mode."""

    def __init__(self, resolution: str, refresh_rate: str | None = None, current: bool = False):
        """Initialize display mode.

        Args:
            resolution: Resolution string (e.g., "1920x1080")
            refresh_rate: Refresh rate (e.g., "60.00")
            current: Whether this is the current active mode
        """
        self.resolution = resolution
        self.refresh_rate = refresh_rate
        self.current = current

    def __str__(self) -> str:
        """Get string representation."""
        if self.refresh_rate:
            return f"{self.resolution}@{self.refresh_rate}Hz"
        return self.resolution


async def _get_connected_display() -> tuple[str | None, str | None]:
    """Get connected display output name and current resolution.

    Returns:
        Tuple of (output_name, current_resolution) or (None, None)
    """
    try:
        loop = asyncio.get_event_loop()
        logger.debug("Running xrandr to get connected display")
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["xrandr"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )

        if result.returncode != 0:
            logger.warning(f"xrandr failed with return code {result.returncode}: {result.stderr}")
            return None, None

        logger.debug(f"xrandr output:\n{result.stdout}")

        current_output = None
        current_resolution = None

        for line in result.stdout.splitlines():
            # Look for connected output line like:
            # HDMI-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 509mm x 286mm
            if " connected " in line:
                parts = line.split()
                if len(parts) >= 2:
                    output_name = parts[0]
                    # Check if it's connected (not disconnected)
                    if "disconnected" not in line.lower():
                        current_output = output_name
                        logger.debug(f"Found connected output: {output_name}")

                        # Find current resolution in the line
                        # Format: "HDMI-1 connected primary 1920x1080+0+0 ..."
                        for part in parts:
                            # Look for resolution pattern like "1920x1080" or "1920x1080+0+0"
                            if "x" in part and part[0].isdigit():
                                # Remove position offsets (+0+0)
                                res_part = part.split("+")[0]
                                if re.match(r"\d+x\d+", res_part):
                                    current_resolution = res_part
                                    logger.debug(f"Found current resolution: {current_resolution}")
                                    break

                        break

        logger.info(f"Connected display: {current_output}, Current resolution: {current_resolution}")
        return current_output, current_resolution

    except FileNotFoundError:
        logger.warning("xrandr utility not found. Install with: sudo apt install x11-xserver-utils")
    except Exception as e:
        logger.error(f"Error getting connected display: {e}", exc_info=True)
        return None, None


async def _get_available_resolutions(output_name: str) -> list[DisplayMode]:
    """Get available resolutions for a display output.

    Args:
        output_name: Display output name (e.g., "HDMI-1")

    Returns:
        List of available display modes
    """
    modes = []
    try:
        loop = asyncio.get_event_loop()
        logger.debug(f"Getting available resolutions for output: {output_name}")
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["xrandr"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )

        if result.returncode != 0:
            logger.warning(f"xrandr failed with return code {result.returncode}")
            return modes

        # Parse xrandr output to find modes for the specified output
        in_output_section = False
        current_resolution = None

        for line in result.stdout.splitlines():
            # Check if we're in the section for this output
            if line.startswith(output_name):
                in_output_section = True
                logger.debug(f"Found output section: {line}")
                # Extract current resolution from the output line
                # Format: "HDMI-1 connected primary 1920x1080+0+0 ..."
                parts = line.split()
                for part in parts:
                    if "x" in part and part[0].isdigit():
                        res_part = part.split("+")[0]
                        if re.match(r"\d+x\d+", res_part):
                            current_resolution = res_part
                            logger.debug(f"Current resolution from output line: {current_resolution}")
                            break
                continue

            # If we hit another output, stop parsing
            if in_output_section and re.match(r"^\w+-\d+", line):
                logger.debug(f"Hit another output, stopping: {line}")
                break

            # Parse mode lines (indented with spaces)
            if in_output_section and line.startswith("   "):
                # Format: "   1920x1080     60.00*+"
                # or:     "   1920x1080     60.00 +"
                # or:     "   1920x1080     60.00"
                line = line.strip()
                logger.debug(f"Parsing mode line: {line}")
                parts = re.split(r"\s+", line)

                if len(parts) >= 1:
                    resolution = parts[0]
                    # Check if it's a valid resolution format
                    if re.match(r"\d+x\d+", resolution):
                        refresh_rate = None
                        is_current = False

                        # Check for refresh rate and current indicator
                        if len(parts) >= 2:
                            refresh_part = parts[1]
                            # Remove * (current) and + (preferred) indicators
                            refresh_rate = refresh_part.replace("*", "").replace("+", "").strip()
                            is_current = "*" in refresh_part

                        # Use current resolution from output line if available
                        if resolution == current_resolution:
                            is_current = True

                        logger.debug(f"Found mode: {resolution}, refresh: {refresh_rate}, current: {is_current}")
                        modes.append(DisplayMode(resolution, refresh_rate, is_current))

        # Sort modes: current first, then by resolution (largest first)
        modes.sort(key=lambda m: (not m.current, -int(m.resolution.split("x")[0])), reverse=False)
        logger.info(f"Found {len(modes)} available resolutions for {output_name}")

    except Exception as e:
        logger.error(f"Error getting available resolutions: {e}", exc_info=True)

    return modes


async def _set_resolution(output_name: str, resolution: str) -> tuple[bool, str]:
    """Set display resolution using xrandr.

    Args:
        output_name: Display output name (e.g., "HDMI-1")
        resolution: Resolution string (e.g., "1920x1080")

    Returns:
        Tuple of (success, message)
    """
    try:
        loop = asyncio.get_event_loop()

        logger.info(f"Setting resolution to {resolution} for output {output_name}")

        # Use xrandr to set the resolution
        # Format: xrandr --output <output> --mode <resolution>
        cmd = ["xrandr", "--output", output_name, "--mode", resolution]
        logger.debug(f"Running command: {' '.join(cmd)}")

        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ),
        )

        logger.debug(f"xrandr return code: {result.returncode}")
        if result.stdout:
            logger.debug(f"xrandr stdout: {result.stdout}")
        if result.stderr:
            logger.debug(f"xrandr stderr: {result.stderr}")

        if result.returncode == 0:
            logger.info(f"Successfully set resolution to {resolution} for {output_name}")
            return True, f"Resolution changed to {resolution}"
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"Failed to set resolution: {error_msg.strip()}")
            return False, f"Failed to set resolution: {error_msg.strip()}"

    except Exception as e:
        logger.error(f"Error setting resolution: {e}", exc_info=True)
        return False, f"Error: {str(e)}"


class ResolutionSelectionScreen(Screen):
    """Screen for selecting display resolution using xrandr."""

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
        output_name, current_res = await _get_connected_display()

        text = "🖥 *Resolution Selection*\n\n"

        if not output_name:
            text += "❌ No connected display detected.\n\n"
            text += "Make sure:\n"
            text += "• A display is connected via HDMI\n"
            text += "• X server is running\n"
            text += "• `xrandr` utility is installed (`sudo apt install x11-xserver-utils`)\n"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=RESOLUTION_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        text += f"Display: *{output_name}*\n"
        if current_res:
            text += f"Current resolution: *{current_res}*\n\n"
        else:
            text += "Current resolution: Unknown\n\n"

        # Get available resolutions
        modes = await _get_available_resolutions(output_name)

        if not modes:
            text += "⚠️ No available resolutions found.\n"
            text += "The display may not support resolution querying."
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=RESOLUTION_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        text += "Available resolutions:\n"

        keyboard = []
        for mode in modes:
            button_text = str(mode)
            if mode.current:
                button_text = f"✓ {button_text} (Current)"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{RESOLUTION_SELECT}{output_name}:{mode.resolution}"
                    )
                ]
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
            # Format: "resolution:select:HDMI-1:1920x1080"
            data = query.data[len(RESOLUTION_SELECT) :]
            logger.debug(f"Resolution selection callback data: {data}")
            parts = data.split(":")
            logger.debug(f"Split parts: {parts}")
            if len(parts) >= 2:
                output_name = parts[0]
                resolution = parts[1]
                logger.info(f"Attempting to set resolution: {resolution} for output: {output_name}")
                success, message = await _set_resolution(output_name, resolution)

                if success:
                    logger.info(f"Resolution change successful: {message}")
                    await query.answer(f"Resolution set to {resolution}")
                else:
                    logger.error(f"Resolution change failed: {message}")
                    await query.answer(message, show_alert=True)

                # Return to system control after showing message
                return Navigation(next_screen="system_control")
            else:
                logger.warning(f"Invalid resolution data format: {data} (expected 'output:resolution')")
                await query.answer("Invalid resolution data", show_alert=True)

        return None
