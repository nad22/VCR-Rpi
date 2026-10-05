import json
import os
import queue
import random
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"}
IDLE_LABEL = "TV - ORF1"
ADDON = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
MEDIA_DIR = os.path.join(ADDON_PATH, "resources", "media")
STATE_DIR = xbmcvfs.translatePath("special://profile/addon_data/service.idlescreen")
IDLE_STATE_FILE = os.path.join(STATE_DIR, "idle_playback")
IDLE_TOGGLE_REQUEST = os.path.join(STATE_DIR, "toggle_idle")
SETTINGS_FILE = os.path.join(STATE_DIR, "idlescreen.json")


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[service.idlescreen] {message}", level)


def normalized_path(path):
    if not path:
        return ""
    return os.path.normcase(os.path.realpath(path))


def set_idle_state(active):
    try:
        if active:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(IDLE_STATE_FILE, "w", encoding="utf-8") as state_file:
                state_file.write(str(time.time()))
        else:
            os.remove(IDLE_STATE_FILE)
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"Could not update idle playback marker: {exc}", xbmc.LOGWARNING)


def find_videos():
    videos = []
    if not os.path.isdir(MEDIA_DIR):
        return videos

    for root, _, files in os.walk(MEDIA_DIR):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS:
                videos.append(os.path.join(root, filename))
    return sorted(videos)


class IdlePlayer(xbmc.Player):
    def __init__(self, idle_paths):
        super().__init__()
        self.events = queue.Queue()
        self.last_file = ""
        self.idle_paths = idle_paths
        self.intentional_stop = False

    def onAVStarted(self):
        path = self.getPlayingFile()
        if path:
            self.last_file = path
        self.events.put(("started", path or self.last_file))

    def onPlayBackEnded(self):
        try:
            path = self.getPlayingFile()
        except RuntimeError:
            path = ""
        path = path or self.last_file
        self.events.put(("ended", path))

    def onPlayBackStopped(self):
        try:
            path = self.getPlayingFile()
        except RuntimeError:
            path = ""
        path = path or self.last_file
        normalized = normalized_path(path)
        if self.intentional_stop:
            self.intentional_stop = False
            self.events.put(("stopped", path))
            return
        if normalized in self.idle_paths:
            log(f"Treating idle stop as video end and continuing: {os.path.basename(path)}")
            self.events.put(("ended", path))
        else:
            self.events.put(("stopped", path))


def load_random_start_settings():
    """Return (enabled, min_duration_sec, end_margin_sec); re-read on every video start."""
    cfg = {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as settings_file:
            loaded = json.load(settings_file)
        cfg = loaded.get("random_start", {}) if isinstance(loaded, dict) else {}
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"Could not read {SETTINGS_FILE}: {exc}; using defaults", xbmc.LOGWARNING)
    if not isinstance(cfg, dict):
        cfg = {}

    try:
        min_sec = max(0.0, float(cfg.get("min_duration_minutes", 3))) * 60.0
        margin = max(0.0, float(cfg.get("end_margin_sec", 60)))
    except (TypeError, ValueError):
        min_sec, margin = 180.0, 60.0
    return bool(cfg.get("enabled", True)), min_sec, margin


def seek_to_random_position(player):
    enabled, min_sec, margin = load_random_start_settings()
    if not enabled:
        return False

    try:
        total = float(player.getTotalTime())
    except (RuntimeError, TypeError, ValueError):
        return False
    if total <= 0 or total <= min_sec:
        return False

    latest = total - margin
    if latest <= 0:
        return False

    target = random.uniform(0.0, latest)
    player.seekTime(target)
    log(f"Idle video is {total / 60.0:.1f} min long; random start at {target / 60.0:.1f} min")
    return True


def play_random_video(player, videos, deck, previous=""):
    if not videos:
        return ""

    if not deck:
        deck.extend(videos)
        random.shuffle(deck)
        if len(deck) > 1 and normalized_path(deck[-1]) == normalized_path(previous):
            deck[0], deck[-1] = deck[-1], deck[0]

    selected = deck.pop()
    log(f"Starting idle video: {os.path.basename(selected)}")
    set_idle_state(True)
    player.play(selected, listitem=xbmcgui.ListItem(label=IDLE_LABEL))
    return selected


