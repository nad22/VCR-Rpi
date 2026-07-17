import socket
import subprocess
import os
import errno
import re
import time
import xbmc


class BluetoothRemoteReader:
    """Read button events and encoder ticks from ESP32 Bluetooth remote."""
    
    def __init__(self, device_name="VCR_REMOTE", device_addr=None, rfcomm_channels=None):
        self.device_name = device_name
        self.device_addr = device_addr
        if rfcomm_channels is None:
            self.rfcomm_channels = [1]
        elif isinstance(rfcomm_channels, int):
            self.rfcomm_channels = [rfcomm_channels]
        else:
            self.rfcomm_channels = [int(ch) for ch in rfcomm_channels]
        self.socket = None
        self.rfcomm_file = None
        self.rfcomm_idx = 0
        self.rfcomm_path = "/dev/rfcomm0"
        self.initialized = False
        self.connected_channel = None
        self._rx_buffer = ""
        self._last_rx_log_at = 0.0
        self._last_link_check_at = 0.0
        self._link_check_interval_sec = 2.0
        self._event_pattern = re.compile(
            r"(PLAY_PAUSE|GO_START|STOP|NEXT|PREV|FF|RW|SEEK:[+-]?\d+(?:\.\d+)?)",
            re.IGNORECASE,
        )
        self._discover_device()

    def _is_link_connected(self):
        """Return True when BlueZ reports an active ACL link to the remote."""
        if not self.device_addr:
            return False

        now = time.time()
        if (now - self._last_link_check_at) < self._link_check_interval_sec:
            return True

        self._last_link_check_at = now
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", self.device_addr],
                capture_output=True,
                text=True,
                timeout=3,
            )
            out = (result.stdout or "") + "\n" + (result.stderr or "")
            return "Connected: yes" in out
        except Exception as exc:
            xbmc.log(f"[BT_REMOTE] Link check failed: {exc}", xbmc.LOGINFO)
            # Do not tear down a working stream because of a transient tool issue.
            return True

    def _connect_via_rfcomm_tty(self):
        """Fallback for systems where Python lacks AF_BLUETOOTH (e.g. some LibreELEC builds)."""
        last_error = None
        for channel in self.rfcomm_channels:
            try:
                # Ensure stale binding is released before rebinding.
                subprocess.run(
                    ["rfcomm", "release", str(self.rfcomm_idx)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except Exception:
                pass

            try:
                result = subprocess.run(
                    ["rfcomm", "bind", str(self.rfcomm_idx), self.device_addr, str(channel)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    last_error = result.stderr.strip() or result.stdout.strip() or "rfcomm bind failed"
                    xbmc.log(
                        f"[BT_REMOTE] rfcomm bind failed on channel {channel}: {last_error}",
                        xbmc.LOGINFO,
                    )
                    continue

                fd = os.open(self.rfcomm_path, os.O_RDONLY | os.O_NONBLOCK)
                self.rfcomm_file = fd
                self.connected_channel = channel
                self.initialized = True
                xbmc.log(
                    f"[BT_REMOTE] RFCOMM TTY connected via {self.rfcomm_path} on channel {channel}",
                    xbmc.LOGINFO,
                )
                return True
            except Exception as exc:
                last_error = exc
                xbmc.log(
                    f"[BT_REMOTE] rfcomm TTY open failed on channel {channel}: {exc}",
                    xbmc.LOGINFO,
                )
                try:
                    subprocess.run(
                        ["rfcomm", "release", str(self.rfcomm_idx)],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                except Exception:
                    pass

        xbmc.log(
            f"[BT_REMOTE] rfcomm fallback failed for {self.device_addr} on channels {self.rfcomm_channels}: {last_error}",
            xbmc.LOGERROR,
        )
        self.initialized = False
        self.connected_channel = None
        return False
    
    def _discover_device(self):
        """Discover the Bluetooth remote device address."""
        if self.device_addr:
            xbmc.log(
                f"[BT_REMOTE] Using configured device address {self.device_addr}",
                xbmc.LOGINFO
            )
            return

        try:
            # Search paired devices first, then all known devices.
            for command in (["bluetoothctl", "paired-devices"], ["bluetoothctl", "devices"]):
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split("\n"):
                    if self.device_name in line:
                        # Format: "Device XX:XX:XX:XX:XX:XX VCR_REMOTE"
                        parts = line.split()
                        if len(parts) >= 2:
                            self.device_addr = parts[1]
                            xbmc.log(
                                f"[BT_REMOTE] Found device {self.device_name} at {self.device_addr}",
                                xbmc.LOGINFO
                            )
                            return
            
            xbmc.log(
                f"[BT_REMOTE] Device {self.device_name} not found in paired devices",
                xbmc.LOGERROR
            )
        except Exception as exc:
            xbmc.log(
                f"[BT_REMOTE] Device discovery failed: {exc}",
                xbmc.LOGERROR
            )
    
    def connect(self):
        """Connect to the Bluetooth remote."""
        if self.device_addr is None:
            xbmc.log("[BT_REMOTE] No device address available", xbmc.LOGERROR)
            return False

        if not hasattr(socket, "AF_BLUETOOTH"):
            xbmc.log(
                "[BT_REMOTE] socket.AF_BLUETOOTH unavailable; switching to rfcomm fallback",
                xbmc.LOGINFO,
            )
            return self._connect_via_rfcomm_tty()
        
        last_error = None
        for channel in self.rfcomm_channels:
            try:
                self.socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                self.socket.settimeout(2.0)
                self.socket.connect((self.device_addr, channel))
                self.initialized = True
                self.connected_channel = channel
                xbmc.log(
                    f"[BT_REMOTE] RFCOMM connected to {self.device_addr} on channel {channel}",
                    xbmc.LOGINFO
                )
                return True
            except Exception as exc:
                last_error = exc
                xbmc.log(
                    f"[BT_REMOTE] RFCOMM connect failed on channel {channel}: {exc}",
                    xbmc.LOGINFO
                )
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                self.socket = None

        xbmc.log(
            f"[BT_REMOTE] Connection failed for {self.device_addr} on channels {self.rfcomm_channels}: {last_error}",
            xbmc.LOGERROR
        )
        self.initialized = False
        self.connected_channel = None
        return False
    
    def read_events(self):
        """
        Read and parse events from the remote.
        Returns a list of event strings like ["PLAY_PAUSE", "SEEK:+10", "NEXT"]
        """
        events = []
        
        if not self.initialized or (self.socket is None and self.rfcomm_file is None):
            return events

        # Detect remote power-cycle/disconnect and force service-level reconnect.
        if not self._is_link_connected():
            raise ConnectionError("Bluetooth link lost")
        
        try:
            if self.socket is not None:
                data = self.socket.recv(1024).decode("utf-8", errors="ignore")
            elif self.rfcomm_file is not None:
                try:
                    chunk = os.read(self.rfcomm_file, 1024)
                    if not chunk:
                        return events
                    data = chunk.decode("utf-8", errors="ignore")
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        return events
                    raise
            else:
                return events

            if not data:
                return events

            # Throttled low-level RX debug, useful for diagnosing silent button presses.
            try:
                import time
                now = time.time()
                if now - self._last_rx_log_at >= 1.0:
                    self._last_rx_log_at = now
                    dbg = data.replace("\r", "\\r").replace("\n", "\\n")
                    xbmc.log(f"[BT_REMOTE] RX raw: {dbg[:120]}", xbmc.LOGINFO)
            except Exception:
                pass

            self._rx_buffer += data

            # First pass: line-based parsing for normal CR/LF terminated frames.
            parsed = []
            # Normalize CRLF/CR to LF, then split lines.
            normalized = self._rx_buffer.replace("\r\n", "\n").replace("\r", "\n")
            lines = normalized.split("\n")
            self._rx_buffer = lines.pop()  # keep incomplete trailing data
            for line in lines:
                line = line.strip()
                if line:
                    parsed.append(line)

            # Second pass fallback: scan for known tokens in the remaining stream.
            if self._rx_buffer:
                found = [m.group(1) for m in self._event_pattern.finditer(self._rx_buffer)]
                if found:
                    parsed.extend(found)
                    # Keep only a small tail in case a token is split across reads.
                    self._rx_buffer = self._rx_buffer[-32:]
                elif len(self._rx_buffer) > 256:
                    # Prevent unbounded growth for malformed data.
                    self._rx_buffer = self._rx_buffer[-64:]

            for evt in parsed:
                evt = evt.strip().upper()
                if evt:
                    events.append(evt)
        except socket.timeout:
            pass
        except Exception as exc:
            xbmc.log(f"[BT_REMOTE] Read error: {exc}", xbmc.LOGERROR)
            self.close()
            raise
        
        return events
    
    def close(self):
        """Close the Bluetooth connection."""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        if self.rfcomm_file is not None:
            try:
                os.close(self.rfcomm_file)
            except Exception:
                pass
            self.rfcomm_file = None
            try:
                subprocess.run(
                    ["rfcomm", "release", str(self.rfcomm_idx)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except Exception:
                pass
        self.socket = None
        self.initialized = False
        self.connected_channel = None
        self._rx_buffer = ""
        xbmc.log("[BT_REMOTE] Disconnected", xbmc.LOGINFO)
