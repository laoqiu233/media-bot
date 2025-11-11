"""TV control screen for HDMI-CEC."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import (
    TV_ACTIVE_SOURCE,
    TV_BACK,
    TV_MUTE,
    TV_OFF,
    TV_ON,
    TV_VOL_DOWN,
    TV_VOL_UP,
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


class TVScreen(Screen):
    """Screen for controlling TV via HDMI-CEC."""

    def __init__(self, cec_controller):
        """Initialize TV screen.

        Args:
            cec_controller: CEC controller
        """
        self.cec = cec_controller

    def get_name(self) -> str:
        """Get screen name."""
        return "tv"

    async def render(self, context: Context) -> ScreenRenderResult:
        try:
            cec_status = await self.cec.get_status()

            text = "📺 *TV Control (HDMI-CEC)*\n\n"

            if cec_status.get("available"):
                text += "✅ CEC is available\n\n"

                power_status = cec_status.get("power_status", "unknown")
                if power_status == "on":
                    text += "Power: 🟢 ON\n"
                elif power_status == "standby":
                    text += "Power: 🔴 STANDBY\n"
                else:
                    text += f"Power: {power_status}\n"

                if cec_status.get("tv_name"):
                    text += f"Device: {cec_status['tv_name']}\n"

                text += "\nUse the buttons below to control your TV:"

                keyboard = [
                    [
                        InlineKeyboardButton("🟢 Turn ON", callback_data=TV_ON),
                        InlineKeyboardButton("🔴 Turn OFF", callback_data=TV_OFF),
                    ],
                    [
                        InlineKeyboardButton(
                            "📺 Set Active Source", callback_data=TV_ACTIVE_SOURCE
                        ),
                    ],
                    [
                        InlineKeyboardButton("🔊 Volume +", callback_data=TV_VOL_UP),
                        InlineKeyboardButton("🔉 Volume -", callback_data=TV_VOL_DOWN),
                    ],
                    [
                        InlineKeyboardButton("🔇 Mute", callback_data=TV_MUTE),
                    ],
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data=TV_BACK),
                    ],
                ]

            else:
                text += "❌ CEC is not available\n\n"
                text += "Make sure:\n"
                text += "• Your TV supports HDMI-CEC\n"
                text += "• CEC is enabled in TV settings\n"
                text += "• HDMI cable is properly connected\n"
                text += "• CEC device path is correct in config"

                keyboard = [
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data=TV_BACK),
                    ],
                ]

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering TV screen: {e}")
            text = "📺 *TV Control*\n\nError loading CEC status."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data=TV_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    async def handle_callback(
        self,
        query: CallbackQuery,
        context: Context,
    ) -> ScreenHandlerResult:
        if query.data == TV_BACK:
            return Navigation(next_screen="main_menu")
        elif query.data == TV_ON:
            await self._tv_on(query)
        elif query.data == TV_OFF:
            await self._tv_off(query)
        elif query.data == TV_ACTIVE_SOURCE:
            await self._set_active_source(query)
        elif query.data == TV_VOL_UP:
            await self._volume_up(query)
        elif query.data == TV_VOL_DOWN:
            await self._volume_down(query)
        elif query.data == TV_MUTE:
            await self._mute(query)

    async def _tv_on(self, query: CallbackQuery) -> None:
        try:
            await query.answer("Turning TV on...")
            success = await self.cec.tv_on()

            if success:
                await query.answer("📺 TV turned on!", show_alert=True)
            else:
                await query.answer("Failed to turn on TV. Check CEC connection.", show_alert=True)

        except Exception as e:
            logger.error(f"Error turning TV on: {e}")
            await query.answer("Error", show_alert=True)

    async def _tv_off(self, query: CallbackQuery) -> None:
        try:
            await query.answer("Turning TV off...")
            success = await self.cec.tv_off()

            if success:
                await query.answer("📺 TV turned off!", show_alert=True)
            else:
                await query.answer("Failed to turn off TV. Check CEC connection.", show_alert=True)

        except Exception as e:
            logger.error(f"Error turning TV off: {e}")
            await query.answer("Error", show_alert=True)

    async def _set_active_source(self, query: CallbackQuery) -> None:
        try:
            await query.answer("Setting active source...")
            success = await self.cec.set_active_source()

            if success:
                await query.answer("✅ Set as active source!", show_alert=True)
            else:
                await query.answer("Failed to set active source.", show_alert=True)

        except Exception as e:
            logger.error(f"Error setting active source: {e}")
            await query.answer("Error", show_alert=True)

    async def _volume_up(self, query: CallbackQuery) -> None:
        try:
            success = await self.cec.volume_up()
            await query.answer("🔊 Volume up" if success else "Failed")
        except Exception as e:
            logger.error(f"Error increasing volume: {e}")
            await query.answer("Error", show_alert=True)

    async def _volume_down(self, query: CallbackQuery) -> None:
        try:
            success = await self.cec.volume_down()
            await query.answer("🔉 Volume down" if success else "Failed")
        except Exception as e:
            logger.error(f"Error decreasing volume: {e}")
            await query.answer("Error", show_alert=True)

    async def _mute(self, query: CallbackQuery) -> None:
        try:
            success = await self.cec.mute()
            await query.answer("🔇 Mute toggled" if success else "Failed")
        except Exception as e:
            logger.error(f"Error toggling mute: {e}")
            await query.answer("Error", show_alert=True)
