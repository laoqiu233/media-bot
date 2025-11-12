"""HDMI-CEC TV control implementation."""

import asyncio
import logging
import re
import time
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
        self._status_cache: Optional[dict] = None  # Cached status
        self._status_cache_time: float = 0.0  # Timestamp of cached status
        self._status_cache_ttl: float = 60.0  # Cache TTL in seconds (60 seconds)

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
        # Try to get physical address from adapter info
        # First try to get it from the adapter itself
        try:
            # Use --playback -S to get adapter info which includes physical address
            success, output = await self._send_cec_command(["--playback", "-S"])
            if success:
                # Look for physical address in output (format: "Physical address: 1.0.0.0")
                phys_match = re.search(r"physical address:\s*([0-9a-f.]+)", output, re.IGNORECASE)
                if phys_match:
                    phys_addr = phys_match.group(1).strip()
                    logger.info(f"Using physical address: {phys_addr}")
                    success, _ = await self._send_cec_command(["--to", "0", "--active-source", f"phys-addr={phys_addr}"])
                    return success
        except Exception as e:
            logger.debug(f"Could not get physical address: {e}")
        
        # Fallback to common default physical address
        logger.info("Using default physical address: 1.0.0.0")
        success, output = await self._send_cec_command(["--to", "0", "--active-source", "phys-addr=1.0.0.0"])
        return success

    async def get_power_status(self) -> str | None:
        """Get the power status of the TV.

        Returns:
            Power status string ("on" or "standby") or None if unable to determine
        """
        if not self.enabled:
            return None

        if not await self.check_availability():
            return None

        try:
            # Use lock to prevent concurrent cec-ctl usage
            async with self._lock:
                self._current_command = "get_power_status"
                # Build cec-ctl command with device specification
                cmd = ["cec-ctl", "-d", self.cec_device, "--to", "0", "--give-device-power-status"]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    self._current_command = None
                    logger.debug("Power status query timeout")
                    return None

                # Combine stdout and stderr (cec-ctl may output to either)
                output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")
                self._current_command = None

                # Check if output contains "pwr-state: on"
                if "pwr-state: on" in output.lower():
                    logger.debug("TV power status: on")
                    return "on"
                elif output.strip():  # If we got any response, assume standby
                    logger.debug("TV power status: standby")
                    return "standby"
                else:
                    logger.debug("No response from power status query")
                    return None

        except Exception as e:
            logger.error(f"Error getting power status: {e}")
            self._current_command = None
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
        """Increase TV volume by 5 steps.

        Returns:
            True if successful
        """
        logger.info("Increasing TV volume by 5")
        # Send volume up command 5 times
        success = True
        for _ in range(5):
            result, _ = await self._send_cec_command(["--to", "0", "--user-control-pressed", "ui-cmd=volume-up"])
            if not result:
                success = False
            # Small delay between commands to avoid overwhelming the TV
            await asyncio.sleep(0.1)
        return success

    async def volume_down(self) -> bool:
        """Decrease TV volume by 5 steps.

        Returns:
            True if successful
        """
        logger.info("Decreasing TV volume by 5")
        # Send volume down command 5 times
        success = True
        for _ in range(5):
            result, _ = await self._send_cec_command(["--to", "0", "--user-control-pressed", "ui-cmd=volume-down"])
            if not result:
                success = False
            # Small delay between commands to avoid overwhelming the TV
            await asyncio.sleep(0.1)
        return success

    async def mute(self) -> bool:
        """Mute the TV.

        Returns:
            True if successful
        """
        logger.info("Muting TV")
        success, _ = await self._send_cec_command(["--to", "0", "--user-control-pressed", "ui-cmd=mute"])
        return success

    async def get_osd_name(self) -> str | None:
        """Get the OSD name of the TV.

        Returns:
            TV name or None
        """
        # cec-ctl doesn't have --get-osd-name, use --playback -S to scan
        # This will show device info including OSD names
        success, output = await self._send_cec_command(["--playback", "-S"])
        if not success:
            return None

        # Parse output for OSD name
        # Look for device 0 (TV) and its OSD name
        # Format might be: "device #0: TV" or "OSD name: ..."
        match = re.search(r"osd name:\s*(.+)", output, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            logger.info(f"TV OSD name: {name}")
            return name
        
        # Try alternative format
        match = re.search(r"device\s+#?0:\s*(.+)", output, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            logger.info(f"TV device name: {name}")
            return name

        return None

    async def scan_devices(self) -> list[dict]:
        """Scan for CEC devices on the bus.

        Returns:
            List of device information
        """
        success, output = await self._send_cec_command(["--playback", "-S"])
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
        
        Uses caching to avoid frequent cec-ctl calls. Cache expires after 60 seconds.

        Returns:
            Status dictionary
        """
        current_time = time.time()
        
        # Return cached status if it's still valid
        if (
            self._status_cache is not None
            and (current_time - self._status_cache_time) < self._status_cache_ttl
        ):
            # Update current_command in cached result (this changes frequently)
            if self._status_cache:
                self._status_cache["current_command"] = self.get_current_command()
            return self._status_cache
        
        # Cache expired or doesn't exist, fetch fresh status
        available = await self.check_availability()
        if not available:
            status = {
                "available": False,
                "enabled": self.enabled,
                "error": "CEC not available",
                "current_command": self.get_current_command(),
            }
            # Cache the result
            self._status_cache = status
            self._status_cache_time = current_time
            return status

        power_status = await self.get_power_status()
        osd_name = await self.get_osd_name()

        status = {
            "available": True,
            "enabled": self.enabled,
            "device": self.cec_device,
            "power_status": power_status,
            "tv_name": osd_name,
            "current_command": self.get_current_command(),
        }
        
        # Cache the result
        self._status_cache = status
        self._status_cache_time = current_time
        
        return status


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
