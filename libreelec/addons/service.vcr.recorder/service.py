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
from lib.ads1115_levels import ADS1115LevelReader
from lib.bluetooth_remote import BluetoothRemoteReader
from lib.servo_controller import ServoController


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
DATA_DIR = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}")
RAM_AUDIO_LEVELS_FILE = f"/dev/shm/{ADDON_ID}/audio_levels.json"
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


def _read_external_audio_levels(path, max_age_sec=0.7):
    try:
        st = os.stat(path)
        age = time.time() - st.st_mtime
        if age > max_age_sec:
            return None

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        left = int(payload.get("left", payload.get("l", -1)))
        right = int(payload.get("right", payload.get("r", -1)))
        if left < 0 or right < 0:
            return None

        return {
            "left": max(0, min(100, left)),
            "right": max(0, min(100, right)),
        }
    except Exception:
        return None


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

        # Prefer the main SoC pin controller (pinctrl-bcm*) over auxiliary
        # expander chips (e.g. raspberrypi-exp-gpio), which also match a loose
        # "raspberry" substring check but only expose a handful of internal
        # lines unrelated to the physical header pins.
        def _match(predicate):
            for chip in chips:
                label = chip["label"].lower()
                if predicate(label) and 0 <= pin < chip["ngpio"]:
                    candidate = chip["base"] + pin
                    if self._is_valid_global_gpio(candidate, chips):
                        return candidate, chip["label"]
            return None, None

        candidate, chip_label = _match(lambda label: "pinctrl" in label)
        if candidate is None:
            candidate, chip_label = _match(lambda label: "bcm" in label or "raspberry" in label)

        if candidate is not None:
            log(f"GPIO pin mapping: BCM {pin} -> sysfs {candidate} ({chip_label})")
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
                log(f"GPIO edge pin={pin} pressed={pressed}")
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
    if mapping:
        pairs = ", ".join(f"{k}->{v}" for k, v in sorted(mapping.items()))
        log(f"GPIO button mapping loaded: {pairs}")
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


def dispatch_action(rpc, action, servo_controller=None):
    if action == "Player.PlayPause":
        rpc.play_pause()
    elif action == "Player.Play":
        # Compatibility: treat dedicated PLAY button as toggle on this remote.
        rpc.play_pause()
    elif action in ("Player.Stop", "Input.Stop"):
        # Try direct player stop first, then global stop action as fallback.
        rpc.stop()
        rpc.execute_action("stop")
    elif action in ("Player.SeekStart", "Player.GoStart", "goStart"):
        rpc.seek_to_start()
    elif action == "Player.GoNext":
        rpc.goto_next()
    elif action == "Player.GoPrevious":
        rpc.goto_previous()
    elif action == "Input.FastForward":
        rpc.execute_action("fastforward")
    elif action == "Input.Rewind":
        rpc.execute_action("rewind")
    elif action == "Input.Up":
        rpc.execute_action("up")
    elif action == "Input.Down":
        rpc.execute_action("down")
    elif action == "Input.Left":
        rpc.execute_action("left")
    elif action == "Input.Right":
        rpc.execute_action("right")
    elif action == "Input.Select":
        rpc.execute_action("select")
    elif action == "Input.Back":
        rpc.execute_action("back")
    elif action == "Player.ChapterNext":
        rpc.execute_action("nextchapter")
    elif action == "Player.ChapterPrevious":
        rpc.execute_action("previouschapter")
    elif action == "Servo.Eject":
        if servo_controller is not None:
            servo_controller.trigger_eject()
        else:
            log("Servo.Eject requested but no servo controller is active")
    elif action == "Servo.Load":
        if servo_controller is not None:
            servo_controller.trigger_load()
        else:
            log("Servo.Load requested but no servo controller is active")
    else:
        log(f"Unknown action mapping: {action}")


