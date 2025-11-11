"""Base screen class for the bot UI system."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telegram import CallbackQuery, InlineKeyboardMarkup, Update

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Context:
    def __init__(self, init_context: dict[str, Any] | None = None):
        self.context = init_context if init_context is not None else {}

    def get_context(self) -> dict[str, Any]:
        return self.context

    def clear_context(self) -> None:
        self.context = {}

    def update_context(self, **kwargs: Any) -> None:
        self.context.update(kwargs)


class Navigation:
    def __init__(self, next_screen: str, **kwargs: dict[str, Any]):
        self.next_screen = next_screen
        self.kwargs = kwargs


@dataclass
class RenderOptions:
    """Options for controlling how a screen should be rendered."""

    photo_url: str | None = None
    """Optional photo URL to display with the message."""

    force_new_message: bool = False
    """If True, forces sending a new message instead of editing the current one."""


ScreenHandlerResult = Navigation | None
ScreenRenderResult = tuple[str, InlineKeyboardMarkup, RenderOptions]


class Screen(ABC):
    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    async def render(self, context: Context) -> ScreenRenderResult:
        pass

    async def handle_callback(self, query: CallbackQuery, context: Context) -> ScreenHandlerResult:
        """Handle callback queries. Override in subclass if needed."""
        return None

    async def handle_message(
        self,
        update: Update,
        context: Context,
    ) -> ScreenHandlerResult:
        """Handle text messages. Override in subclass if needed."""
        return None

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering this screen. Override in subclass if needed."""
        return None

    async def on_exit(self, context: Context) -> None:
        """Called when exiting this screen. Override in subclass if needed."""
        return None
