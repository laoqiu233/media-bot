"""HDMI-CEC TV control implementation."""

import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class CECController:
    """Controller for HDMI-CEC TV commands."""

    def __init__(self, cec_device: str = "/dev/cec0", enabled: bool = True):
        """Initialize CEC controller.

        Args:
            cec_device: Path to CEC device
            enabled: Whether CEC is enabled
        """
        self.cec_device = cec_device
        self.enabled = enabled
        self._cec_available: bool | None = None
        self._lock = asyncio.Lock()  # Lock to prevent concurrent cec-ctl usage
        self._persistent_process: Optional[asyncio.subprocess.Process] = None
        self._current_command: Optional[str] = None  # Track current running command

    async def check_availability(self) -> bool:
        """Check if CEC is available on the system.

        Returns:
            True if CEC is available
        """
        if not self.enabled:
            return False

        if self._cec_available is not None:
            return self._cec_available

        try:
            # Try to run cec-ctl
            process = await asyncio.create_subprocess_exec(
                "which",
                "cec-ctl",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode == 0 and stdout:
                self._cec_available = True
                logger.info("CEC client found and available")
                return True
            else:
                self._cec_available = False
                logger.warning("CEC client not found on system")
                return False

        except Exception as e:
            logger.error(f"Error checking CEC availability: {e}")
            self._cec_available = False
            return False

    async def _send_cec_command(self, args: list[str], timeout: float = 2.0) -> tuple[bool, str]:
        """Send a CEC command using cec-ctl with locking.

        Args:
            args: List of cec-ctl arguments (e.g., ["--to", "0", "--standby"])
            timeout: Command timeout in seconds (reduced for faster response)

        Returns:
            Tuple of (success, output)
        """
        if not self.enabled:
            return False, "CEC is disabled"

        if not await self.check_availability():
            return False, "CEC is not available"

        # Use lock to prevent concurrent cec-ctl usage
        async with self._lock:
            self._current_command = " ".join(args)
            try:
                # Build cec-ctl command with device specification
                cmd = ["cec-ctl", "-d", self.cec_device] + args
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    self._current_command = None
                    return False, "Command timeout"

                output = stdout.decode() if stdout else ""
                error = stderr.decode() if stderr else ""

                if process.returncode == 0:
                    logger.debug(f"CEC command '{self._current_command}' executed successfully")
                    self._current_command = None
                    return True, output
                else:
                    logger.error(f"CEC command failed: {error}")
                    self._current_command = None
                    return False, error

            except Exception as e:
                logger.error(f"Error sending CEC command: {e}")
                self._current_command = None
                return False, str(e)
    
    def get_current_command(self) -> Optional[str]:
        """Get the currently running CEC command.
        
        Returns:
            Current command string or None if no command is running
        """
        return self._current_command

    async def tv_on(self) -> bool:
        """Turn the TV on.

        Returns:
            True if successful
        """
        logger.info("Turning TV on via CEC")
        success, output = await self._send_cec_command(["--to", "0", "--image-view-on"])
        return success

    async def tv_off(self) -> bool:
        """Turn the TV off (standby mode).

        Returns:
            True if successful
        """
        logger.info("Turning TV off via CEC")
        success, output = await self._send_cec_command(["--to", "0", "--standby"])
        return success

    async def set_active_source(self) -> bool:
        """Set the Raspberry Pi as the active HDMI source.

        Returns:
            True if successful
        """
        logger.info("Setting Raspberry Pi as active source")
        success, output = await self._send_cec_command(["--to", "0", "--active-source"])
        return success

    async def get_power_status(self) -> str | None:
        """Get the power status of the TV.

        Returns:
            Power status string or None
        """
        success, output = await self._send_cec_command(["--to", "0", "--get-power-status"])
        if not success:
            return None

        # Parse output for power status
        # cec-ctl response format: "power status: on" or "power status: standby"
        match = re.search(r"power status:\s*(\w+)", output, re.IGNORECASE)
        if match:
            status = match.group(1).lower()
            logger.info(f"TV power status: {status}")
            return status

        return None

    async def is_tv_on(self) -> bool:
        """Check if TV is currently on.

        Returns:
            True if TV is on
        """
        status = await self.get_power_status()
        return status == "on" if status else False

    async def set_volume(self, level: int) -> bool:
        """Set TV volume level.

        Args:
            level: Volume level (0-100)

        Returns:
            True if successful
        """
        # CEC volume control is limited and not well standardized
        # This is a basic implementation
        logger.info(f"Setting TV volume to {level}")
        # Convert 0-100 to CEC volume (0x00 to 0x7F)
        cec_volume = int((level / 100) * 0x7F)
        success, _ = await self._send_cec_command(["--to", "0", "--set-volume", str(cec_volume)])
        return success

    async def volume_up(self) -> bool:
        """Increase TV volume.

        Returns:
            True if successful
        """
        logger.info("Increasing TV volume")
        success, _ = await self._send_cec_command(["--to", "0", "--volume-up"])
        return success

    async def volume_down(self) -> bool:
        """Decrease TV volume.

        Returns:
            True if successful
        """
        logger.info("Decreasing TV volume")
        success, _ = await self._send_cec_command(["--to", "0", "--volume-down"])
        return success

    async def mute(self) -> bool:
        """Mute the TV.

        Returns:
            True if successful
        """
        logger.info("Muting TV")
        success, _ = await self._send_cec_command(["--to", "0", "--mute"])
        return success

    async def get_osd_name(self) -> str | None:
        """Get the OSD name of the TV.

        Returns:
            TV name or None
        """
        success, output = await self._send_cec_command(["--to", "0", "--get-osd-name"])
        if not success:
            return None

        # Parse output for OSD name
        match = re.search(r"osd name:\s*(.+)", output, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            logger.info(f"TV OSD name: {name}")
            return name

        return None

    async def scan_devices(self) -> list[dict]:
        """Scan for CEC devices on the bus.

        Returns:
            List of device information
        """
        success, output = await self._send_cec_command(["--scan"])
        if not success:
            return []

        devices = []
        # Parse scan output
        # Format: "device #0: TV" or similar
        for match in re.finditer(r"device\s+#?(\d+):\s*(.+)", output, re.IGNORECASE | re.MULTILINE):
            device_num = int(match.group(1))
            device_name = match.group(2).strip()
            devices.append({"address": device_num, "name": device_name})

        logger.info(f"Found {len(devices)} CEC devices")
        return devices

    async def send_key(self, key_code: str) -> bool:
        """Send a remote control key press.

        Args:
            key_code: CEC key code (e.g., 'select', 'up', 'down', 'left', 'right')

        Returns:
            True if successful
        """
        logger.info(f"Sending key: {key_code}")
        success, _ = await self._send_cec_command(["--to", "0", "--key", key_code])
        return success

    async def get_status(self) -> dict:
        """Get overall CEC status.

        Returns:
            Status dictionary
        """
        available = await self.check_availability()
        if not available:
            return {
                "available": False,
                "enabled": self.enabled,
                "error": "CEC not available",
                "current_command": self.get_current_command(),
            }

        power_status = await self.get_power_status()
        osd_name = await self.get_osd_name()

        return {
            "available": True,
            "enabled": self.enabled,
            "device": self.cec_device,
            "power_status": power_status,
            "tv_name": osd_name,
            "current_command": self.get_current_command(),
        }


# Global CEC controller instance
cec_controller: CECController | None = None


def get_cec_controller(cec_device: str = "/dev/cec0", enabled: bool = True) -> CECController:
    """Get or create the global CEC controller instance.

    Args:
        cec_device: Path to CEC device
        enabled: Whether CEC is enabled

    Returns:
        CECController instance
    """
    global cec_controller
    if cec_controller is None:
        cec_controller = CECController(cec_device=cec_device, enabled=enabled)
    return cec_controller
