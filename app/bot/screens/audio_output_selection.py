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


async def _get_available_sinks() -> list[tuple[str, str]]:
    """Get list of available audio sinks.

    Returns:
        List of tuples (sink_name, display_name)
    """
    sinks = []
    try:
        loop = asyncio.get_event_loop()

        # Run pactl list short sinks
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["pactl", "list", "short", "sinks"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            ),
        )

        if result.returncode != 0:
            logger.warning(f"pactl command failed: {result.stderr}")
            return sinks

        if not result.stdout:
            logger.warning("pactl returned no output")
            return sinks

        # Parse output: index<TAB>name<TAB>description<TAB>state...
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = line.split("\t")
            if len(parts) >= 2:
                sink_name = parts[1].strip()
                description = parts[2].strip() if len(parts) > 2 else ""

                # Create display name
                name_lower = sink_name.lower()
                desc_lower = description.lower()

                if "hdmi" in name_lower or "hdmi" in desc_lower:
                    display_name = "HDMI Audio"
                elif "bcm2835" in name_lower or "analog" in name_lower or "stereo" in name_lower:
                    display_name = "3.5mm Jack (Analog)"
                else:
                    # Use description or last part of name
                    display_name = description or sink_name.split(".")[-1] if "." in sink_name else sink_name

                sinks.append((sink_name, display_name))
                logger.debug(f"Found sink: {sink_name} -> {display_name}")

    except FileNotFoundError:
        logger.error("pactl command not found")
    except Exception as e:
        logger.error(f"Error getting audio sinks: {e}", exc_info=True)

    return sinks


async def _get_current_default_sink() -> str | None:
    """Get the name of the current default sink.

    Returns:
        Sink name or None
    """
    try:
        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["pactl", "get-default-sink"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode == 0:
            return result.stdout.strip()

    except Exception as e:
        logger.debug(f"Error getting default sink: {e}")

    return None


async def _switch_to_sink(sink_name: str) -> tuple[bool, str]:
    """Switch audio output to the specified sink.

    Uses the same logic as prerun.sh (lines 13-25).

    Args:
        sink_name: Name of the sink to switch to

    Returns:
        Tuple of (success, message)
    """
    try:
        loop = asyncio.get_event_loop()

        # Set default sink (like prerun.sh line 17)
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["pactl", "set-default-sink", sink_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode != 0:
            return False, f"Failed to set default sink: {result.stderr}"

        # Move all current playback streams to new sink (like prerun.sh lines 20-22)
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["pactl", "list", "short", "sink-inputs"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ),
        )

        if result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    input_id = line.split()[0]
                    await loop.run_in_executor(
                        None,
                        lambda inp=input_id: subprocess.run(
                            ["pactl", "move-sink-input", inp, sink_name],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=1,
                        ),
                    )

        return True, "✅ Audio output switched successfully"

    except Exception as e:
        logger.error(f"Error switching audio sink: {e}", exc_info=True)
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
        sinks = await _get_available_sinks()
        current_sink = await _get_current_default_sink()

        text = "🔊 *Audio Output Selection*\n\n"

        if not sinks:
            text += "⚠️ No audio sinks found.\n\n"
            text += "Make sure PulseAudio or PipeWire is running."
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=AUDIO_OUTPUT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        if current_sink:
            # Find current sink in the list
            current_display = next((display for name, display in sinks if name == current_sink), None)
            if current_display:
                text += f"Current: *{current_display}*\n\n"
            else:
                text += f"Current: *{current_sink}*\n\n"
        else:
            text += "Current: Unknown\n\n"

        text += "Select audio output:\n"

        keyboard = []
        for sink_name, display_name in sinks:
            button_text = display_name
            if current_sink and sink_name == current_sink:
                button_text = f"✓ {display_name}"

            # Store sink name in callback data
            keyboard.append(
                [InlineKeyboardButton(button_text, callback_data=f"{AUDIO_OUTPUT_SELECT}{sink_name}")]
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
            sink_name = query.data[len(AUDIO_OUTPUT_SELECT) :]

            if not sink_name:
                await query.answer("Error: No sink name provided", show_alert=True)
                return None

            logger.info(f"Switching to audio sink: {sink_name}")

            success, message = await _switch_to_sink(sink_name)

            if success:
                # Find display name for the message
                sinks = await _get_available_sinks()
                display_name = next((display for name, display in sinks if name == sink_name), sink_name)
                await query.answer(f"✅ Switched to {display_name}")
            else:
                await query.answer(message, show_alert=True)

            # Stay on the same screen to show updated state
            return None

        return None
