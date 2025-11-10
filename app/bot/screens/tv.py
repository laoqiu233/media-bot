"""TV control screen for HDMI-CEC."""

import logging
from typing import Dict, Any, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.screens.base import Screen

logger = logging.getLogger(__name__)


class TVScreen(Screen):
    """Screen for controlling TV via HDMI-CEC."""

    def __init__(self, screen_manager, cec_controller):
        """Initialize TV screen.

        Args:
            screen_manager: Screen manager instance
            cec_controller: CEC controller
        """
        super().__init__(screen_manager)
        self.cec = cec_controller

    def get_name(self) -> str:
        """Get screen name."""
        return "tv"

    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the TV control screen.

        Args:
            chat_id: Chat ID
            state: Screen state

        Returns:
            Tuple of (text, keyboard)
        """
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
                        InlineKeyboardButton("🟢 Turn ON", callback_data="tv:on:"),
                        InlineKeyboardButton("🔴 Turn OFF", callback_data="tv:off:"),
                    ],
                    [
                        InlineKeyboardButton("📺 Set Active Source", callback_data="tv:active_source:"),
                    ],
                    [
                        InlineKeyboardButton("🔊 Volume +", callback_data="tv:vol_up:"),
                        InlineKeyboardButton("🔉 Volume -", callback_data="tv:vol_down:"),
                    ],
                    [
                        InlineKeyboardButton("🔇 Mute", callback_data="tv:mute:"),
                    ],
                    [
                        InlineKeyboardButton("🔄 Refresh Status", callback_data="tv:refresh:"),
                    ],
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data="tv:back:"),
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
                        InlineKeyboardButton("🔄 Check Again", callback_data="tv:refresh:"),
                    ],
                    [
                        InlineKeyboardButton("« Back to Menu", callback_data="tv:back:"),
                    ],
                ]

            return text, InlineKeyboardMarkup(keyboard)

        except Exception as e:
            logger.error(f"Error rendering TV screen: {e}")
            text = "📺 *TV Control*\n\nError loading CEC status."
            keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="tv:back:")]]
            return text, InlineKeyboardMarkup(keyboard)

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle TV screen callbacks.

        Args:
            update: Telegram update
            context: Bot context
            action: Action identifier
            params: Additional parameters
        """
        chat_id = update.callback_query.message.chat_id

        if action == "back":
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

        elif action == "refresh":
            await update.callback_query.answer("Refreshing...")
            await self.refresh(chat_id)

        elif action == "on":
            await self._tv_on(update, context)

        elif action == "off":
            await self._tv_off(update, context)

        elif action == "active_source":
            await self._set_active_source(update, context)

        elif action == "vol_up":
            await self._volume_up(update, context)

        elif action == "vol_down":
            await self._volume_down(update, context)

        elif action == "mute":
            await self._mute(update, context)

    async def _tv_on(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Turn TV on.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            await update.callback_query.answer("Turning TV on...")
            success = await self.cec.tv_on()
            
            if success:
                await update.callback_query.answer("📺 TV turned on!", show_alert=True)
            else:
                await update.callback_query.answer(
                    "Failed to turn on TV. Check CEC connection.",
                    show_alert=True
                )
            
            # Refresh status
            chat_id = update.callback_query.message.chat_id
            await self.refresh(chat_id)

        except Exception as e:
            logger.error(f"Error turning TV on: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _tv_off(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Turn TV off.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            await update.callback_query.answer("Turning TV off...")
            success = await self.cec.tv_off()
            
            if success:
                await update.callback_query.answer("📺 TV turned off!", show_alert=True)
            else:
                await update.callback_query.answer(
                    "Failed to turn off TV. Check CEC connection.",
                    show_alert=True
                )
            
            # Refresh status
            chat_id = update.callback_query.message.chat_id
            await self.refresh(chat_id)

        except Exception as e:
            logger.error(f"Error turning TV off: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _set_active_source(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Set this device as active source.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            await update.callback_query.answer("Setting active source...")
            success = await self.cec.set_active_source()
            
            if success:
                await update.callback_query.answer(
                    "✅ Set as active source!",
                    show_alert=True
                )
            else:
                await update.callback_query.answer(
                    "Failed to set active source.",
                    show_alert=True
                )

        except Exception as e:
            logger.error(f"Error setting active source: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _volume_up(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Increase TV volume.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            success = await self.cec.volume_up()
            await update.callback_query.answer("🔊 Volume up" if success else "Failed")
        except Exception as e:
            logger.error(f"Error increasing volume: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _volume_down(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Decrease TV volume.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            success = await self.cec.volume_down()
            await update.callback_query.answer("🔉 Volume down" if success else "Failed")
        except Exception as e:
            logger.error(f"Error decreasing volume: {e}")
            await update.callback_query.answer("Error", show_alert=True)

    async def _mute(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Mute/unmute TV.

        Args:
            update: Telegram update
            context: Bot context
        """
        try:
            success = await self.cec.mute()
            await update.callback_query.answer("🔇 Mute toggled" if success else "Failed")
        except Exception as e:
            logger.error(f"Error toggling mute: {e}")
            await update.callback_query.answer("Error", show_alert=True)

