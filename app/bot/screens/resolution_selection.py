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
            # Format refresh rate nicely (remove trailing zeros)
            rate = self.refresh_rate.rstrip("0").rstrip(".")
            return f"{self.resolution}@{rate}Hz"
        return self.resolution

    def get_mode_string(self) -> str:
        """Get mode string for xrandr command."""
        return self.resolution

    def get_rate_string(self) -> str | None:
        """Get rate string for xrandr command."""
        return self.refresh_rate


async def _get_connected_display() -> tuple[str | None, str | None, str | None]:
    """Get connected display output name, current resolution, and refresh rate.

    Returns:
        Tuple of (output_name, current_resolution, current_rate) or (None, None, None)
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
            return None, None, None

        logger.debug(f"xrandr output:\n{result.stdout}")

        current_output = None
        current_resolution = None
        current_rate = None

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

                        # Now find the current refresh rate by looking at the mode lines
                        # We'll parse the next few lines to find the mode with *
                        break

        # If we found a connected output, look for its current refresh rate
        if current_output and current_resolution:
            in_output_section = False
            for line in result.stdout.splitlines():
                if line.startswith(current_output):
                    in_output_section = True
                    continue
                
                # If we hit another output, stop
                if in_output_section and re.match(r"^\w+-\d+", line):
                    break
                
                # Look for mode line with current resolution and * marker
                if in_output_section and line.startswith("   ") and current_resolution in line:
                    # Format: "   1280x720      60.00*   50.00    59.94"
                    parts = re.split(r"\s+", line.strip())
                    if len(parts) >= 2 and parts[0] == current_resolution:
                        # Find the refresh rate with *
                        for refresh_part in parts[1:]:
                            if "*" in refresh_part:
                                current_rate = refresh_part.replace("*", "").replace("+", "").strip()
                                logger.debug(f"Found current refresh rate: {current_rate}")
                                break
                    break

        logger.info(
            f"Connected display: {current_output}, "
            f"Current resolution: {current_resolution}, "
            f"Current rate: {current_rate}"
        )
        return current_output, current_resolution, current_rate

    except FileNotFoundError:
        logger.warning("xrandr utility not found. Install with: sudo apt install x11-xserver-utils")
        return None, None, None
    except Exception as e:
        logger.error(f"Error getting connected display: {e}", exc_info=True)
        return None, None, None


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
        current_rate = None

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
            # Format can be:
            # "   1920x1080     60.00*+   50.00    59.94    30.00"
            # First part is resolution, rest are refresh rates
            if in_output_section and line.startswith("   "):
                line = line.strip()
                logger.debug(f"Parsing mode line: {line}")
                parts = re.split(r"\s+", line)

                if len(parts) >= 1:
                    resolution = parts[0]
                    # Check if it's a valid resolution format
                    if re.match(r"\d+x\d+", resolution):
                        # Parse all refresh rates for this resolution
                        # Parts[1:] contains all refresh rates
                        for refresh_part in parts[1:]:
                            # Skip if it's not a number (could be indicators like +)
                            if not re.match(r"^\d+\.?\d*", refresh_part):
                                continue

                            # Extract refresh rate (remove * and + indicators)
                            refresh_rate = refresh_part.replace("*", "").replace("+", "").strip()
                            
                            # Check if this is the current mode
                            # It's current if resolution matches AND has * marker
                            is_current = False
                            if resolution == current_resolution and "*" in refresh_part:
                                is_current = True
                                # Store the current rate for reference
                                if not current_rate:
                                    current_rate = refresh_rate

                            logger.debug(
                                f"Found mode: {resolution}, refresh: {refresh_rate}, current: {is_current}"
                            )
                            modes.append(DisplayMode(resolution, refresh_rate, is_current))

        # Sort modes: current first, then by resolution (largest first), then by refresh rate
        modes.sort(
            key=lambda m: (
                not m.current,
                -int(m.resolution.split("x")[0]),
                float(m.refresh_rate) if m.refresh_rate else 0,
            ),
            reverse=False,
        )
        logger.info(f"Found {len(modes)} available resolution/refresh combinations for {output_name}")

    except Exception as e:
        logger.error(f"Error getting available resolutions: {e}", exc_info=True)

    return modes


async def _set_resolution(output_name: str, resolution: str, refresh_rate: str | None = None) -> tuple[bool, str]:
    """Set display resolution using xrandr.

    Args:
        output_name: Display output name (e.g., "HDMI-1")
        resolution: Resolution string (e.g., "1920x1080")
        refresh_rate: Refresh rate string (e.g., "60.00") - optional

    Returns:
        Tuple of (success, message)
    """
    try:
        loop = asyncio.get_event_loop()

        logger.info(f"Setting resolution to {resolution}" + (f" @ {refresh_rate}Hz" if refresh_rate else "") + f" for output {output_name}")

        # Use xrandr to set the resolution
        # Format: xrandr --output <output> --mode <resolution> [--rate <refresh_rate>]
        cmd = ["xrandr", "--output", output_name, "--mode", resolution]
        if refresh_rate:
            cmd.extend(["--rate", refresh_rate])
        
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
            rate_str = f" @ {refresh_rate}Hz" if refresh_rate else ""
            logger.info(f"Successfully set resolution to {resolution}{rate_str} for {output_name}")
            return True, f"Resolution changed to {resolution}{rate_str}"
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            error_msg = error_msg.strip()
            logger.error(f"Failed to set resolution: {error_msg}")
            
            # Create a user-friendly error message
            # Check for common xrandr errors
            if "cannot find mode" in error_msg.lower() or "badmatch" in error_msg.lower():
                return False, f"Resolution {resolution} not available for {output_name}"
            elif "X Error" in error_msg or "BadMatch" in error_msg:
                return False, f"Resolution {resolution} not supported by display"
            else:
                # Return a concise error message (keep it short for Telegram)
                # Extract first line or truncate
                first_line = error_msg.split("\n")[0] if "\n" in error_msg else error_msg
                if len(first_line) > 150:
                    first_line = first_line[:147] + "..."
                return False, f"Failed: {first_line}"

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
        output_name, current_res, current_rate = await _get_connected_display()

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

            # Include both resolution and refresh rate in callback data
            # Format: "output:resolution:rate" or "output:resolution" if no rate
            if mode.refresh_rate:
                callback_data = f"{RESOLUTION_SELECT}{output_name}:{mode.resolution}:{mode.refresh_rate}"
            else:
                callback_data = f"{RESOLUTION_SELECT}{output_name}:{mode.resolution}"

            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=callback_data)]
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
            # Format: "resolution:select:HDMI-1:1920x1080:60.00" or "resolution:select:HDMI-1:1920x1080"
            data = query.data[len(RESOLUTION_SELECT) :]
            logger.debug(f"Resolution selection callback data: {data}")
            parts = data.split(":")
            logger.debug(f"Split parts: {parts}")
            if len(parts) >= 2:
                output_name = parts[0]
                resolution = parts[1]
                refresh_rate = parts[2] if len(parts) >= 3 else None
                
                logger.info(
                    f"Attempting to set resolution: {resolution}"
                    + (f" @ {refresh_rate}Hz" if refresh_rate else "")
                    + f" for output: {output_name}"
                )
                success, message = await _set_resolution(output_name, resolution, refresh_rate)

                if success:
                    logger.info(f"Resolution change successful: {message}")
                    await query.answer(f"Resolution set to {resolution}" + (f" @ {refresh_rate}Hz" if refresh_rate else ""))
                else:
                    logger.error(f"Resolution change failed: {message}")
                    # Telegram has a 200 character limit for callback query answers
                    # Truncate message if too long
                    max_length = 200
                    display_message = message
                    if len(display_message) > max_length:
                        display_message = display_message[:max_length - 3] + "..."
                    await query.answer(display_message, show_alert=True)

                # Return to system control after showing message
                return Navigation(next_screen="system_control")
            else:
                logger.warning(f"Invalid resolution data format: {data} (expected 'output:resolution[:rate]')")
                await query.answer("Invalid resolution data", show_alert=True)

        return None
