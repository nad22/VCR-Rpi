import fcntl
import math
import os
import glob


I2C_SLAVE = 0x0703


_FONT_3X5 = {
    " ": [0b000, 0b000, 0b000, 0b000, 0b000],
    "-": [0b000, 0b000, 0b111, 0b000, 0b000],
    ":": [0b000, 0b010, 0b000, 0b010, 0b000],
    ".": [0b000, 0b000, 0b000, 0b000, 0b010],
    "0": [0b111, 0b101, 0b101, 0b101, 0b111],
    "1": [0b010, 0b110, 0b010, 0b010, 0b111],
    "2": [0b111, 0b001, 0b111, 0b100, 0b111],
    "3": [0b111, 0b001, 0b111, 0b001, 0b111],
    "4": [0b101, 0b101, 0b111, 0b001, 0b001],
    "5": [0b111, 0b100, 0b111, 0b001, 0b111],
    "6": [0b111, 0b100, 0b111, 0b101, 0b111],
    "7": [0b111, 0b001, 0b010, 0b010, 0b010],
    "8": [0b111, 0b101, 0b111, 0b101, 0b111],
    "9": [0b111, 0b101, 0b111, 0b001, 0b111],
    "A": [0b111, 0b101, 0b111, 0b101, 0b101],
    "B": [0b110, 0b101, 0b110, 0b101, 0b110],
    "C": [0b111, 0b100, 0b100, 0b100, 0b111],
    "D": [0b110, 0b101, 0b101, 0b101, 0b110],
    "E": [0b111, 0b100, 0b110, 0b100, 0b111],
    "F": [0b111, 0b100, 0b110, 0b100, 0b100],
    "G": [0b111, 0b100, 0b101, 0b101, 0b111],
    "H": [0b101, 0b101, 0b111, 0b101, 0b101],
    "I": [0b111, 0b010, 0b010, 0b010, 0b111],
    "J": [0b001, 0b001, 0b001, 0b101, 0b111],
    "K": [0b101, 0b101, 0b110, 0b101, 0b101],
    "L": [0b100, 0b100, 0b100, 0b100, 0b111],
    "M": [0b101, 0b111, 0b111, 0b101, 0b101],
    "N": [0b101, 0b111, 0b111, 0b111, 0b101],
    "O": [0b111, 0b101, 0b101, 0b101, 0b111],
    "P": [0b111, 0b101, 0b111, 0b100, 0b100],
    "Q": [0b111, 0b101, 0b101, 0b111, 0b001],
    "R": [0b111, 0b101, 0b111, 0b110, 0b101],
    "S": [0b111, 0b100, 0b111, 0b001, 0b111],
    "T": [0b111, 0b010, 0b010, 0b010, 0b010],
    "U": [0b101, 0b101, 0b101, 0b101, 0b111],
    "V": [0b101, 0b101, 0b101, 0b101, 0b010],
    "W": [0b101, 0b101, 0b111, 0b111, 0b101],
    "X": [0b101, 0b101, 0b010, 0b101, 0b101],
    "Y": [0b101, 0b101, 0b010, 0b010, 0b010],
    "Z": [0b111, 0b001, 0b010, 0b100, 0b111],
}


