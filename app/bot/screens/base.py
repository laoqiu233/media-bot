"""Base screen class for the bot UI system."""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


class Screen(ABC):
    """Abstract base class for bot screens.

    Each screen represents a single state in the bot's UI.
    Screens are responsible for rendering their content and handling user interactions.
    """

    def __init__(self, screen_manager: "ScreenManager"):
        """Initialize the screen.

        Args:
            screen_manager: The screen manager instance
        """
        self.screen_manager = screen_manager

    @abstractmethod
    def get_name(self) -> str:
        """Get the unique name of this screen.

        Returns:
            Screen name identifier
        """
        pass

    @abstractmethod
    async def render(
        self, chat_id: int, state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """Render the screen content.

        Args:
            chat_id: The chat ID
            state: Screen-specific state data

        Returns:
            Tuple of (message_text, keyboard_markup)
        """
        pass

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        params: str,
    ) -> None:
        """Handle a callback query for this screen.

        Args:
            update: Telegram update
            context: Bot context
            action: The action identifier from callback data
            params: Additional parameters from callback data
        """
        # Default implementation does nothing
        # Subclasses should override to handle specific actions
        pass

    async def on_enter(self, chat_id: int, **kwargs) -> None:
        """Called when entering this screen.

        Subclasses can override to perform initialization.

        Args:
            chat_id: The chat ID
            **kwargs: Additional context data
        """
        pass

    async def on_exit(self, chat_id: int) -> None:
        """Called when leaving this screen.

        Subclasses can override to perform cleanup.

        Args:
            chat_id: The chat ID
        """
        pass

    def get_state(self, chat_id: int) -> Dict[str, Any]:
        """Get the current state for this screen.

        Args:
            chat_id: The chat ID

        Returns:
            Screen state dictionary
        """
        return self.screen_manager.get_screen_state(chat_id)

    def set_state(self, chat_id: int, state: Dict[str, Any]) -> None:
        """Set the state for this screen.

        Args:
            chat_id: The chat ID
            state: Screen state dictionary
        """
        self.screen_manager.set_screen_state(chat_id, state)

    def update_state(self, chat_id: int, **kwargs) -> None:
        """Update specific state values for this screen.

        Args:
            chat_id: The chat ID
            **kwargs: State keys and values to update
        """
        state = self.get_state(chat_id)
        state.update(kwargs)
        self.set_state(chat_id, state)

    async def navigate_to(
        self, chat_id: int, screen_name: str, add_to_history: bool = True, **kwargs
    ) -> None:
        """Navigate to another screen.

        Args:
            chat_id: The chat ID
            screen_name: Target screen name
            add_to_history: Whether to add current screen to navigation history
            **kwargs: Additional context to pass to the target screen
        """
        await self.screen_manager.navigate_to(
            chat_id, screen_name, add_to_history=add_to_history, **kwargs
        )

    async def go_back(self, chat_id: int) -> None:
        """Navigate back to the previous screen.

        Args:
            chat_id: The chat ID
        """
        await self.screen_manager.go_back(chat_id)

    async def refresh(self, chat_id: int) -> None:
        """Refresh the current screen.

        Args:
            chat_id: The chat ID
        """
        await self.screen_manager.update_active_message(chat_id)

