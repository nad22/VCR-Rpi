import os
import shutil
import subprocess
import threading


class SoundEffectPlayer:
    """Plays short WAV files on a dedicated ALSA device (e.g. MAX98357A I2S amp)
    via a detached aplay process, independent of Kodi's own player."""

    def __init__(self, cfg=None, sounds_dir="", log_fn=None):
        cfg = cfg or {}
        self.log = log_fn or (lambda msg: None)
        self.device = str(cfg.get("device", "plughw:CARD=sndrpihifiberry,DEV=0"))
        self.sounds_dir = sounds_dir
        self.events = {
            str(name).lower(): str(filename)
            for name, filename in (cfg.get("events") or {}).items()
            if filename
        }
        self.aplay = shutil.which("aplay")
        self._proc = None
        self._warned = set()

        if self.aplay is None:
            self.log("Sound effects disabled: aplay not found")
        else:
            self.log(f"Sound effects ready: device={self.device}, events={sorted(self.events)}")

    def _warn_once(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self.log(message)

    def _watch(self, proc, event):
        _, stderr = proc.communicate()
        # Negative return code means we terminated it for a newer sound.
        if proc.returncode > 0:
            detail = (stderr or b"").decode("utf-8", "replace").strip()
            self._warn_once(f"fail:{event}", f"Sound '{event}' failed (aplay rc={proc.returncode}): {detail}")

    def play(self, event):
        filename = self.events.get(str(event).lower())
        if not filename or self.aplay is None:
            return False

        path = os.path.join(self.sounds_dir, os.path.basename(filename))
        if not os.path.isfile(path):
            self._warn_once(f"missing:{event}", f"Sound '{event}' file not found: {path}")
            return False

        self.stop()
        try:
            self._proc = subprocess.Popen(
                [self.aplay, "-q", "-D", self.device, path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            self._warn_once(f"spawn:{event}", f"Sound '{event}' could not start: {exc}")
            return False

        threading.Thread(target=self._watch, args=(self._proc, event), daemon=True).start()
        return True

    def stop(self):
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def close(self):
        self.stop()