def run():
    monitor = xbmc.Monitor()
    videos = find_videos()
    idle_paths = {normalized_path(path) for path in videos}
    player = IdlePlayer(idle_paths)
    set_idle_state(False)

    if not videos:
        log(f"No videos found in {MEDIA_DIR}; add video files to enable the idle loop", xbmc.LOGWARNING)
        while not monitor.abortRequested():
            if monitor.waitForAbort(5):
                break
        return

    log(f"Found {len(videos)} idle video(s)")
    if monitor.waitForAbort(2):
        return

    automation_enabled = not player.isPlaying()
    external_playback_active = not automation_enabled
    current_idle = ""
    idle_playback_confirmed = False
    previous_idle = ""
    next_idle_at = 0.0
    stop_deadline = 0.0
    playback_start_deadline = 0.0
    next_marker_refresh = time.monotonic() + 5.0
    random_deck = []

    if automation_enabled:
        current_idle = play_random_video(player, videos, random_deck)
        playback_start_deadline = time.monotonic() + 10.0

    while not monitor.abortRequested():
        now = time.monotonic()

        try:
            while True:
                event, path = player.events.get_nowait()
                normalized = normalized_path(path)

                if event == "started":
                    stop_deadline = 0.0
                    playback_start_deadline = 0.0
                    if normalized in idle_paths:
                        current_idle = path
                        idle_playback_confirmed = True
                        seek_to_random_position(player)
                    else:
                        current_idle = ""
                        idle_playback_confirmed = False
                        automation_enabled = False
                        external_playback_active = True
                        set_idle_state(False)
                        log("External video playback detected; idle loop suspended")

                elif event == "ended" and normalized in idle_paths:
                    previous_idle = path
                    current_idle = ""
                    idle_playback_confirmed = False
                    next_idle_at = now

                elif event == "stopped" and normalized in idle_paths:
                    current_idle = ""
                    idle_playback_confirmed = False
                    automation_enabled = False
                    external_playback_active = False
                    next_idle_at = 0.0
                    set_idle_state(False)
                    stop_deadline = now + 0.5

                elif event in ("ended", "stopped") and external_playback_active:
                    external_playback_active = False
                    automation_enabled = True
                    next_idle_at = now + 0.5
                    log("External playback ended; resuming idle loop")

        except queue.Empty:
            pass

        if current_idle and player.isPlaying():
            idle_playback_confirmed = True

        if current_idle and idle_playback_confirmed and not player.isPlaying():
            previous_idle = current_idle
            current_idle = ""
            idle_playback_confirmed = False
            automation_enabled = True
            external_playback_active = False
            next_idle_at = now
            set_idle_state(False)
            log("Idle playback ended without callback; continuing with next video")

        if os.path.exists(IDLE_TOGGLE_REQUEST):
            try:
                os.remove(IDLE_TOGGLE_REQUEST)
            except OSError as exc:
                log(f"Could not clear toggle request: {exc}", xbmc.LOGWARNING)
            else:
                playing_path = normalized_path(player.getPlayingFile()) if player.isPlaying() else ""
                idle_is_playing = playing_path in idle_paths or (
                    bool(current_idle) and player.isPlaying()
                )
                if idle_is_playing:
                    automation_enabled = False
                    external_playback_active = False
                    current_idle = ""
                    idle_playback_confirmed = False
                    next_idle_at = 0.0
                    set_idle_state(False)
                    stop_deadline = now + 0.5
                    player.intentional_stop = True
                    player.stop()
                    log("IdleScreen toggled off; returning to Kodi home")
                else:
                    automation_enabled = True
                    external_playback_active = False
                    stop_deadline = 0.0
                    next_idle_at = 0.0
                    idle_playback_confirmed = False
                    current_idle = play_random_video(player, videos, random_deck, previous_idle)
                    playback_start_deadline = now + 10.0 if current_idle else 0.0
                    log("IdleScreen toggled on by RESET button")

        if player.isPlaying():
            playing_path = normalized_path(player.getPlayingFile())
            if current_idle and playing_path and playing_path not in idle_paths:
                current_idle = ""
                automation_enabled = False
                external_playback_active = True
                set_idle_state(False)
                log("External playback detected by current-file check; idle loop suspended")

        if external_playback_active and not player.isPlaying():
            external_playback_active = False
            automation_enabled = True
            next_idle_at = now + 0.5
            log("External playback no longer active; resuming idle loop")

        if (
            automation_enabled
            and current_idle
            and not idle_playback_confirmed
            and playback_start_deadline
            and now >= playback_start_deadline
            and not player.isPlaying()
        ):
            log(f"Idle video did not start: {os.path.basename(current_idle)}; trying another")
            previous_idle = current_idle
            current_idle = ""
            playback_start_deadline = 0.0
            next_idle_at = now

        if (
            current_idle
            and player.isPlaying()
            and normalized_path(player.getPlayingFile()) in idle_paths
            and now >= next_marker_refresh
        ):
            set_idle_state(True)
            next_marker_refresh = now + 5.0

        if stop_deadline and now >= stop_deadline:
            stop_deadline = 0.0
            if not player.isPlaying():
                automation_enabled = False
                next_idle_at = 0.0
                set_idle_state(False)
                log("Idle video stopped; returning to Kodi home")
                xbmc.executebuiltin("ActivateWindow(home)")

        if automation_enabled and next_idle_at and now >= next_idle_at:
            if not player.isPlaying():
                next_idle_at = 0.0
                current_idle = play_random_video(player, videos, random_deck, previous_idle)
                playback_start_deadline = now + 10.0 if current_idle else 0.0
            else:
                next_idle_at = now + 0.5

        if monitor.waitForAbort(0.1):
            break

    set_idle_state(False)
    log("Idle screen service stopped")


if __name__ == "__main__":
    run()