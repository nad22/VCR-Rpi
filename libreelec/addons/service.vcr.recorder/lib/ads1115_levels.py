import fcntl
import glob
import os
import struct
import time


I2C_SLAVE = 0x0703

_REG_CONVERSION = 0x00
_REG_CONFIG = 0x01

_MUX_SINGLE = {
    0: 0x4000,  # AIN0 vs GND
    1: 0x5000,  # AIN1 vs GND
    2: 0x6000,  # AIN2 vs GND
    3: 0x7000,  # AIN3 vs GND
}

_PGA = {
    "6.144": 0x0000,
    "4.096": 0x0200,
    "2.048": 0x0400,
    "1.024": 0x0600,
    "0.512": 0x0800,
    "0.256": 0x0A00,
}

_DR = {
    8: 0x0000,
    16: 0x0020,
    32: 0x0040,
    64: 0x0060,
    128: 0x0080,
    250: 0x00A0,
    475: 0x00C0,
    860: 0x00E0,
}


class ADS1115LevelReader:
    def __init__(
        self,
        bus="auto",
        address="0x48",
        channel_left=0,
        channel_right=1,
        gain="4.096",
        sps=860,
        bias=16384,
        full_scale_delta=6,
        noise_floor=1,
        samples_per_read=2,
        baseline_alpha=0.10,
    ):
        self.bus = bus
        self.address = self._parse_address(address)
        self.channel_left = int(channel_left)
        self.channel_right = int(channel_right)
        self.gain = str(gain)
        self.sps = int(sps)
        self.bias = float(bias)
        self.full_scale_delta = max(1, int(full_scale_delta))
        self.noise_floor = max(0, int(noise_floor))
        self.samples_per_read = max(2, int(samples_per_read))
        self.baseline_alpha = min(0.2, max(0.0, float(baseline_alpha)))

        self._baseline_by_channel = {
            0: float(self.bias),
            1: float(self.bias),
            2: float(self.bias),
            3: float(self.bias),
        }
        self._baseline_initialized = {0: False, 1: False, 2: False, 3: False}

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
                # Quick read probe
                self._set_pointer(fd, _REG_CONVERSION)
                os.read(fd, 2)
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
        raise OSError(getattr(last_error, "errno", 2), f"ADS1115 open failed: {last_error}")

    def _set_pointer(self, fd, register):
        os.write(fd, bytes([register & 0xFF]))

    def _write_config(self, fd, config):
        payload = bytes([_REG_CONFIG, (config >> 8) & 0xFF, config & 0xFF])
        os.write(fd, payload)

    def _read_conversion(self, fd):
        self._set_pointer(fd, _REG_CONVERSION)
        raw = os.read(fd, 2)
        val = struct.unpack(">h", raw)[0]
        return val

    def _sample_channel(self, channel):
        if channel not in _MUX_SINGLE:
            channel = 0

        pga_bits = _PGA.get(self.gain, _PGA["4.096"])
        dr_bits = _DR.get(self.sps, _DR[860])

        # OS=1 (start single), MUX, PGA, MODE=1(single-shot), DR, COMP_QUE=11(disable)
        config = 0x8000 | _MUX_SINGLE[channel] | pga_bits | 0x0100 | dr_bits | 0x0003
        self._write_config(self.fd, config)

        # Keep latency low while still waiting for one full conversion cycle.
        wait_s = max(0.0007, (1.0 / max(8, self.sps)) * 1.00)
        time.sleep(wait_s)
        return self._read_conversion(self.fd)

    def _sample_burst(self, channel, count):
        values = []
        for _ in range(count):
            values.append(self._sample_channel(channel))
        return values

    def _to_percent_from_window(self, channel, samples):
        if not samples:
            return 0

        mean = sum(samples) / float(len(samples))
        vmin = float(min(samples))
        vmax = float(max(samples))

        # AC estimate from local peak-to-peak window.
        delta_ac = 0.5 * (vmax - vmin)

        # DC/envelope estimate around per-channel baseline.
        baseline = self._baseline_by_channel.get(channel, float(self.bias))
        if not self._baseline_initialized.get(channel, False):
            baseline = mean
            self._baseline_by_channel[channel] = baseline
            self._baseline_initialized[channel] = True

        # Only adapt baseline when signal is low, so real program material is not cancelled.
        quiet_threshold = float(self.noise_floor) * 3.0
        if delta_ac < quiet_threshold:
            a = self.baseline_alpha
            baseline = (1.0 - a) * baseline + a * mean
            self._baseline_by_channel[channel] = baseline

        delta_dc = abs(mean - baseline)

        # Small AC program material can be under-represented with very short windows,
        # so bias the result toward the AC envelope while still honoring DC movement.
        delta = max(delta_ac * 2.0, delta_dc)

        # Remove fixed front-end noise floor.
        delta = max(0.0, delta - float(self.noise_floor))

        pct = int((delta / float(self.full_scale_delta)) * 100.0)
        return max(0, min(100, pct))

    def _legacy_to_percent(self, samples):
        # Kept as fallback helper for troubleshooting.
        mean = sum(samples) / float(len(samples))
        peak_delta = 0.0
        for v in samples:
            d = abs(float(v) - mean)
            if d > peak_delta:
                peak_delta = d

        # Subtract fixed ADC noise floor.
        delta = max(0.0, peak_delta - float(self.noise_floor))
        pct = int((delta / float(self.full_scale_delta)) * 100.0)
        return max(0, min(100, pct))

    def read_levels(self):
        if self.fd is None:
            return {"left": 0, "right": 0}

        left_samples = self._sample_burst(self.channel_left, self.samples_per_read)
        right_samples = self._sample_burst(self.channel_right, self.samples_per_read)

        return {
            "left": self._to_percent_from_window(self.channel_left, left_samples),
            "right": self._to_percent_from_window(self.channel_right, right_samples),
        }
