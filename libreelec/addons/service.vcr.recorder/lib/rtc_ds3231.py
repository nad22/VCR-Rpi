"""Minimal I2C driver for the DS3231 real-time-clock module.

The DS3231 is the standard, cheap, high-precision RTC breakout board
(often sold as "DS3231 RTC module"). It uses the same I2C bus as the
SSD1309 OLED display (SDA=GPIO2/Pin3, SCL=GPIO3/Pin5, 3.3V, GND) --
no extra GPIO pins are required, only a free I2C address (default 0x68).
"""

import fcntl
import glob
import os
import time


I2C_SLAVE = 0x0703

_REG_SECONDS = 0x00
_REG_MINUTES = 0x01
_REG_HOURS = 0x02
_REG_DAY = 0x03
_REG_DATE = 0x04
_REG_MONTH = 0x05
_REG_YEAR = 0x06


def _bcd_to_int(value):
    return (value >> 4) * 10 + (value & 0x0F)


def _int_to_bcd(value):
    return ((value // 10) << 4) | (value % 10)


class DS3231Rtc:
    def __init__(self, bus="auto", address="0x68"):
        self.bus = bus
        self.address = self._parse_address(address)
        self.fd = None
        self._resolved_dev = None
        self._open()

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
        self.fd = None

    def _parse_address(self, value):
        if isinstance(value, str):
            text = value.strip().lower()
            if text.startswith("0x"):
                return int(text, 16)
            return int(text)
        return int(value)

    def _candidate_devices(self):
        if self.bus in ("auto", None, ""):
            devices = sorted(glob.glob("/dev/i2c-*"))
            preferred = []
            other = []
            for dev in devices:
                if dev.endswith("-1"):
                    preferred.append(dev)
                else:
                    other.append(dev)
            return preferred + other
        try:
            return [f"/dev/i2c-{int(self.bus)}"]
        except Exception:
            return [f"/dev/i2c-{self.bus}"]

    def _open(self):
        last_error = None
        for dev in self._candidate_devices():
            if not os.path.exists(dev):
                last_error = FileNotFoundError(dev)
                continue
            fd = None
            try:
                fd = os.open(dev, os.O_RDWR)
                fcntl.ioctl(fd, I2C_SLAVE, self.address)
                # Quick probe: read back the seconds register.
                os.write(fd, bytes([_REG_SECONDS]))
                os.read(fd, 1)
                self.fd = fd
                self._resolved_dev = dev
                return
            except Exception as exc:
                last_error = exc
                try:
                    if fd is not None:
                        os.close(fd)
                except Exception:
                    pass

        if last_error is None:
            last_error = FileNotFoundError("No /dev/i2c-* devices found")
        raise OSError(getattr(last_error, "errno", 2), f"DS3231 open failed: {last_error}")

    def read_datetime(self):
        """Return (hour, minute, second) read from the RTC (24h)."""
        os.write(self.fd, bytes([_REG_SECONDS]))
        data = os.read(self.fd, 7)
        second = _bcd_to_int(data[0] & 0x7F)
        minute = _bcd_to_int(data[1] & 0x7F)
        hour_raw = data[2]
        if hour_raw & 0x40:  # 12-hour mode bit set
            hour = _bcd_to_int(hour_raw & 0x1F)
            if hour_raw & 0x20:  # PM
                hour = (hour % 12) + 12
            else:
                hour = hour % 12
        else:
            hour = _bcd_to_int(hour_raw & 0x3F)
        return hour, minute, second

    def read_time_str(self):
        hour, minute, second = self.read_datetime()
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    def set_datetime(self, hour, minute, second, weekday=1, day=1, month=1, year=25):
        """Write a 24h time (and date) to the RTC."""
        payload = bytes([
            _REG_SECONDS,
            _int_to_bcd(second),
            _int_to_bcd(minute),
            _int_to_bcd(hour),
            _int_to_bcd(weekday),
            _int_to_bcd(day),
            _int_to_bcd(month),
            _int_to_bcd(year % 100),
        ])
        os.write(self.fd, payload)

    def sync_from_system(self):
        """Write the current OS clock into the RTC (e.g. once NTP has set it)."""
        now = time.localtime()
        self.set_datetime(
            now.tm_hour, now.tm_min, now.tm_sec,
            weekday=now.tm_wday + 1, day=now.tm_mday,
            month=now.tm_mon, year=now.tm_year % 100,
        )
