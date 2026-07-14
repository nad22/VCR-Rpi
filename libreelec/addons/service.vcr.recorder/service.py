import json
import os
import time

import xbmc
import xbmcaddon

from lib.kodi_rpc import KodiRpc


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
DATA_DIR = xbmc.translatePath(f"special://profile/addon_data/{ADDON_ID}")


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

    def _export_pin(self, pin):
        gpio_dir = self._gpio_dir(pin)
        if not os.path.isdir(gpio_dir):
            _write_text(os.path.join(self.SYSFS_GPIO_DIR, "export"), pin)

    def _setup_pin(self, btn):
        pin = int(btn["pin"])
        self._export_pin(pin)
        _write_text(self._gpio_file(pin, "direction"), "in")

        active_low = "1" if bool(btn.get("active_low", True)) else "0"
        active_low_file = self._gpio_file(pin, "active_low")
        if os.path.exists(active_low_file):
            _write_text(active_low_file, active_low)

        value = _read_text(self._gpio_file(pin, "value"), "1")
        pressed = value == "0" if bool(btn.get("active_low", True)) else value == "1"
        self.states[pin] = {"pressed": pressed, "last_event_at": 0.0}

    def setup(self):
        try:
            for btn in self.buttons:
                self._setup_pin(btn)
            self.initialized = True
            log(f"GPIO input active for {len(self.buttons)} buttons")
            return True
        except Exception as exc:
            self.initialized = False
            log(f"GPIO setup failed: {exc}")
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

    buttons_cfg = {"buttons": []}
    button_map = {}
    next_cfg_reload = 0
    last_buttons_cfg_raw = ""

    last_state = ""
    last_timecode = ""
    log("Service started")

    while not monitor.abortRequested():
        now = time.monotonic()
        if now >= next_cfg_reload:
            buttons_cfg = load_json("buttons.json", {"buttons": []})
            button_map = build_button_mapping(buttons_cfg)
            next_cfg_reload = now + 5

            cfg_raw = json.dumps(buttons_cfg, sort_keys=True)
            if cfg_raw != last_buttons_cfg_raw:
                gpio_buttons = build_gpio_buttons(buttons_cfg)
                if gpio_reader is not None:
                    gpio_reader.close()
                    gpio_reader = None
                if gpio_buttons:
                    reader = GpioButtonReader(gpio_buttons)
                    if reader.setup():
                        gpio_reader = reader
                last_buttons_cfg_raw = cfg_raw

        if gpio_reader is not None:
            events = gpio_reader.read_events()
            for event in events:
                action = button_map.get(event)
                if action:
                    dispatch_action(rpc, action)
                    log(f"GPIO event {event} -> {action}")

        snapshot = rpc.get_playback_snapshot()
        state = snapshot["state"]
        timecode = snapshot["timecode"]
        if state != last_state or timecode != last_timecode:
            log(f"Playback {state} {timecode} {snapshot['title']}")
            last_state = state
            last_timecode = timecode

        if monitor.waitForAbort(0.1):
            break

    if gpio_reader is not None:
        gpio_reader.close()

    log("Service stopped")


if __name__ == "__main__":
    run()
