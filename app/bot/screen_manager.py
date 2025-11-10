"""Screen manager for handling navigation and active messages."""

import logging
from typing import Dict, Optional, Any

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class ScreenManager:
    """Manages screen navigation and active messages for each chat."""

    def __init__(self):
        """Initialize the screen manager."""
        self.screens: Dict[str, "Screen"] = {}
        self.chat_sessions: Dict[int, Dict[str, Any]] = {}

    def register_screen(self, screen: "Screen") -> None:
        """Register a screen.

        Args:
            screen: Screen instance to register
        """
        screen_name = screen.get_name()
        self.screens[screen_name] = screen
        logger.info(f"Registered screen: {screen_name}")

    def get_screen(self, screen_name: str) -> Optional["Screen"]:
        """Get a registered screen by name.

        Args:
            screen_name: Name of the screen

        Returns:
            Screen instance or None if not found
        """
        return self.screens.get(screen_name)

    def _get_session(self, chat_id: int) -> Dict[str, Any]:
        """Get or create a session for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            Session dictionary
        """
        if chat_id not in self.chat_sessions:
            self.chat_sessions[chat_id] = {
                "message_id": None,
                "screen": "main_menu",
                "state": {},
                "history": [],
            }
        return self.chat_sessions[chat_id]

    def get_active_screen(self, chat_id: int) -> Optional["Screen"]:
        """Get the active screen for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            Active screen instance or None
        """
        session = self._get_session(chat_id)
        screen_name = session["screen"]
        return self.get_screen(screen_name)

    def get_screen_state(self, chat_id: int) -> Dict[str, Any]:
        """Get the state for the active screen.

        Args:
            chat_id: Chat ID

        Returns:
            Screen state dictionary
        """
        session = self._get_session(chat_id)
        return session.get("state", {})

    def set_screen_state(self, chat_id: int, state: Dict[str, Any]) -> None:
        """Set the state for the active screen.

        Args:
            chat_id: Chat ID
            state: Screen state dictionary
        """
        session = self._get_session(chat_id)
        session["state"] = state

    async def navigate_to(
        self,
        chat_id: int,
        screen_name: str,
        add_to_history: bool = True,
        **kwargs,
    ) -> None:
        """Navigate to a screen.

        Args:
            chat_id: Chat ID
            screen_name: Target screen name
            add_to_history: Whether to add current screen to history
            **kwargs: Additional context for the target screen
        """
        session = self._get_session(chat_id)
        current_screen_name = session["screen"]
        current_screen = self.get_screen(current_screen_name)

        # Add to history if requested
        if add_to_history and current_screen_name != screen_name:
            if current_screen_name not in session["history"][-1:]:
                session["history"].append(current_screen_name)

        # Call on_exit for current screen
        if current_screen:
            await current_screen.on_exit(chat_id)

        # Update session
        session["screen"] = screen_name
        session["state"] = {}  # Reset state for new screen

        # Get new screen
        new_screen = self.get_screen(screen_name)
        if not new_screen:
            logger.error(f"Screen not found: {screen_name}")
            return

        # Call on_enter for new screen
        await new_screen.on_enter(chat_id, **kwargs)

        # Update the active message
        await self.update_active_message(chat_id)

        logger.info(f"Navigated to {screen_name} for chat {chat_id}")

    async def go_back(self, chat_id: int) -> None:
        """Navigate back to the previous screen.

        Args:
            chat_id: Chat ID
        """
        session = self._get_session(chat_id)
        history = session["history"]

        if history:
            previous_screen = history.pop()
            await self.navigate_to(chat_id, previous_screen, add_to_history=False)
        else:
            # No history, go to main menu
            await self.navigate_to(chat_id, "main_menu", add_to_history=False)

    async def update_active_message(self, chat_id: int) -> None:
        """Update the active message for a chat.

        Args:
            chat_id: Chat ID
        """
        session = self._get_session(chat_id)
        message_id = session.get("message_id")
        screen = self.get_active_screen(chat_id)

        if not screen:
            logger.error(f"No active screen for chat {chat_id}")
            return

        # Render the screen
        text, keyboard = await screen.render(chat_id, session["state"])

        # Get bot instance from context
        # This will be set when we update the message from a callback or message handler
        # For now, we store the rendered content and update later
        session["_rendered_text"] = text
        session["_rendered_keyboard"] = keyboard

    async def create_or_update_active_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
    ) -> None:
        """Create a new active message or update existing one.

        Args:
            update: Telegram update
            context: Bot context
            chat_id: Chat ID
        """
        session = self._get_session(chat_id)
        screen = self.get_active_screen(chat_id)

        if not screen:
            logger.error(f"No active screen for chat {chat_id}")
            return

        # Render the screen
        text, keyboard = await screen.render(chat_id, session["state"])

        message_id = session.get("message_id")

        # Try to update existing message first
        if message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=keyboard,
                )
                logger.debug(f"Updated message {message_id} for chat {chat_id}")
                return
            except Exception as e:
                logger.debug(f"Could not update message {message_id}: {e}")
                # Message might have been deleted, create a new one

        # Create new message
        try:
            if update.callback_query:
                # If from callback, try to edit the callback message
                try:
                    message = await update.callback_query.edit_message_text(
                        text=text,
                        reply_markup=keyboard,
                    )
                    session["message_id"] = message.message_id
                    logger.info(
                        f"Created active message {message.message_id} for chat {chat_id}"
                    )
                    return
                except Exception as e:
                    logger.debug(f"Could not edit callback message: {e}")

            # Send new message
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            session["message_id"] = message.message_id
            logger.info(
                f"Created active message {message.message_id} for chat {chat_id}"
            )
        except Exception as e:
            logger.error(f"Error creating active message: {e}")

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle a callback query.

        Args:
            update: Telegram update
            context: Bot context
        """
        query = update.callback_query
        await query.answer()

        chat_id = query.message.chat_id
        data = query.data

        # Parse callback data: screen:action:params
        parts = data.split(":", 2)
        if len(parts) < 2:
            logger.warning(f"Invalid callback data format: {data}")
            return

        screen_name = parts[0]
        action = parts[1]
        params = parts[2] if len(parts) > 2 else ""

        # Get the target screen
        screen = self.get_screen(screen_name)
        if not screen:
            logger.error(f"Screen not found for callback: {screen_name}")
            return

        # Handle the callback
        await screen.handle_callback(update, context, action, params)

        # Update the active message
        await self.create_or_update_active_message(update, context, chat_id)

    def clear_session(self, chat_id: int) -> None:
        """Clear the session for a chat.

        Args:
            chat_id: Chat ID
        """
        if chat_id in self.chat_sessions:
            del self.chat_sessions[chat_id]
            logger.info(f"Cleared session for chat {chat_id}")

