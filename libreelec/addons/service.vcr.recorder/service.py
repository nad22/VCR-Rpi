import json
import glob
import os
import time
import errno
import re
import shutil
import subprocess

import xbmc
import xbmcaddon
import xbmcvfs

from lib.kodi_rpc import KodiRpc
from lib.ssd1309_display import SSD1309Display


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
DATA_DIR = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")
os.makedirs(DATA_DIR, exist_ok=True)


def load_json(filename, default):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        xbmc.log(f"[{ADDON_ID}] Failed to load {filename}: {exc}", xbmc.LOGERROR)
        return default


def log(msg):
    xbmc.log(f"[{ADDON_ID}] {msg}", xbmc.LOGINFO)


def _read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return default


def _write_text(path, value):
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(value))


class GpioButtonReader:
    SYSFS_GPIO_DIR = "/sys/class/gpio"

    def __init__(self, buttons):
        self.buttons = buttons
        self.states = {}
        self.initialized = False

    def _gpio_dir(self, pin):
        return os.path.join(self.SYSFS_GPIO_DIR, f"gpio{pin}")

    def _gpio_file(self, pin, name):
        return os.path.join(self._gpio_dir(pin), name)

    def _chip_infos(self):
        chips = []
        try:
            for name in os.listdir(self.SYSFS_GPIO_DIR):
                if not name.startswith("gpiochip"):
                    continue
                chip_dir = os.path.join(self.SYSFS_GPIO_DIR, name)
                base = int(_read_text(os.path.join(chip_dir, "base"), "-1"))
                ngpio = int(_read_text(os.path.join(chip_dir, "ngpio"), "0"))
                label = _read_text(os.path.join(chip_dir, "label"), "")
                if base >= 0 and ngpio > 0:
                    chips.append({"base": base, "ngpio": ngpio, "label": label})
        except Exception:
            return []
        return chips

    def _is_valid_global_gpio(self, pin, chips):
        for chip in chips:
            if chip["base"] <= pin < (chip["base"] + chip["ngpio"]):
                return True
        return False

    def _resolve_sysfs_pin(self, configured_pin):
        pin = int(configured_pin)
        chips = self._chip_infos()
        if not chips:
            return pin

        if self._is_valid_global_gpio(pin, chips):
            return pin

        for chip in chips:
            label = chip["label"].lower()
            if "bcm" in label or "raspberry" in label or "pinctrl" in label:
                if 0 <= pin < chip["ngpio"]:
                    candidate = chip["base"] + pin
                    if self._is_valid_global_gpio(candidate, chips):
                        log(f"GPIO pin mapping: BCM {pin} -> sysfs {candidate} ({chip['label']})")
                        return candidate

        return pin

    def _export_pin(self, pin):
        gpio_dir = self._gpio_dir(pin)
        if not os.path.isdir(gpio_dir):
            try:
                _write_text(os.path.join(self.SYSFS_GPIO_DIR, "export"), pin)
            except OSError as exc:
                # Pin already exported by another process is not fatal.
                if exc.errno != errno.EBUSY:
                    raise OSError(exc.errno, f"export failed for GPIO{pin}: {exc}")

            # Sysfs entries may appear with a short delay after export.
            for _ in range(10):
                if os.path.isdir(gpio_dir):
                    break
                time.sleep(0.02)

            if not os.path.isdir(gpio_dir):
                raise OSError(errno.ENOENT, f"GPIO directory not created for pin {pin}")

    def _setup_pin(self, btn):
        self._apply_pull(btn)

        pin = self._resolve_sysfs_pin(btn["pin"])
        btn["_sysfs_pin"] = pin
        self._export_pin(pin)
        try:
            _write_text(self._gpio_file(pin, "direction"), "in")
        except OSError as exc:
            raise OSError(exc.errno, f"direction write failed for GPIO{pin}: {exc}")

        # Keep kernel polarity at active_low=0 and handle polarity in Python only.
        # This avoids double inversion inconsistencies across sysfs implementations.
        active_low = "0"
        active_low_file = self._gpio_file(pin, "active_low")
        if os.path.exists(active_low_file):
            try:
                _write_text(active_low_file, active_low)
            except OSError as exc:
                # Some kernels lock active_low for certain lines; continue with default polarity.
                log(f"GPIO{pin} active_low unchanged: {exc}")

        value = _read_text(self._gpio_file(pin, "value"), "1")
        pressed = value == "0" if bool(btn.get("active_low", True)) else value == "1"
        self.states[pin] = {"pressed": pressed, "last_event_at": 0.0}
        log(
            f"GPIO{pin} initialized: raw={value}, active_low={bool(btn.get('active_low', True))}, "
            f"pressed={pressed}"
        )

    def _apply_pull(self, btn):
        bcm_pin = int(btn.get("pin", -1))
        if bcm_pin < 0:
            return

        active_low = bool(btn.get("active_low", True))
        desired = str(btn.get("pull", "up" if active_low else "down")).strip().lower()
        if desired not in ("up", "down", "off"):
            desired = "up" if active_low else "down"

        if desired == "up":
            pud = "pu"
        elif desired == "down":
            pud = "pd"
        else:
            pud = "pn"

        # Best effort: try modern pinctrl first, then legacy raspi-gpio.
        cmds = []
        pinctrl = shutil.which("pinctrl")
        if pinctrl:
            cmds.append([pinctrl, "set", str(bcm_pin), "ip", pud])

        raspi_gpio = shutil.which("raspi-gpio")
        if raspi_gpio:
            cmds.append([raspi_gpio, "set", str(bcm_pin), "ip", pud])

        if not cmds:
            log(f"GPIO BCM{bcm_pin}: no pinctrl/raspi-gpio found to apply pull-{desired}")
            return

        last_err = None
        for cmd in cmds:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=0.5, check=False)
                if proc.returncode == 0:
                    log(f"GPIO BCM{bcm_pin}: pull-{desired} applied via {' '.join(cmd[:2])}")
                    return
                last_err = (proc.stderr or proc.stdout or "").strip()
            except Exception as exc:
                last_err = str(exc)

        log(f"GPIO BCM{bcm_pin}: failed to apply pull-{desired}: {last_err}")

    def setup(self):
        ok = 0
        pressed_init = 0
        for btn in self.buttons:
            pin = btn.get("pin")
            try:
                self._setup_pin(btn)
                ok += 1
                st = self.states.get(int(btn.get("_sysfs_pin", pin)), {})
                if st.get("pressed", False):
                    pressed_init += 1
            except Exception as exc:
                log(f"GPIO setup failed for pin {pin}: {exc}")

        self.initialized = ok > 0
        if self.initialized:
            log(f"GPIO input active for {ok}/{len(self.buttons)} buttons")
            if ok > 0 and pressed_init == ok:
                log(
                    "GPIO warning: all buttons read PRESSED at startup. "
                    "Likely missing/incorrect pull resistors or wrong polarity. "
                    "For button-to-GND use active_low=true and pull=up."
                )
            return True

        log("GPIO setup failed: no usable GPIO buttons")
        return False

    def close(self):
        self.initialized = False
        self.states = {}

    def read_events(self):
        if not self.initialized:
            return []

        events = []
        now = time.monotonic()
        for btn in self.buttons:
            pin = int(btn.get("_sysfs_pin", btn["pin"]))
            value = _read_text(self._gpio_file(pin, "value"), "1")
            pressed = value == "0" if bool(btn.get("active_low", True)) else value == "1"

            st = self.states.get(pin)
            if st is None:
                self.states[pin] = {"pressed": pressed, "last_event_at": 0.0}
                continue

            if pressed != st["pressed"]:
                st["pressed"] = pressed
                if pressed:
                    debounce_ms = int(btn.get("debounce_ms", 50))
                    if (now - st["last_event_at"]) * 1000.0 >= debounce_ms:
                        st["last_event_at"] = now
                        events.append(btn["event"])

        return events