class SSD1309Display:
    WIDTH = 128
    HEIGHT = 64
    PAGES = 8

    def __init__(self, bus=1, address=0x3C, invert=False, rotate180=False, probe_mode="cmd"):
        self.bus = bus
        self.address = address
        self.invert = bool(invert)
        self.rotate180 = bool(rotate180)
        self.probe_mode = str(probe_mode or "cmd").lower()
        self.fd = None
        self.buffer = bytearray(self.WIDTH * self.PAGES)
        self._resolved_dev = None
        self._attempts = []
        self._vu_l = 0.0
        self._vu_r = 0.0
        self._peak_l = 0.0
        self._peak_r = 0.0
        self._peak_hold_l = 0
        self._peak_hold_r = 0
        self._open()
        self._init_panel()

    def _parse_address(self, address):
        if isinstance(address, str):
            text = address.strip().lower()
            if text == "auto":
                return None
            if text.startswith("0x"):
                return int(text, 16)
            return int(text)
        return int(address)

    def _normalize_address(self, address):
        # Accept both 7-bit addresses (0x3C/0x3D) and common shifted 8-bit forms (0x78/0x7A).
        if address >= 0x78:
            return address >> 1
        return address

    def _candidate_addresses(self):
        parsed = self._parse_address(self.address)
        if parsed is None:
            return [0x3C, 0x3D]

        normalized = self._normalize_address(parsed)
        candidates = [normalized]
        fallback = 0x3D if normalized == 0x3C else 0x3C
        candidates.append(fallback)
        deduped = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped

    def _rank_i2c_device(self, dev):
        try:
            bus_num = int(dev.rsplit("-", 1)[1])
        except Exception:
            bus_num = 999

        name_path = f"/sys/class/i2c-dev/i2c-{bus_num}/name"
        name = ""
        try:
            with open(name_path, "r", encoding="utf-8") as f:
                name = f.read().strip().lower()
        except Exception:
            pass

        # Prefer the physical Raspberry Pi GPIO I2C adapter and avoid HDMI DDC/CEC buses.
        if bus_num == 1:
            return (0, bus_num)
        if "ddc" in name or "cec" in name or "hdmi" in name:
            return (4, bus_num)
        if "bcm" in name or "bsc" in name or "rp1" in name or "i2c" in name:
            return (1, bus_num)
        return (2, bus_num)

    def _candidate_devices(self):
        if self.bus in ("auto", None, ""):
            devices = sorted(glob.glob("/dev/i2c-*"), key=self._rank_i2c_device)
            return devices

        try:
            bus_num = int(self.bus)
            return [f"/dev/i2c-{bus_num}"]
        except Exception:
            return [f"/dev/i2c-{self.bus}"]

    def _is_ddc_only_setup(self, devices):
        if not devices:
            return False

        bus_nums = []
        for dev in devices:
            try:
                bus_nums.append(int(dev.rsplit("-", 1)[1]))
            except Exception:
                pass

        if not bus_nums:
            return False

        # On Raspberry Pi, GPIO I2C is usually i2c-1. If only high-numbered buses
        # are present (for example 20/21), this is commonly HDMI DDC/CEC only.
        has_low_bus = any(num in (0, 1, 10, 11) for num in bus_nums)
        has_only_high = all(num >= 20 for num in bus_nums)
        return (not has_low_bus) and has_only_high

    def _open(self):
        last_error = None
        candidates = self._candidate_devices()
        if self.bus in ("auto", None, "") and self._is_ddc_only_setup(candidates):
            raise OSError(
                2,
                "Only high-numbered I2C buses found (likely HDMI DDC/CEC): "
                f"{candidates}. GPIO I2C bus is missing. Enable i2c_arm in "
                "/flash/config.txt (dtparam=i2c_arm=on) and reboot.",
            )

        for dev in candidates:
            fd = None
            if not os.path.exists(dev):
                last_error = FileNotFoundError(dev)
                continue
            for address in self._candidate_addresses():
                try:
                    fd = os.open(dev, os.O_RDWR)
                    fcntl.ioctl(fd, I2C_SLAVE, address)
                    # Some bridges reject specific probe bytes; allow a simple open-only probe mode.
                    if self.probe_mode == "cmd":
                        os.write(fd, bytes([0x00, 0xE3]))  # SSD13xx NOP
                    elif self.probe_mode == "data":
                        os.write(fd, bytes([0x40, 0x00]))
                    self.fd = fd
                    self._resolved_dev = dev
                    self.address = address
                    return
                except Exception as exc:
                    self._attempts.append(f"{dev}@0x{address:02X} -> {exc}")
                    last_error = exc
                    try:
                        if fd is not None:
                            os.close(fd)
                    except Exception:
                        pass
                    fd = None

        if last_error is None:
            last_error = FileNotFoundError("No /dev/i2c-* devices found")
        raise OSError(
            getattr(last_error, "errno", 2),
            "Unable to open SSD1309 I2C bus "
            f"(candidates={self._candidate_devices()}, addresses={self._candidate_addresses()}, "
            f"probe_mode={self.probe_mode}, attempts={self._attempts}): {last_error}",
        )

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
        self.fd = None

    def _write(self, payload):
        if self.fd is None:
            return
        os.write(self.fd, payload)

    def _cmd(self, *cmds):
        for c in cmds:
            self._write(bytes([0x00, c & 0xFF]))

    def _init_panel(self):
        self._cmd(
            0xAE,
            0xD5,
            0x80,
            0xA8,
            0x3F,
            0xD3,
            0x00,
            0x40,
            0x8D,
            0x14,
            0x20,
            0x00,
            0xA1 if not self.rotate180 else 0xA0,
            0xC8 if not self.rotate180 else 0xC0,
            0xDA,
            0x12,
            0x81,
            0xCF,
            0xD9,
            0xF1,
            0xDB,
            0x40,
            0xA4,
            0xA7 if self.invert else 0xA6,
            0xAF,
        )
        self.clear()
        self.flush()

    def clear(self):
        self.buffer = bytearray(self.WIDTH * self.PAGES)

    def set_pixel(self, x, y, on=True):
        if x < 0 or x >= self.WIDTH or y < 0 or y >= self.HEIGHT:
            return
        idx = x + (y // 8) * self.WIDTH
        bit = 1 << (y & 7)
        if on:
            self.buffer[idx] |= bit
        else:
            self.buffer[idx] &= (~bit & 0xFF)

    def hline(self, x, y, w, on=True):
        for i in range(max(0, w)):
            self.set_pixel(x + i, y, on)

    def vline(self, x, y, h, on=True):
        for i in range(max(0, h)):
            self.set_pixel(x, y + i, on)

    def rect(self, x, y, w, h, on=True):
        if w <= 0 or h <= 0:
            return
        self.hline(x, y, w, on)
        self.hline(x, y + h - 1, w, on)
        self.vline(x, y, h, on)
        self.vline(x + w - 1, y, h, on)

    def fill_rect(self, x, y, w, h, on=True):
        for yy in range(max(0, h)):
            self.hline(x, y + yy, w, on)

    def draw_char(self, x, y, ch):
        pat = _FONT_3X5.get(ch, _FONT_3X5[" "])
        for row in range(5):
            bits = pat[row]
            for col in range(3):
                if bits & (1 << (2 - col)):
                    self.set_pixel(x + col, y + row, True)

    def draw_text(self, x, y, text):
        xx = x
        for ch in text.upper():
            self.draw_char(xx, y, ch)
            xx += 4

    def _digit_segments(self, d):
        seg = {
            "0": "abcedf",
            "1": "bc",
            "2": "abged",
            "3": "abgcd",
            "4": "fgbc",
            "5": "afgcd",
            "6": "afgecd",
            "7": "abc",
            "8": "abcdefg",
            "9": "abfgcd",
        }
        return seg.get(d, "")

    def draw_digit7(self, x, y, d, w=12, h=22, t=2):
        segs = self._digit_segments(d)
        # a
        if "a" in segs:
            self.fill_rect(x + t, y, w - 2 * t, t)
        # b
        if "b" in segs:
            self.fill_rect(x + w - t, y + t, t, h // 2 - t)
        # c
        if "c" in segs:
            self.fill_rect(x + w - t, y + h // 2, t, h // 2 - t)
        # d
        if "d" in segs:
            self.fill_rect(x + t, y + h - t, w - 2 * t, t)
        # e
        if "e" in segs:
            self.fill_rect(x, y + h // 2, t, h // 2 - t)
        # f
        if "f" in segs:
            self.fill_rect(x, y + t, t, h // 2 - t)
        # g
        if "g" in segs:
            self.fill_rect(x + t, y + h // 2 - t // 2, w - 2 * t, t)

    def draw_colon(self, x, y):
        self.fill_rect(x, y + 6, 2, 2)
        self.fill_rect(x, y + 14, 2, 2)

    def _draw_transport(self, x, y, state):
        st = (state or "").upper()

        # REW icon <<
        self.fill_rect(x + 0, y + 3, 1, 3, True)
        self.fill_rect(x + 1, y + 2, 1, 5, True)
        self.fill_rect(x + 2, y + 1, 1, 7, True)
        self.fill_rect(x + 4, y + 3, 1, 3, True)
        self.fill_rect(x + 5, y + 2, 1, 5, True)
        self.fill_rect(x + 6, y + 1, 1, 7, True)

        # PLAY icon >
        px = x + 14
        self.fill_rect(px + 0, y + 1, 1, 7, True)
        self.fill_rect(px + 1, y + 2, 1, 5, True)
        self.fill_rect(px + 2, y + 3, 1, 3, True)

        # PAUSE icon ||
        qx = x + 23
        self.fill_rect(qx + 0, y + 1, 1, 7, True)
        self.fill_rect(qx + 2, y + 1, 1, 7, True)

        # FF icon >>
        fx = x + 30
        self.fill_rect(fx + 0, y + 3, 1, 3, True)
        self.fill_rect(fx + 1, y + 2, 1, 5, True)
        self.fill_rect(fx + 2, y + 1, 1, 7, True)
        self.fill_rect(fx + 4, y + 3, 1, 3, True)
        self.fill_rect(fx + 5, y + 2, 1, 5, True)
        self.fill_rect(fx + 6, y + 1, 1, 7, True)

        # Highlight active transport symbol with a tiny underline bar.
        if "REW" in st or st == "RW":
            self.fill_rect(x, y + 9, 7, 1, True)
        elif "PLAY" in st:
            self.fill_rect(px, y + 9, 3, 1, True)
        elif "PAUSE" in st:
            self.fill_rect(qx, y + 9, 3, 1, True)
        elif "FAST" in st or "FF" in st:
            self.fill_rect(fx, y + 9, 7, 1, True)

    def _draw_meter_scale(self, x, y, bars, bw, gap):
        for i in range(bars):
            xx = x + i * (bw + gap)
            self.fill_rect(xx, y, bw, 1, True)
           # if i in (0, 2, 4, 6):
            #    self.fill_rect(xx + 1, y - 1, 1, 1, True)

    

    def _draw_lr_label(self, x, y, channel):
        c = (channel or "L").upper()
        if c == "L":
            self.fill_rect(x, y, 1, 8, True)
            self.fill_rect(x, y + 7, 5, 1, True)
            return

        # R glyph
        self.fill_rect(x, y, 1, 8, True)
        self.fill_rect(x + 1, y, 3, 1, True)
        self.fill_rect(x + 4, y + 1, 1, 2, True)
        self.fill_rect(x + 1, y + 3, 3, 1, True)
        self.fill_rect(x + 2, y + 4, 1, 1, True)
        self.fill_rect(x + 3, y + 5, 1, 1, True)
        self.fill_rect(x + 4, y + 6, 1, 1, True)

    def _draw_cassette(self, x, y):
        """Cassette tape icon, 26 × 18 px, matching the standard cassette symbol.

        Layout:
          - Outer rounded-rectangle border (1 px, 2 px corner radius)
          - Two hollow circular reels (thick ring: outer r≈5, inner r≈2.5)
          - Omega-shaped tape-path at the bottom connecting the two reels
        """
        W, H = 22, 14

        # --- Outer rectangle (eckig, keine abgerundeten Ecken) ---
        self.hline(x,     y,         W)          # top
        self.hline(x,     y + H - 1, W)          # bottom
        self.vline(x,         y, H)              # left
        self.vline(x + W - 1, y, H)              # right

        
        def _circle(cx, cy, r):
            px = 0
            py = r
            d = 3 - 2 * r
            while px <= py:
                for dx, dy in ((px, py), (py, px), (-px, py), (-py, px),
                            (-px, -py), (-py, -px), (px, -py), (py, -px)):
                    self.fill_rect(cx + dx, cy + dy, 1, 1, True)
                if d < 0:
                    d += 4 * px + 6
                else:
                    d += 4 * (px - py) + 10
                    py -= 1
                px += 1

        r = 3
        cy = y + 7
        left_cx  = x + 6
        right_cx = x + W - 7

        # Linker und rechter Kreis, je nur eine Linie
        _circle(left_cx,  cy, r)
        _circle(right_cx, cy, r)

        # --- Strich tangential zur Oberkante beider Kreise ---
        top_y = cy - r  # Tangentenpunkt oben
        self.hline(left_cx, top_y, right_cx - left_cx + 1)
        y = y + 16
        self.draw_text(x + 3, y + 2, "AUTO")
        W, H = 22, 9
        self.hline(x,     y,         W)          # top
        self.hline(x,     y + H - 1, W)          # bottom
        self.vline(x,         y, H)              # left
        self.vline(x + W - 1, y, H)              # right

    def _scroll_title(self, title, tick):
        t = (title or "-").upper()
        vis_chars = 28
        if len(t) <= vis_chars:
            return t
        offset = (tick // 3) % (len(t) + 6)
        pad = t + "      " + t
        return pad[offset:offset + vis_chars]

    def _smooth_vu(self, current, target, attack=0.98, release=0.85):
        if target >= current:
            return current + (target - current) * attack
        return current + (target - current) * release

    def _update_peak(self, peak, level, hold_counter, hold_frames=1, decay=0.30):
        if level >= peak:
            return level, hold_frames
        if hold_counter > 0:
            return peak, hold_counter - 1
        return max(0.0, peak - decay), 0

    def render_vfd(self, state, timecode, title, volume, tick, level_l=None, level_r=None):
        self.clear()

        # Layered bezel lines to get a denser VFD front-panel look.
        self.rect(0, 0, self.WIDTH, self.HEIGHT)
        self.rect(1, 1, self.WIDTH - 2, self.HEIGHT - 2)
        self.hline(2, 33, self.WIDTH - 4)
        self.hline(2, 42, self.WIDTH - 4)

        #title_line = self._scroll_title(title, tick)
        #self.draw_text(3, 3, title_line)

        tc = (timecode or "00:00:00")
        if len(tc) != 8:
            tc = "00:00:00"
        digits = [tc[0], tc[1], tc[3], tc[4], tc[6], tc[7]]
        x = 8
        y = 7
        for i, d in enumerate(digits):
            self.draw_digit7(x, y, d)
            x += 13
            if i in (1, 3):
                self.draw_colon(x + 1, y)
                x += 5

        #self._draw_transport(6, 44, state)

        state_txt = (state or "STOP")[:6]
        self.draw_text(8, 36, state_txt)

        # Cassette icon right of time when a video is loaded
        if (state or "").upper() not in ("", "STOP", "IDLE"):
            self._draw_cassette(100, 5)
        
        

        # Honest VU: use explicit channel levels when available.
        if level_l is not None and level_r is not None:
            target_l = max(0.0, min(1.0, float(level_l) / 100.0))
            target_r = max(0.0, min(1.0, float(level_r) / 100.0))
        else:
            base = max(0.0, min(1.0, float(volume) / 100.0))
            target_l = base
            target_r = base
        self._vu_l = self._smooth_vu(self._vu_l, target_l)
        self._vu_r = self._smooth_vu(self._vu_r, target_r)
        self._peak_l, self._peak_hold_l = self._update_peak(self._peak_l, self._vu_l, self._peak_hold_l)
        self._peak_r, self._peak_hold_r = self._update_peak(self._peak_r, self._vu_r, self._peak_hold_r)

        bars = 18
        bw = 2
        gap = 1
        x_l = 14
        x_r = 14
        y_l = 48
        y_r = 55

        self.draw_text(8, 47, "L")
        self.draw_text(8, 54, "R")

        l_on = int(round(self._vu_l * bars))
        r_on = int(round(self._vu_r * bars))
        l_peak = max(0, min(bars - 1, int(round(self._peak_l * bars)) - 1))
        r_peak = max(0, min(bars - 1, int(round(self._peak_r * bars)) - 1))

        self._draw_meter_scale(x_l, y_l - 1, bars, bw, gap)
        self._draw_meter_scale(x_r, y_r - 1, bars, bw, gap)

        for i in range(bars):
            on_l = i < l_on
            on_r = i < r_on
            xx = x_l + i * (bw + gap)
            self.fill_rect(xx, y_l, bw, 3, on_l)
            if i == l_peak:
                self.fill_rect(xx, y_l + 3, bw, 1, True)

            xx2 = x_r + i * (bw + gap)
            self.fill_rect(xx2, y_r, bw, 3, on_r)
            if i == r_peak:
                self.fill_rect(xx2, y_r + 3, bw, 1, True)

        self.flush()

    def flush(self):
        self._cmd(0x21, 0x00, self.WIDTH - 1)
        self._cmd(0x22, 0x00, self.PAGES - 1)
        for page in range(self.PAGES):
            start = page * self.WIDTH
            chunk = self.buffer[start:start + self.WIDTH]
            self._write(bytes([0x40]) + bytes(chunk))
