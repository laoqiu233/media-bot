"""Subtitle selection screen."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import SUBTITLE_BACK, SUBTITLE_REMOVE, SUBTITLE_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class SubtitleSelectionScreen(Screen):
    """Screen for selecting subtitle tracks."""

    def __init__(self, player):
        """Initialize subtitle selection screen.

        Args:
            player: MPV player controller
        """
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "subtitle_selection"

    async def on_enter(self, context: Context, **kwargs) -> None:
        """Called when entering the screen."""
        # Store the library state if provided (so we can pass it back to player)
        library_state = kwargs.get("library_state")
        if library_state:
            context.update_context(saved_library_state=library_state)

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the subtitle selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        try:
            # Check if media is playing
            status = await self.player.get_status()
            if not status.get("current_file"):
                text = "📝 *Subtitle Selection*\n\n"
                text += "⚠️ No media is currently playing.\n\n"
                text += "Please start playing a media file first."

                keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=SUBTITLE_BACK)]]
                return text, InlineKeyboardMarkup(keyboard), RenderOptions()

            # Get available subtitle tracks
            subtitle_tracks = await self.player.get_subtitle_tracks()
            current_track_id = await self.player.get_current_subtitle_track()

            text = "📝 *Subtitle Selection*\n\n"

            if not subtitle_tracks:
                text += "⚠️ No subtitle tracks found in the current media.\n\n"
                text += "This media file may not have embedded subtitles."

                keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=SUBTITLE_BACK)]]
                return text, InlineKeyboardMarkup(keyboard), RenderOptions()

            # Show current subtitle status
            if current_track_id is not None:
                current_track = next(
                    (t for t in subtitle_tracks if t["id"] == current_track_id), None
                )
                if current_track:
                    track_label = self._format_track_label(current_track)
                    text += f"Current: *{track_label}*\n\n"
                else:
                    text += f"Current: Track ID {current_track_id}\n\n"
            else:
                text += "Current: *No subtitles*\n\n"

            text += "Select subtitle track:\n\n"

            keyboard = []
            for track in subtitle_tracks:
                track_id = track["id"]
                track_label = self._format_track_label(track)

                # Mark current track
                if current_track_id == track_id:
                    button_text = f"✅ {track_label}"
                else:
                    button_text = track_label

                keyboard.append(
                    [
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"{SUBTITLE_SELECT}{track_id}",
                        )
                    ]
                )

            # Add remove subtitles button
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🚫 Remove Subtitles"
                        if current_track_id is not None
                        else "🚫 No Subtitles",
                        callback_data=SUBTITLE_REMOVE,
                    )
                ]
            )

            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back to Player", callback_data=SUBTITLE_BACK)])

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering subtitle selection screen: {e}", exc_info=True)
            text = "📝 *Subtitle Selection*\n\n"
            text += "❌ Error loading subtitle tracks."

            keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=SUBTITLE_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

    def _format_track_label(self, track: dict) -> str:
        """Format track label for display.

        Args:
            track: Track dictionary with id, title, lang, codec

        Returns:
            Formatted track label
        """
        parts = []

        # Add track number
        parts.append(f"Track {track['id']}")

        # Add language if available
        if track.get("lang"):
            parts.append(f"[{track['lang']}]")

        # Add title if available
        if track.get("title"):
            parts.append(f"- {track['title']}")

        # Add codec if available
        if track.get("codec"):
            parts.append(f"({track['codec']})")

        return " ".join(parts)

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
        try:
            if query.data == SUBTITLE_BACK:
                # Return to player screen, passing library state back
                saved_library_state = context.get_context().get("saved_library_state")
                if saved_library_state:
                    return Navigation(next_screen="player", library_state=saved_library_state)
                return Navigation(next_screen="player")

            elif query.data == SUBTITLE_REMOVE:
                # Remove subtitles
                success = await self.player.set_subtitle_track(None)
                if success:
                    await query.answer("✅ Subtitles removed")
                    # Return to player screen
                    return Navigation(next_screen="player")
                else:
                    await query.answer("❌ Failed to remove subtitles", show_alert=True)
                    return None

            elif query.data.startswith(SUBTITLE_SELECT):
                # Extract track ID
                track_id_str = query.data[len(SUBTITLE_SELECT) :]
                try:
                    track_id = int(track_id_str)
                except ValueError:
                    await query.answer("Invalid track ID", show_alert=True)
                    return None

                # Set subtitle track
                success = await self.player.set_subtitle_track(track_id)
                if success:
                    # Get track info for feedback
                    subtitle_tracks = await self.player.get_subtitle_tracks()
                    selected_track = next((t for t in subtitle_tracks if t["id"] == track_id), None)
                    if selected_track:
                        track_label = self._format_track_label(selected_track)
                        await query.answer(f"✅ Switched to {track_label}")
                    else:
                        await query.answer(f"✅ Switched to track {track_id}")

                    # Return to player screen
                    return Navigation(next_screen="player")
                else:
                    await query.answer("❌ Failed to switch subtitle track", show_alert=True)
                    return None

            return None

        except Exception as e:
            logger.error(f"Error handling subtitle selection callback: {e}", exc_info=True)
            await query.answer("Error", show_alert=True)
            return None