def resolve_builtin_action(event_upper):
    if event_upper == "STOP":
        return "Player.Stop"
    if event_upper == "PLAY":
        return "Player.PlayPause"
    if event_upper == "PLAY_PAUSE":
        return "Player.PlayPause"
    if event_upper == "FF":
        return "Input.FastForward"
    if event_upper == "RW":
        return "Input.Rewind"
    if event_upper == "NEXT":
        return "Player.GoNext"
    if event_upper == "PREV":
        return "Player.GoPrevious"
    if event_upper in ("GO_START", "GOSTART", "START"):
        return "Player.GoStart"
    if event_upper == "UP":
        return "Input.Up"
    if event_upper == "DOWN":
        return "Input.Down"
    if event_upper == "LEFT":
        return "Input.Left"
    if event_upper == "RIGHT":
        return "Input.Right"
    if event_upper == "OK":
        return "Input.Select"
    if event_upper == "BACK":
        return "Input.Back"
    if event_upper == "CHAPTER_NEXT":
        return "Player.ChapterNext"
    if event_upper == "CHAPTER_PREV":
        return "Player.ChapterPrevious"
    if event_upper == "EJECT":
        return "Servo.Eject"
    if event_upper == "LOAD":
        return "Servo.Load"
    return None


def run():
    monitor = xbmc.Monitor()
    rpc = KodiRpc()
    gpio_reader = None
    display = None
    ads_reader = None
    bt_reader = None

    buttons_cfg = {"buttons": []}
    button_map = {}
    next_cfg_reload = 0.0
    last_buttons_cfg_raw = ""
    last_display_cfg_raw = ""
    last_servos_cfg_raw = ""
    servo_controller = None

    last_state = ""
    last_timecode = ""
    last_volume = 0
    last_audio_left = 0
    last_audio_right = 0
    audio_source = "kodi"
    audio_levels_file = RAM_AUDIO_LEVELS_FILE

    vu_poll_interval = 0.01
    next_volume_poll = 0.0
    tick = 0
    display_cfg = {}

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
                    "audio_source": "kodi",
                    "audio_levels_file": RAM_AUDIO_LEVELS_FILE,
                    "ads1115": {
                        "bus": "auto",
                        "address": "0x48",
                        "channel_left": 0,
                        "channel_right": 1,
                        "gain": "4.096",
                        "sps": 860,
                        "bias": 16384,
                        "full_scale_delta": 6,
                        "noise_floor": 1,
                        "samples_per_read": 2,
                        "baseline_alpha": 0.10,
                    },
                    "invert": False,
                    "rotate180": False,
                },
            )

            audio_source = str(display_cfg.get("audio_source", "auto")).lower()
            audio_file_value = display_cfg.get("audio_levels_file", RAM_AUDIO_LEVELS_FILE)
            if isinstance(audio_file_value, str) and audio_file_value.startswith("/"):
                audio_levels_file = audio_file_value
            else:
                audio_levels_file = os.path.join(DATA_DIR, str(audio_file_value))
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

            servos_cfg = load_json("servos.json", {"enabled": False})
            servos_cfg_raw = json.dumps(servos_cfg, sort_keys=True)
            if servos_cfg_raw != last_servos_cfg_raw:
                if servo_controller is not None:
                    servo_controller.close()
                    servo_controller = None
                if bool(servos_cfg.get("enabled", False)):
                    try:
                        servo_controller = ServoController(servos_cfg, log_fn=log)
                        log("Servo controller initialized")
                    except Exception as exc:
                        servo_controller = None
                        log(f"Servo controller init failed: {exc}")
                last_servos_cfg_raw = servos_cfg_raw

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

                if ads_reader is not None:
                    ads_reader.close()
                    ads_reader = None
                if audio_source == "ads1115":
                    try:
                        adc_cfg = display_cfg.get("ads1115", {})
                        ads_reader = ADS1115LevelReader(
                            bus=adc_cfg.get("bus", "auto"),
                            address=adc_cfg.get("address", "0x48"),
                            channel_left=adc_cfg.get("channel_left", 0),
                            channel_right=adc_cfg.get("channel_right", 1),
                            gain=adc_cfg.get("gain", "4.096"),
                            sps=adc_cfg.get("sps", 860),
                            bias=adc_cfg.get("bias", 16384),
                            full_scale_delta=adc_cfg.get("full_scale_delta", 6),
                            noise_floor=adc_cfg.get("noise_floor", 1),
                            samples_per_read=adc_cfg.get("samples_per_read", 2),
                            baseline_alpha=adc_cfg.get("baseline_alpha", 0.10),
                        )
                        log(
                            "ADS1115 audio source active: "
                            f"dev={getattr(ads_reader, '_resolved_dev', 'unknown')} "
                            f"addr={adc_cfg.get('address', '0x48')}"
                        )
                    except Exception as exc:
                        ads_reader = None
                        log(f"ADS1115 init failed: {exc}")

                last_display_cfg_raw = display_cfg_raw

        if gpio_reader is not None:
            events = gpio_reader.read_events()
            for event in events:
                event_upper = str(event).upper()
                action = button_map.get(event_upper)
                if action is None:
                    action = resolve_builtin_action(event_upper)
                if action:
                    dispatch_action(rpc, action, servo_controller=servo_controller)
                    log(f"GPIO event {event_upper} -> {action}")
                else:
                    log(f"GPIO event {event_upper} has no action mapping")

        if bt_reader is None:
            try:
                bt_cfg = display_cfg.get("bluetooth_remote", {}) if isinstance(display_cfg, dict) else {}
                bt_name = str(bt_cfg.get("device_name", "VCR_REMOTE")).strip() or "VCR_REMOTE"
                bt_addr = str(bt_cfg.get("device_addr", "")).strip() or os.environ.get("VCR_REMOTE_ADDR")
                bt_channels = bt_cfg.get("rfcomm_channels")
                if bt_channels is None:
                    bt_channels = [int(bt_cfg.get("rfcomm_channel", 1))]
                bt_reader = BluetoothRemoteReader(
                    device_name=bt_name,
                    device_addr=bt_addr,
                    rfcomm_channels=bt_channels,
                )
                if bt_reader.connect():
                    log(
                        "Bluetooth remote connected "
                        f"name={bt_name} addr={bt_reader.device_addr} "
                        f"channel={bt_reader.connected_channel}"
                    )
                else:
                    bt_reader = None
            except Exception as exc:
                log(f"Bluetooth remote init failed: {exc}")
                bt_reader = None

        if bt_reader is not None:
            try:
                events = bt_reader.read_events()
                for event_str in events:
                    event_str = str(event_str).strip().upper()
                    if not event_str:
                        continue

                    if event_str.startswith("SEEK:"):
                        seek_str = event_str[5:]
                        try:
                            seek_seconds = int(float(seek_str))
                            seek_ok = rpc.seek_relative(seek_seconds)
                            if seek_ok:
                                log(f"BT event SEEK {seek_seconds:+d}s")
                            else:
                                log(f"BT event SEEK rejected {seek_seconds:+d}s")
                        except ValueError:
                            log(f"BT event invalid SEEK value: {seek_str}")
                    else:
                        action = button_map.get(event_str)
                        if action is None:
                            action = resolve_builtin_action(event_str)

                        if action:
                            dispatch_action(rpc, action, servo_controller=servo_controller)
                            log(f"BT event {event_str} -> {action}")
                        else:
                            log(f"BT event {event_str} has no action mapping")
            except Exception as exc:
                log(f"Bluetooth event read failed: {exc}")
                if bt_reader:
                    try:
                        bt_reader.close()
                    except Exception:
                        pass
                    bt_reader = None

        snapshot = rpc.get_playback_snapshot()
        if now >= next_volume_poll:
            try:
                levels = None
                if audio_source == "ads1115" and ads_reader is not None:
                    levels = ads_reader.read_levels()
                elif audio_source in ("auto", "external"):
                    levels = _read_external_audio_levels(audio_levels_file)

                if levels is not None:
                    last_audio_left = levels["left"]
                    last_audio_right = levels["right"]
                    last_volume = int((last_audio_left + last_audio_right) / 2)
                elif audio_source in ("auto", "kodi"):
                    last_volume = rpc.get_audio_level()
                    last_audio_left = last_volume
                    last_audio_right = last_volume
                else:
                    last_audio_left = 0
                    last_audio_right = 0
                    last_volume = 0
            except Exception as exc:
                log(f"Audio level poll failed: {exc}")
            next_volume_poll = now + vu_poll_interval

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
                    level_l=last_audio_left,
                    level_r=last_audio_right,
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

        if monitor.waitForAbort(vu_poll_interval):
            break

    if gpio_reader is not None:
        gpio_reader.close()
    if ads_reader is not None:
        ads_reader.close()
    if display is not None:
        display.close()
    if servo_controller is not None:
        servo_controller.close()

    log("Service stopped")


if __name__ == "__main__":
    run()
