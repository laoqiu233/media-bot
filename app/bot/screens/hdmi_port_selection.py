"""HDMI port selection screen using modetest."""

import asyncio
import logging
import re
import subprocess

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callback_data import HDMI_PORT_BACK, HDMI_PORT_SELECT
from app.bot.screens.base import (
    Context,
    Navigation,
    RenderOptions,
    Screen,
    ScreenHandlerResult,
    ScreenRenderResult,
)

logger = logging.getLogger(__name__)


class HDMIConnector:
    """Represents an HDMI connector detected by modetest."""

    def __init__(self, connector_id: int, name: str, connected: bool, modes: list[str] | None = None):
        """Initialize HDMI connector.

        Args:
            connector_id: Connector ID from modetest
            name: Connector name (e.g., "HDMI-A-1", "HDMI-A-2")
            connected: Whether a display is connected
            modes: List of available modes (optional)
        """
        self.connector_id = connector_id
        self.name = name
        self.connected = connected
        self.modes = modes or []


async def _detect_hdmi_connectors() -> list[HDMIConnector]:
    """Detect HDMI connectors using modetest with vc4 driver.

    Returns:
        List of HDMI connectors found
    """
    connectors = []
    try:
        loop = asyncio.get_event_loop()
        # Run modetest -M vc4 -c to get connector information for Raspberry Pi
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["modetest", "-M", "vc4", "-c"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )

        if result.returncode != 0:
            logger.warning(f"modetest failed: {result.stderr}")
            # Try without -M vc4 as fallback
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["modetest", "-c"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )
            if result.returncode != 0:
                return connectors

        # Parse modetest output
        # Format is typically:
        # id      encoder status          name            size (mm)       modes   encoders
        # 28      0       connected       HDMI-A-1        0x0             1       27
        # 29      0       disconnected    HDMI-A-2        0x0             0       27

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("id") or line.startswith("--"):
                continue

            # Parse connector line
            # Split by whitespace, but be careful with multiple spaces
            parts = re.split(r"\s+", line)
            if len(parts) >= 4:
                try:
                    connector_id = int(parts[0])
                    encoder_id = parts[1] if len(parts) > 1 else "0"
                    status = parts[2] if len(parts) > 2 else "unknown"
                    name = parts[3] if len(parts) > 3 else ""

                    # Only process HDMI connectors
                    if "HDMI" in name.upper() or "hdmi" in name.lower():
                        connected = status.lower() == "connected"
                        connectors.append(HDMIConnector(connector_id, name, connected))
                except (ValueError, IndexError) as e:
                    logger.debug(f"Error parsing modetest line '{line}': {e}")
                    continue

    except FileNotFoundError:
        logger.warning("modetest utility not found. Install with: sudo apt install libdrm-tests")
    except subprocess.TimeoutExpired:
        logger.error("modetest command timed out")
    except Exception as e:
        logger.error(f"Error detecting HDMI connectors: {e}")

    return connectors


async def _get_current_active_connector() -> HDMIConnector | None:
    """Get currently active HDMI connector.

    Returns:
        Active connector or None if unable to determine
    """
    try:
        loop = asyncio.get_event_loop()
        # Get connectors and find which one is connected and likely active
        connectors = await _detect_hdmi_connectors()

        # Return the first connected connector (usually the active one)
        for connector in connectors:
            if connector.connected:
                return connector

        # If none are connected, return the first one
        if connectors:
            return connectors[0]

        return None

    except Exception as e:
        logger.error(f"Error getting current active connector: {e}")
        return None


async def _get_connector_modes(connector_id: int) -> list[str]:
    """Get available modes for a connector.

    Args:
        connector_id: Connector ID

    Returns:
        List of mode strings (e.g., ["1920x1080@60", "1280x720@60"])
    """
    modes = []
    try:
        loop = asyncio.get_event_loop()
        # Get detailed connector info including modes
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["modetest", "-M", "vc4", "-c", str(connector_id)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )
        
        # Fallback if vc4 fails
        if result.returncode != 0:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["modetest", "-c", str(connector_id)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )

        if result.returncode == 0:
            # Parse modes from output
            # Look for lines with resolution info like "1920x1080" or mode indices
            for line in result.stdout.splitlines():
                # Look for resolution patterns
                mode_match = re.search(r"(\d+)x(\d+)(?:@(\d+))?", line)
                if mode_match:
                    width, height, refresh = mode_match.groups()
                    refresh_str = f"@{refresh}" if refresh else ""
                    modes.append(f"{width}x{height}{refresh_str}")

    except Exception as e:
        logger.debug(f"Error getting connector modes: {e}")

    return modes


