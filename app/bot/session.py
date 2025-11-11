import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from telegram import CallbackQuery, Message
from telegram.ext import ExtBot

from app.bot.screen_registry import ScreenRegistry
from app.bot.screens.base import (
    Context,
    Navigation,
    Screen,
    ScreenHandlerResult,
)

logger = logging.getLogger(__name__)


class Session:
    def __init__(
        self, chat_id: int, init_screen: Screen, bot: ExtBot, screen_registry: ScreenRegistry
    ):
        self.chat_id = chat_id
        self.screen = init_screen
        self.context = Context()
        self.bot = bot
        self.screen_registry = screen_registry
        self.message_id: int | None = None

        # Auto-refresh state
        self.last_activity = datetime.now()
        self.refresh_task: asyncio.Task | None = None
        self.is_refreshing = False

        # Cache last rendered content to avoid unnecessary updates
        self.last_rendered_text: str | None = None
        self.last_rendered_keyboard = None
        self.last_poster_url: str | None = None
        self.is_photo_message = False

        # Lock to prevent concurrent render operations
        self._render_lock = asyncio.Lock()

        self._start_auto_refresh()

    async def render_screen(self, force: bool = False) -> None:
        async with self._render_lock:
            (render_result_text, render_result_keyboard, render_options) = await self.screen.render(
                self.context
            )

            # Get rendering options from screen
            photo_url = render_options.photo_url
            force_new_message = render_options.force_new_message
            has_photo = photo_url is not None

            # Determine if we need to send a new message
            needs_new_message = force_new_message or (
                self.message_id is not None
                and (
                    (has_photo != self.is_photo_message)
                    or (has_photo and photo_url != self.last_poster_url)
                )
            )

            # Skip update if content hasn't changed (unless forced or needs new message)
            if (
                not force
                and not needs_new_message
                and self.message_id is not None
                and render_result_text == self.last_rendered_text
                and render_result_keyboard == self.last_rendered_keyboard
            ):
                return

            # Delete old message if we need to send a new one
            if needs_new_message and self.message_id is not None:
                try:
                    await self.bot.delete_message(self.chat_id, self.message_id)
                except Exception as e:
                    logger.debug(f"Could not delete old message: {e}")
                self.message_id = None

            if self.message_id is None:
                # Send new message
                if has_photo and photo_url:
                    try:
                        message = await self.bot.send_photo(
                            self.chat_id,
                            photo=photo_url,
                            caption=render_result_text,
                            reply_markup=render_result_keyboard,
                            parse_mode="Markdown",
                        )
                        self.is_photo_message = True
                    except Exception as e:
                        logger.error(f"Failed to send photo: {e}")
                        logger.info("Falling back to text message (poster will be skipped)")
                        message = await self.bot.send_message(
                            self.chat_id,
                            render_result_text,
                            reply_markup=render_result_keyboard,
                            parse_mode="Markdown",
                        )
                        self.is_photo_message = False
                        # Clear the cached poster URL to prevent retry loops
                        self.last_poster_url = None
                else:
                    message = await self.bot.send_message(
                        self.chat_id,
                        render_result_text,
                        reply_markup=render_result_keyboard,
                        parse_mode="Markdown",
                    )
                    self.is_photo_message = False
                self.message_id = message.message_id
            else:
                # Edit existing message
                try:
                    if self.is_photo_message:
                        await self.bot.edit_message_caption(
                            chat_id=self.chat_id,
                            message_id=self.message_id,
                            caption=render_result_text,
                            reply_markup=render_result_keyboard,
                            parse_mode="Markdown",
                        )
                    else:
                        await self.bot.edit_message_text(
                            text=render_result_text,
                            chat_id=self.chat_id,
                            message_id=self.message_id,
                            reply_markup=render_result_keyboard,
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    logger.debug(f"Could not edit message: {e}")

            # Cache the rendered content
            self.last_rendered_text = render_result_text
            self.last_rendered_keyboard = render_result_keyboard
            self.last_poster_url = photo_url

    async def handle_result(self, result: ScreenHandlerResult) -> None:
        if isinstance(result, Navigation):
            new_screen = self.screen_registry.get_screen_or_throw(result.next_screen)
            self.context.clear_context()
            await self.screen.on_exit(self.context)
            await new_screen.on_enter(self.context, **result.kwargs)
            self.screen = new_screen
        await self.render_screen()

    async def handle_callback(self, query: CallbackQuery) -> None:
        self._reset_activity()
        result = await self.screen.handle_callback(query, self.context)
        await self.handle_result(result)

    async def handle_message(self, message: Message) -> None:
        self._reset_activity()
        result = await self.screen.handle_message(message, self.context)
        await self.handle_result(result)
        await message.delete()

    def _reset_activity(self) -> None:
        """Reset the last activity timestamp and restart auto-refresh if stopped."""
        self.last_activity = datetime.now()
        if not self.is_refreshing:
            self._start_auto_refresh()

    def _start_auto_refresh(self) -> None:
        """Start the auto-refresh background task."""
        if self.refresh_task is not None:
            self.refresh_task.cancel()
        self.is_refreshing = True
        self.refresh_task = asyncio.create_task(self._auto_refresh_loop())

    async def _auto_refresh_loop(self) -> None:
        """Background task that refreshes the screen every 0.5 seconds."""
        try:
            while True:
                await asyncio.sleep(0.5)

                # Check if 5 minutes have passed since last activity
                time_since_activity = datetime.now() - self.last_activity
                if time_since_activity > timedelta(minutes=5):
                    logger.info(
                        f"Session {self.chat_id}: Stopping auto-refresh after 5 minutes of inactivity"
                    )
                    self.is_refreshing = False
                    break

                # Refresh the screen
                try:
                    await self.render_screen()
                except Exception as e:
                    logger.error(f"Error refreshing screen for session {self.chat_id}: {e}")
        except asyncio.CancelledError:
            logger.debug(f"Session {self.chat_id}: Auto-refresh task cancelled")
            raise

    async def cleanup(self) -> None:
        """Clean up the session and stop background tasks."""
        if self.refresh_task is not None:
            self.refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.refresh_task
