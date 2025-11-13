"""Audio track selection screen."""

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import AUDIO_TRACK_BACK, AUDIO_TRACK_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class AudioTrackSelectionScreen(Screen):
    """Screen for selecting audio tracks."""

    def __init__(self, player):
        """Initialize audio track selection screen.

        Args:
            player: MPV player controller
        """
        self.player = player

    def get_name(self) -> str:
        """Get screen name."""
        return "audio_track_selection"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the audio track selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        try:
            # Check if media is playing
            status = await self.player.get_status()
            if not status.get("current_file"):
                text = "🎵 *Audio Track Selection*\n\n"
                text += "⚠️ No media is currently playing.\n\n"
                text += "Please start playing a media file first."

                keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=AUDIO_TRACK_BACK)]]
                return text, InlineKeyboardMarkup(keyboard), RenderOptions()

            # Get available audio tracks
            audio_tracks = await self.player.get_audio_tracks()
            current_track_id = await self.player.get_current_audio_track()

            text = "🎵 *Audio Track Selection*\n\n"

            if not audio_tracks:
                text += "⚠️ No audio tracks found in the current media.\n\n"
                text += "This media file may not have multiple audio tracks."

                keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=AUDIO_TRACK_BACK)]]
                return text, InlineKeyboardMarkup(keyboard), RenderOptions()

            # Show current track
            if current_track_id is not None:
                current_track = next((t for t in audio_tracks if t["id"] == current_track_id), None)
                if current_track:
                    track_label = self._format_track_label(current_track)
                    text += f"Current: *{track_label}*\n\n"
                else:
                    text += f"Current: Track ID {current_track_id}\n\n"
            else:
                text += "Current: Unknown\n\n"

            text += "Select audio track:\n\n"

            keyboard = []
            for track in audio_tracks:
                track_id = track["id"]
                track_label = self._format_track_label(track)
                
                # Mark current track
                if current_track_id == track_id:
                    button_text = f"✅ {track_label}"
                else:
                    button_text = track_label

                keyboard.append([
                    InlineKeyboardButton(
                        button_text,
                        callback_data=f"{AUDIO_TRACK_SELECT}{track_id}",
                    )
                ])

            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back to Player", callback_data=AUDIO_TRACK_BACK)])

            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        except Exception as e:
            logger.error(f"Error rendering audio track selection screen: {e}", exc_info=True)
            text = "🎵 *Audio Track Selection*\n\n"
            text += "❌ Error loading audio tracks."

            keyboard = [[InlineKeyboardButton("⬅️ Back to Player", callback_data=AUDIO_TRACK_BACK)]]
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
            if query.data == AUDIO_TRACK_BACK:
                # Return to player screen
                return Navigation(next_screen="player")

            elif query.data.startswith(AUDIO_TRACK_SELECT):
                # Extract track ID
                track_id_str = query.data[len(AUDIO_TRACK_SELECT) :]
                try:
                    track_id = int(track_id_str)
                except ValueError:
                    await query.answer("Invalid track ID", show_alert=True)
                    return None

                # Set audio track
                success = await self.player.set_audio_track(track_id)
                if success:
                    # Get track info for feedback
                    audio_tracks = await self.player.get_audio_tracks()
                    selected_track = next((t for t in audio_tracks if t["id"] == track_id), None)
                    if selected_track:
                        track_label = self._format_track_label(selected_track)
                        await query.answer(f"✅ Switched to {track_label}")
                    else:
                        await query.answer(f"✅ Switched to track {track_id}")

                    # Return to player screen
                    return Navigation(next_screen="player")
                else:
                    await query.answer("❌ Failed to switch audio track", show_alert=True)
                    return None

            return None

        except Exception as e:
            logger.error(f"Error handling audio track selection callback: {e}", exc_info=True)
            await query.answer("Error", show_alert=True)
            return None