async def _set_hdmi_port(connector_id: int, connector_name: str) -> tuple[bool, str]:
    """Set HDMI port using modetest.

    Args:
        connector_id: Connector ID to activate
        connector_name: Connector name for display

    Returns:
        Tuple of (success, message)
    """
    try:
        loop = asyncio.get_event_loop()

        # Verify connector exists
        connectors = await _detect_hdmi_connectors()
        connector = None
        for conn in connectors:
            if conn.connector_id == connector_id:
                connector = conn
                break

        if not connector:
            return False, f"Connector {connector_name} (ID: {connector_id}) not found"

        if not connector.connected:
            return False, f"Connector {connector_name} is not connected. Please connect a display first."

        # Get available CRTCs (display controllers)
        crtc_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["modetest", "-M", "vc4", "-p"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )
        
        # Fallback if vc4 fails
        if crtc_result.returncode != 0:
            crtc_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["modetest", "-p"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )

        crtc_id = None
        if crtc_result.returncode == 0:
            # Find first available CRTC
            for line in crtc_result.stdout.splitlines():
                if "id" in line.lower() and ("crtc" in line.lower() or "plane" in line.lower()):
                    continue
                parts = re.split(r"\s+", line.strip())
                if len(parts) > 0:
                    try:
                        potential_crtc = int(parts[0])
                        # Use first valid CRTC (usually 0 or 1)
                        if potential_crtc >= 0:
                            crtc_id = potential_crtc
                            break
                    except (ValueError, IndexError):
                        continue

        if crtc_id is None:
            # Default to CRTC 0
            crtc_id = 0

        # Get available modes for the connector
        modes = await _get_connector_modes(connector_id)
        if not modes:
            # Use default mode if none found
            mode = "1920x1080@60"
        else:
            # Use the first (usually preferred) mode
            mode = modes[0]

        # Try to set the connector using modetest -s
        # Format: modetest -s <connector-id>[@<crtc-id>]:<mode>
        # If mode doesn't include @refresh, modetest will use default refresh rate
        set_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["modetest", "-M", "vc4", "-s", f"{connector_id}@{crtc_id}:{mode}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )

        if set_result.returncode == 0:
            return True, f"Successfully switched to {connector_name} (mode: {mode})"
        else:
            # Try without specifying CRTC (let modetest choose)
            set_result2 = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["modetest", "-M", "vc4", "-s", f"{connector_id}:{mode}"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ),
            )
            
            # Fallback without -M vc4
            if set_result2.returncode != 0:
                set_result2 = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["modetest", "-s", f"{connector_id}:{mode}"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    ),
                )

            if set_result2.returncode == 0:
                return True, f"Successfully switched to {connector_name} (mode: {mode})"
            else:
                error_msg = set_result2.stderr or set_result2.stdout or set_result.stderr or "Unknown error"
                return False, f"Failed to switch HDMI port: {error_msg.strip()}"

    except Exception as e:
        logger.error(f"Error setting HDMI port: {e}", exc_info=True)
        return False, f"Error: {str(e)}"


class HDMIPortSelectionScreen(Screen):
    """Screen for selecting HDMI port using modetest."""

    def get_name(self) -> str:
        """Get screen name."""
        return "hdmi_port_selection"

    async def render(self, context: Context) -> ScreenRenderResult:
        """Render the HDMI port selection screen.

        Args:
            context: The context object

        Returns:
            Tuple of (text, keyboard, options)
        """
        # Detect available HDMI connectors
        connectors = await _detect_hdmi_connectors()
        current_connector = await _get_current_active_connector()

        text = "📺 *HDMI Port Selection*\n\n"

        if not connectors:
            text += "❌ No HDMI connectors detected.\n\n"
            text += "Make sure:\n"
            text += "• `modetest` utility is installed (`sudo apt install libdrm-tests`)\n"
            text += "• DRM/KMS is enabled in `/boot/config.txt`\n"
            text += "• System is using KMS driver (vc4-kms-v3d)\n"
            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=HDMI_PORT_BACK)]]
            return text, InlineKeyboardMarkup(keyboard), RenderOptions()

        if current_connector:
            text += f"Current: *{current_connector.name}*"
            if current_connector.connected:
                text += " ✅ Connected\n\n"
            else:
                text += " ⚠️ Disconnected\n\n"
        else:
            text += "Current: Unknown\n\n"

        # Separate connected and disconnected connectors
        connected_connectors = [c for c in connectors if c.connected]
        disconnected_connectors = [c for c in connectors if not c.connected]

        if connected_connectors:
            text += "✅ *Available HDMI ports (Connected):*\n"
        else:
            text += "⚠️ *No connected HDMI ports found*\n"

        keyboard = []
        for connector in connected_connectors:
            button_text = connector.name
            if current_connector and connector.connector_id == current_connector.connector_id:
                button_text = f"✓ {connector.name}"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        button_text, callback_data=f"{HDMI_PORT_SELECT}{connector.connector_id}"
                    )
                ]
            )

        # Show disconnected ports in text but not as buttons
        if disconnected_connectors:
            text += "\n⚪ *Disconnected HDMI ports:*\n"
            for connector in disconnected_connectors:
                text += f"• {connector.name} (ID: {connector.connector_id})\n"
            text += "\n_Connect a display to enable these ports_\n"

        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=HDMI_PORT_BACK)])

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
        if query.data == HDMI_PORT_BACK:
            return Navigation(next_screen="system_control")

        elif query.data.startswith(HDMI_PORT_SELECT):
            connector_id_str = query.data[len(HDMI_PORT_SELECT) :]
            try:
                connector_id = int(connector_id_str)

                # Get connector name for display
                connectors = await _detect_hdmi_connectors()
                connector_name = f"HDMI-{connector_id}"
                for conn in connectors:
                    if conn.connector_id == connector_id:
                        connector_name = conn.name
                        break

                success, message = await _set_hdmi_port(connector_id, connector_name)

                if success:
                    await query.answer(f"Switched to {connector_name}")
                else:
                    await query.answer(message, show_alert=True)

                # Return to system control after showing message
                return Navigation(next_screen="system_control")

            except ValueError:
                await query.answer("Invalid connector ID", show_alert=True)
                return None

        return None