class GpiodCliButtonReader:
    def __init__(self, buttons, chip="gpiochip0"):
        self.buttons = buttons
        self.chip = chip
        self.states = {}
        self.initialized = False
        self.gpioget_path = shutil.which("gpioget")

    def _parse_level(self, text):
        text = (text or "").strip()
        if text in ("0", "1"):
            return int(text)
        m = re.search(r"([01])\s*$", text)
        if m:
            return int(m.group(1))
        raise ValueError(f"Unexpected gpioget output: {text}")

    def _read_level(self, pin):
        if not self.gpioget_path:
            raise FileNotFoundError("gpioget not found")

        # Try modern numeric mode first, then fallback to plain output mode.
        cmds = [
            [self.gpioget_path, "--numeric", self.chip, str(pin)],
            [self.gpioget_path, self.chip, str(pin)],
        ]

        last_err = None
        for cmd in cmds:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=0.3,
                    check=False,
                )
                if proc.returncode == 0:
                    return self._parse_level(proc.stdout)
                last_err = (proc.stderr or proc.stdout or "").strip()
            except Exception as exc:
                last_err = str(exc)

        raise RuntimeError(f"gpioget failed for {self.chip}:{pin}: {last_err}")

    def setup(self):
        if not self.gpioget_path:
            log("gpiod backend unavailable: gpioget not found")
            return False

        ok = 0
        for btn in self.buttons:
            pin = int(btn["pin"])
            try:
                level = self._read_level(pin)
                pressed = level == 0 if bool(btn.get("active_low", True)) else level == 1
                self.states[pin] = {"pressed": pressed, "last_event_at": 0.0}
                ok += 1
            except Exception as exc:
                log(f"gpiod setup failed for pin {pin}: {exc}")

        self.initialized = ok > 0
        if self.initialized:
            log(f"gpiod input active on {self.chip} for {ok}/{len(self.buttons)} buttons")
            return True

        log("gpiod setup failed: no usable GPIO buttons")
        return False

    def close(self):
        self.initialized = False
        self.states = {}

    def read_events(self):
        if not self.initialized:
            return []

        events = []
        now = time.monotonic()
        for btn in self.buttons:
            pin = int(btn["pin"])
            try:
                level = self._read_level(pin)
            except Exception as exc:
                log(f"gpiod read failed for pin {pin}: {exc}")
                continue

            pressed = level == 0 if bool(btn.get("active_low", True)) else level == 1
            st = self.states.get(pin)
            if st is None:
                self.states[pin] = {"pressed": pressed, "last_event_at": 0.0}
                continue

            if pressed != st["pressed"]:
                st["pressed"] = pressed
                if pressed:
                    debounce_ms = int(btn.get("debounce_ms", 50))
                    if (now - st["last_event_at"]) * 1000.0 >= debounce_ms:
                        st["last_event_at"] = now
                        events.append(btn["event"])

        return events


