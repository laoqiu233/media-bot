"""System control screen."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    SYSTEM_CONTROL_AUDIO_OUTPUT,
    SYSTEM_CONTROL_BACK,
    SYSTEM_CONTROL_HDMI_PORT,
    SYSTEM_CONTROL_RESOLUTION,
    SYSTEM_CONTROL_SETUP,
)
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class SystemControlScreen(Screen):
    """Screen for system control options."""

    def get_name(self) -> str:
        """Get screen name."""
        return "system_control"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the system control screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        text = "⚙️ *System Control*\n\n"
        text += "Manage system settings and configuration:\n"

        keyboard = [
            [InlineKeyboardButton("🛠 Wi‑Fi / Token Setup", callback_data=SYSTEM_CONTROL_SETUP)],
            [InlineKeyboardButton("📺 Select HDMI Port", callback_data=SYSTEM_CONTROL_HDMI_PORT)],
            [InlineKeyboardButton("🖥 Select Resolution", callback_data=SYSTEM_CONTROL_RESOLUTION)],
            [InlineKeyboardButton("🔊 Audio Output", callback_data=SYSTEM_CONTROL_AUDIO_OUTPUT)],
            [InlineKeyboardButton("⬅️ Back", callback_data=SYSTEM_CONTROL_BACK)],
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
        if query.data == SYSTEM_CONTROL_SETUP:
            return Navigation(next_screen="setup_confirmation")

        elif query.data == SYSTEM_CONTROL_HDMI_PORT:
            return Navigation(next_screen="hdmi_port_selection")

        elif query.data == SYSTEM_CONTROL_RESOLUTION:
            return Navigation(next_screen="resolution_selection")

        elif query.data == SYSTEM_CONTROL_AUDIO_OUTPUT:
            return Navigation(next_screen="audio_output_selection")

        elif query.data == SYSTEM_CONTROL_BACK:
            return Navigation(next_screen="main_menu")

        return None
