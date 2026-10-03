import array
import io
import os
import shutil
import subprocess
import sys
import threading
import wave


def _parse_volume(value, default=100.0):
    try:
        return max(0.0, min(200.0, float(value)))
    except (TypeError, ValueError):
        return default


def _scale_wav(path, gain):
    """Return WAV bytes with 16-bit samples scaled by gain, or None for other formats."""
    with wave.open(path, "rb") as src:
        if src.getsampwidth() != 2:
            return None
        channels, rate = src.getnchannels(), src.getframerate()
        samples = array.array("h")
        samples.frombytes(src.readframes(src.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()
    scaled = array.array("h", (max(-32768, min(32767, int(s * gain))) for s in samples))
    if sys.byteorder == "big":
        scaled.byteswap()
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(scaled.tobytes())
    return out.getvalue()


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
        self.volume = _parse_volume(cfg.get("volume", 100))
        self.volumes = {
            str(name).lower(): _parse_volume(value, self.volume)
            for name, value in (cfg.get("volumes") or {}).items()
        }
        self.aplay = shutil.which("aplay")
        self._proc = None
        self._warned = set()
        self._scaled = {}

        if self.aplay is None:
            self.log("Sound effects disabled: aplay not found")
        else:
            self.log(
                f"Sound effects ready: device={self.device}, volume={self.volume:g}%, "
                f"events={sorted(self.events)}"
            )
            threading.Thread(target=self._warm_up, daemon=True).start()

    def _volume_for(self, event):
        return self.volumes.get(event, self.volume)

    def _path_for(self, event):
        filename = self.events.get(event)
        return os.path.join(self.sounds_dir, os.path.basename(filename)) if filename else None

    def _scaled_data(self, event, path):
        volume = self._volume_for(event)
        try:
            key = (path, os.path.getmtime(path), volume)
        except OSError:
            return None
        if key not in self._scaled:
            try:
                self._scaled[key] = _scale_wav(path, volume / 100.0)
            except Exception as exc:
                self._scaled[key] = None
                self._warn_once(f"scale:{event}", f"Sound '{event}' volume scaling failed ({exc}); playing unscaled")
            else:
                if self._scaled[key] is None:
                    self._warn_once(f"fmt:{event}", f"Sound '{event}' is not 16-bit PCM; volume setting ignored")
        return self._scaled[key]

    def _warm_up(self):
        for event in self.events:
            path = self._path_for(event)
            if self._volume_for(event) not in (0.0, 100.0) and path and os.path.isfile(path):
                self._scaled_data(event, path)

    def _warn_once(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self.log(message)

    def _watch(self, proc, event, data=None):
        _, stderr = proc.communicate(input=data)
        # Negative return code means we terminated it for a newer sound.
        if proc.returncode > 0:
            detail = (stderr or b"").decode("utf-8", "replace").strip()
            self._warn_once(f"fail:{event}", f"Sound '{event}' failed (aplay rc={proc.returncode}): {detail}")

    def play(self, event):
        event = str(event).lower()
        path = self._path_for(event)
        if not path or self.aplay is None or self._volume_for(event) <= 0:
            return False

        if not os.path.isfile(path):
            self._warn_once(f"missing:{event}", f"Sound '{event}' file not found: {path}")
            return False

        data = self._scaled_data(event, path) if self._volume_for(event) != 100.0 else None

        self.stop()
        try:
            self._proc = subprocess.Popen(
                [self.aplay, "-q", "-D", self.device, path if data is None else "-"],
                stdin=subprocess.DEVNULL if data is None else subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            self._warn_once(f"spawn:{event}", f"Sound '{event}' could not start: {exc}")
            return False

        threading.Thread(target=self._watch, args=(self._proc, event, data), daemon=True).start()
        self.log(f"Sound '{event}' started: {os.path.basename(path)} at {self._volume_for(event):g}%")
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