def build_button_mapping(cfg):
    mapping = {}
    for button in cfg.get("buttons", []):
        event_name = button.get("event")
        action = button.get("action")
        if not event_name or not action:
            continue
        mapping[event_name.upper()] = action
    return mapping


def build_gpio_buttons(cfg):
    buttons = []
    for button in cfg.get("buttons", []):
        if button.get("source") != "gpio":
            continue
        if "pin" not in button or not button.get("event"):
            continue
        buttons.append(button)
    return buttons


def dispatch_action(rpc, action):
    if action == "Player.PlayPause":
        rpc.play_pause()
    elif action == "Player.Stop":
        rpc.stop()
    elif action == "Player.GoNext":
        rpc.goto_next()
    elif action == "Player.GoPrevious":
        rpc.goto_previous()
    elif action == "Input.FastForward":
        rpc.execute_action("fastforward")
    elif action == "Input.Rewind":
        rpc.execute_action("rewind")
    else:
        log(f"Unknown action mapping: {action}")


def run():
    monitor = xbmc.Monitor()
    rpc = KodiRpc()
    gpio_reader = None
    display = None

    buttons_cfg = {"buttons": []}
    button_map = {}
    next_cfg_reload = 0
    last_buttons_cfg_raw = ""
    last_display_cfg_raw = ""

    last_state = ""
    last_timecode = ""
    last_volume = 0
    next_volume_poll = 0.0
    tick = 0
    log("Service started")

    while not monitor.abortRequested():
        now = time.monotonic()
        if now >= next_cfg_reload:
            buttons_cfg = load_json("buttons.json", {"buttons": []})
            button_map = build_button_mapping(buttons_cfg)

            display_cfg = load_json(
                "display.json",
                {
                    "enabled": True,
                    "driver": "ssd1309",
                    "bus": "auto",
                    "address": "0x3C",
                    "invert": False,
                    "rotate180": False,
                },
            )
            next_cfg_reload = now + 5

            cfg_raw = json.dumps(buttons_cfg, sort_keys=True)
            if cfg_raw != last_buttons_cfg_raw:
                gpio_buttons = build_gpio_buttons(buttons_cfg)
                gpio_cfg = buttons_cfg.get("gpio", {})
                gpio_backend = str(gpio_cfg.get("backend", "auto")).lower()
                gpio_chip = str(gpio_cfg.get("chip", "gpiochip0"))

                if gpio_reader is not None:
                    gpio_reader.close()
                    gpio_reader = None
                if gpio_buttons:
                    if gpio_backend in ("auto", "gpiod"):
                        reader = GpiodCliButtonReader(gpio_buttons, chip=gpio_chip)
                        if reader.setup():
                            gpio_reader = reader

                    if gpio_reader is None and gpio_backend in ("auto", "sysfs"):
                        reader = GpioButtonReader(gpio_buttons)
                        if reader.setup():
                            gpio_reader = reader

                    if gpio_reader is None:
                        log(f"No GPIO backend available (requested backend={gpio_backend})")
                last_buttons_cfg_raw = cfg_raw

            display_cfg_raw = json.dumps(display_cfg, sort_keys=True)
            if display_cfg_raw != last_display_cfg_raw:
                if display is not None:
                    display.close()
                    display = None

                if bool(display_cfg.get("enabled", True)):
                    try:
                        addr_value = display_cfg.get("address", "0x3C")
                        addr = int(addr_value, 16) if isinstance(addr_value, str) else int(addr_value)
                        bus_value = display_cfg.get("bus", "auto")
                        probe_mode = str(display_cfg.get("probe_mode", "cmd")).lower()
                        i2c_devices = sorted(glob.glob("/dev/i2c-*"))
                        log(f"SSD1309 config: bus={bus_value}, address=0x{addr:02X}, probe_mode={probe_mode}, i2c_devices={i2c_devices or ['none']}")
                        display = SSD1309Display(
                            bus=bus_value,
                            address=addr,
                            probe_mode=probe_mode,
                            invert=bool(display_cfg.get("invert", False)),
                            rotate180=bool(display_cfg.get("rotate180", False)),
                        )
                        log(f"SSD1309 display initialized on {getattr(display, '_resolved_dev', 'unknown')}")
                    except Exception as exc:
                        display = None
                        log(f"SSD1309 init failed: {exc}")

                last_display_cfg_raw = display_cfg_raw

        if gpio_reader is not None:
            events = gpio_reader.read_events()
            for event in events:
                action = button_map.get(event)
                if action:
                    dispatch_action(rpc, action)
                    log(f"GPIO event {event} -> {action}")

        snapshot = rpc.get_playback_snapshot()
        if now >= next_volume_poll:
            try:
                last_volume = rpc.get_audio_level()
            except Exception as exc:
                log(f"Audio level poll failed: {exc}")
            next_volume_poll = now + 0.5

        state = snapshot["state"]
        timecode = snapshot["timecode"]
        if state != last_state or timecode != last_timecode:
            log(f"Playback {state} {timecode} {snapshot['title']}")
            last_state = state
            last_timecode = timecode

        if display is not None:
            try:
                display.render_vfd(
                    state=snapshot["state"],
                    timecode=snapshot["timecode"],
                    title=snapshot["title"],
                    volume=last_volume,
                    tick=tick,
                )
            except Exception as exc:
                log(f"SSD1309 render failed: {exc}")
                try:
                    display.close()
                except Exception:
                    pass
                display = None

        tick += 1

        if monitor.waitForAbort(0.1):
            break

    if gpio_reader is not None:
        gpio_reader.close()
    if display is not None:
        display.close()

    log("Service stopped")


if __name__ == "__main__":
    run()
