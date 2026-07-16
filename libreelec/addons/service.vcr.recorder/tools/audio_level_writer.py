#!/usr/bin/env python3
"""
Writes real-time L/R peak levels (0-100) to JSON for service.vcr.recorder.

Default output: /dev/shm/service.vcr.recorder/audio_levels.json
Input source: ALSA capture via arecord (stereo, 16-bit, 48 kHz)

Requires on target:
- arecord (alsa-utils)
"""

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time


def rms_to_percent(samples):
    if not samples:
        return 0
    acc = 0.0
    for s in samples:
        v = s / 32768.0
        acc += v * v
    rms = math.sqrt(acc / len(samples))
    return max(0, min(100, int(rms * 165)))


def _run_text(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0, check=False)
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception:
        pass
    return ""


def _detect_pulse_monitor_source():
    if not shutil.which("pactl"):
        return None

    sink = _run_text(["pactl", "get-default-sink"])
    if sink and sink != "auto_null":
        monitor = sink + ".monitor"
        sources = _run_text(["pactl", "list", "short", "sources"])
        if monitor and monitor in sources:
            return monitor

    sources = _run_text(["pactl", "list", "short", "sources"])
    for line in sources.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1]
            if ".monitor" in name and "auto_null.monitor" not in name:
                return name

    # Fallback: any non-null source (for capture cards/mics).
    for line in sources.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1]
            if "auto_null" not in name:
                return name
    return None


def _choose_capture_cmd(device):
    req = (device or "auto").strip()

    if shutil.which("arecord"):
        alsa_dev = "default" if req == "auto" else req
        return [
            "arecord",
            "-q",
            "-D",
            alsa_dev,
            "-f",
            "S16_LE",
            "-c",
            "2",
            "-r",
            "48000",
            "-t",
            "raw",
        ], f"arecord:{alsa_dev}"

    if shutil.which("ffmpeg"):
        alsa_dev = "default" if req == "auto" else req
        return [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "alsa",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-i",
            alsa_dev,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ], f"ffmpeg:{alsa_dev}"

    if shutil.which("parec"):
        pulse_dev = req
        if req == "auto":
            pulse_dev = _detect_pulse_monitor_source()
            if not pulse_dev:
                return None, None
        return [
            "parec",
            "--device",
            pulse_dev,
            "--format=s16le",
            "--rate=48000",
            "--channels=2",
            "--raw",
        ], f"parec:{pulse_dev}"

    return None, None


def _write_levels(path, left, right, note=None):
    payload = {
        "ts": time.time(),
        "left": max(0, min(100, int(left))),
        "right": max(0, min(100, int(right))),
    }
    if note:
        payload["note"] = note

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="auto", help="Capture device/source (default: auto)")
    parser.add_argument(
        "--output",
        default="/dev/shm/service.vcr.recorder/audio_levels.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    chunk_frames = 1024
    chunk_bytes = chunk_frames * 2 * 2  # frames * channels * int16

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    _write_levels(args.output, 0, 0, note="starting")

    while True:
        cmd, backend = _choose_capture_cmd(args.device)
        if not cmd:
            note = "no real capture source (arecord/ffmpeg/parec or pulse source missing)"
            _write_levels(args.output, 0, 0, note=note)
            print(f"audio_level_writer: {note}", file=sys.stderr)
            time.sleep(5)
            continue

        print(f"audio_level_writer: using backend {backend}", file=sys.stderr)
        _write_levels(args.output, 0, 0, note=f"backend={backend} waiting for audio")
        proc = None
        last_write = time.time()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while True:
                raw = proc.stdout.read(chunk_bytes)
                if not raw:
                    time.sleep(0.02)
                    now = time.time()
                    if (now - last_write) > 0.5:
                        _write_levels(args.output, 0, 0, note=f"backend={backend} no audio yet")
                        last_write = now
                    if proc.poll() is not None:
                        break
                    continue

                vals = struct.unpack("<" + "h" * (len(raw) // 2), raw)
                left = vals[0::2]
                right = vals[1::2]
                _write_levels(args.output, rms_to_percent(left), rms_to_percent(right), note=backend)
                last_write = time.time()
        except Exception as exc:
            _write_levels(args.output, 0, 0, note=f"capture error: {exc}")
            print(f"audio_level_writer: backend failed: {exc}", file=sys.stderr)
            time.sleep(1)
        finally:
            try:
                if proc is not None:
                    proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
