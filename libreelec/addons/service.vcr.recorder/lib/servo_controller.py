import errno
import glob
import os
import threading
import time


SYSFS_GPIO_DIR = "/sys/class/gpio"


def _read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return default


def _write_text(path, value):
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(value))


class _SysfsOutputPin:
    """Minimal sysfs GPIO output pin with BCM->global pin resolution."""

    def __init__(self, bcm_pin, log_fn=None):
        self.bcm_pin = int(bcm_pin)
        self.log = log_fn or (lambda msg: None)
        self._write_error_logged = False
        self.pin = self._resolve_sysfs_pin(self.bcm_pin)
        self._export_pin(self.pin)
        _write_text(self._gpio_file("direction"), "out")
        # Keep the value file open for the pin's lifetime. Re-opening/closing
        # a sysfs file on every single pulse edge (100+ times/sec) adds
        # syscall overhead that varies unpredictably and was the main source
        # of visible servo jitter/trembling.
        self._value_fh = open(self._gpio_file("value"), "w", encoding="utf-8")
        self.log(f"Servo GPIO{self.bcm_pin} (sysfs {self.pin}) ready as output")
        self.write(0)

    def _gpio_dir(self):
        return os.path.join(SYSFS_GPIO_DIR, f"gpio{self.pin}")

    def _gpio_file(self, name):
        return os.path.join(self._gpio_dir(), name)

    def _chip_infos(self):
        chips = []
        try:
            for name in os.listdir(SYSFS_GPIO_DIR):
                if not name.startswith("gpiochip"):
                    continue
                chip_dir = os.path.join(SYSFS_GPIO_DIR, name)
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
            self.log(f"Servo GPIO mapping: BCM {pin} -> sysfs {candidate} ({chip_label})")
            return candidate

        return pin

    def _export_pin(self, pin):
        gpio_dir = os.path.join(SYSFS_GPIO_DIR, f"gpio{pin}")
        if not os.path.isdir(gpio_dir):
            try:
                _write_text(os.path.join(SYSFS_GPIO_DIR, "export"), pin)
            except OSError as exc:
                if exc.errno != errno.EBUSY:
                    raise OSError(exc.errno, f"export failed for GPIO{pin}: {exc}")

            for _ in range(10):
                if os.path.isdir(gpio_dir):
                    break
                time.sleep(0.02)

            if not os.path.isdir(gpio_dir):
                raise OSError(errno.ENOENT, f"GPIO directory not created for pin {pin}")

    def write(self, level):
        try:
            self._value_fh.seek(0)
            self._value_fh.write("1" if level else "0")
            self._value_fh.flush()
        except Exception as exc:
            if not self._write_error_logged:
                self._write_error_logged = True
                self.log(f"Servo GPIO{self.bcm_pin}: write to value failed: {exc}")

    def release(self):
        try:
            self.write(0)
        except Exception:
            pass

    def close(self):
        try:
            self._value_fh.close()
        except Exception:
            pass


class _HardwarePwmPin:
    # Real Linux sysfs PWM channel (/sys/class/pwm/pwmchipN/pwmX).
    #
    # This drives the servo signal entirely in hardware/kernel space, so it
    # is immune to Python/GIL/OS-scheduling jitter that affects bit-banged
    # sysfs GPIO output. Requires the pwm overlay to be enabled on the Pi,
    # e.g. in /flash/config.txt:
    #   dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
    # (maps PWM0 -> GPIO12, PWM1 -> GPIO13) followed by a reboot.

    PWM_ROOT = "/sys/class/pwm"

    def __init__(self, chip, channel, period_ns, bcm_pin=None, log_fn=None):
        self.log = log_fn or (lambda msg: None)
        self.bcm_pin = bcm_pin
        self.chip = chip
        self.channel = int(channel)
        self.period_ns = int(period_ns)
        self._write_error_logged = False

        self.chip_dir = os.path.join(self.PWM_ROOT, chip)
        if not os.path.isdir(self.chip_dir):
            raise FileNotFoundError(
                f"{self.chip_dir} not found. Enable the pwm overlay in /flash/config.txt "
                "(e.g. dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4) and reboot."
            )

        self.channel_dir = os.path.join(self.chip_dir, f"pwm{self.channel}")
        self._export_channel()

        # duty_cycle must be <= period, so set period first while duty_cycle
        # is still at its post-export default of 0.
        _write_text(os.path.join(self.channel_dir, "duty_cycle"), 0)
        _write_text(os.path.join(self.channel_dir, "period"), self.period_ns)
        _write_text(os.path.join(self.channel_dir, "enable"), 1)
        # Keep the duty_cycle file open for the pin's lifetime. Re-opening it
        # on every ramp step (up to 50x/sec) adds syscall overhead that
        # varies unpredictably and caused choppy/jerky speed-ramped moves.
        self._duty_fh = open(os.path.join(self.channel_dir, "duty_cycle"), "w", encoding="utf-8")

    def _export_channel(self):
        if not os.path.isdir(self.channel_dir):
            try:
                _write_text(os.path.join(self.chip_dir, "export"), self.channel)
            except OSError as exc:
                if exc.errno != errno.EBUSY:
                    raise OSError(exc.errno, f"pwm export failed for {self.chip}/pwm{self.channel}: {exc}")

            for _ in range(25):
                if os.path.isdir(self.channel_dir):
                    break
                time.sleep(0.02)

            if not os.path.isdir(self.channel_dir):
                raise OSError(errno.ENOENT, f"{self.channel_dir} not created after export")

    def set_pulse_us(self, pulse_us):
        duty_ns = int(round(max(0.0, pulse_us) * 1000))
        duty_ns = max(0, min(self.period_ns, duty_ns))
        try:
            self._duty_fh.seek(0)
            self._duty_fh.write(str(duty_ns))
            self._duty_fh.flush()
        except Exception as exc:
            if not self._write_error_logged:
                self._write_error_logged = True
                self.log(f"Hardware PWM {self.chip}/pwm{self.channel}: duty_cycle write failed: {exc}")

    def release(self):
        self.set_pulse_us(0)

    def close(self):
        try:
            self._duty_fh.close()
        except Exception:
            pass
        try:
            _write_text(os.path.join(self.channel_dir, "enable"), 0)
        except Exception:
            pass


class ServoController:
    """Drives two hobby servos (e.g. SG90) from the Raspberry Pi GPIO via
    software PWM over sysfs. Servo 1 handles eject/load rotation, servo 2
    handles the front-flap door movement during eject.

    All timings are configurable through the constructor / config dict.
    """

    def __init__(self, cfg=None, log_fn=None):
        cfg = cfg or {}
        self.log = log_fn or (lambda msg: None)

        self.pulse_min_us = float(cfg.get("pulse_min_us", 500))
        self.pulse_max_us = float(cfg.get("pulse_max_us", 2400))
        self.angle_min = float(cfg.get("angle_min", 0))
        self.angle_max = float(cfg.get("angle_max", 180))
        self.frequency_hz = max(10, int(cfg.get("frequency_hz", 50)))
        self.move_settle_sec = max(0.0, float(cfg.get("move_settle_sec", 0.3)))
        self.release_after_move = bool(cfg.get("release_after_move", True))
        self.period_ns = int(round(1_000_000_000 / self.frequency_hz))
        self.pwm_chip = str(cfg.get("pwm_chip", "pwmchip0"))
        default_speed = cfg.get("speed_deg_per_sec")
        self.default_speed_deg_per_sec = float(default_speed) if default_speed else None

        servo1_cfg = cfg.get("servo1", {})
        servo2_cfg = cfg.get("servo2", {})
        eject_cfg = cfg.get("eject", {})
        load_cfg = cfg.get("load", {})

        self.servo1_pin = int(servo1_cfg.get("pin", 12))
        self.servo1_neutral_angle = float(servo1_cfg.get("neutral_angle", 90))
        self.servo1_eject_angle = float(servo1_cfg.get("eject_angle", 30))
        self.servo1_load_angle = float(servo1_cfg.get("load_angle", 150))
        self.servo1_pwm_channel = servo1_cfg.get("pwm_channel")
        self.servo1_speed_deg_per_sec = self._resolve_speed(servo1_cfg)
        self._servo1_current_angle = self.servo1_neutral_angle

        self.servo2_pin = int(servo2_cfg.get("pin", 13))
        self.servo2_closed_angle = float(servo2_cfg.get("closed_angle", 0))
        self.servo2_open_angle = float(servo2_cfg.get("open_angle", 90))
        self.servo2_pwm_channel = servo2_cfg.get("pwm_channel")
        self.servo2_speed_deg_per_sec = self._resolve_speed(servo2_cfg)
        self._servo2_current_angle = self.servo2_closed_angle

        self.eject_servo1_hold_sec = max(0.0, float(eject_cfg.get("servo1_hold_sec", 0.6)))
        self.eject_door_delay_sec = max(
            0.0,
            float(eject_cfg.get("door_delay_sec", eject_cfg.get("servo1_to_servo2_delay_sec", 0.4))),
        )
        self.eject_door_open_hold_sec = max(0.0, float(eject_cfg.get("door_open_hold_sec", 3.0)))

        self.load_servo1_hold_sec = max(0.0, float(load_cfg.get("servo1_hold_sec", 0.6)))

        self._servo1 = self._setup_pin(self.servo1_pin, "servo1", self.servo1_pwm_channel)
        self._servo2 = self._setup_pin(self.servo2_pin, "servo2", self.servo2_pwm_channel)

        self._lock = threading.Lock()
        self._busy = False

    def _resolve_speed(self, servo_cfg):
        speed = servo_cfg.get("speed_deg_per_sec", self.default_speed_deg_per_sec)
        return float(speed) if speed else None

    def _speed_for(self, pin):
        if pin is self._servo1:
            return self.servo1_speed_deg_per_sec
        if pin is self._servo2:
            return self.servo2_speed_deg_per_sec
        return self.default_speed_deg_per_sec

    def _setup_pin(self, bcm_pin, label, pwm_channel=None):
        if pwm_channel is not None:
            try:
                pin = _HardwarePwmPin(
                    self.pwm_chip, pwm_channel, self.period_ns, bcm_pin=bcm_pin, log_fn=self.log
                )
                self.log(
                    f"Servo {label} using HARDWARE PWM on GPIO{bcm_pin} "
                    f"({self.pwm_chip}/pwm{pwm_channel})"
                )
                return pin
            except Exception as exc:
                self.log(
                    f"Servo {label} hardware PWM setup failed ({exc}); "
                    "falling back to software (bit-banged) PWM"
                )
        try:
            pin = _SysfsOutputPin(bcm_pin, self.log)
            self.log(f"Servo {label} using software PWM on GPIO{bcm_pin}")
            return pin
        except Exception as exc:
            self.log(f"Servo {label} on GPIO{bcm_pin} setup FAILED: {exc}")
            return None

    def _angle_to_pulse_us(self, angle):
        angle = max(self.angle_min, min(self.angle_max, float(angle)))
        span_angle = max(1e-6, self.angle_max - self.angle_min)
        span_pulse = self.pulse_max_us - self.pulse_min_us
        ratio = (angle - self.angle_min) / span_angle
        return self.pulse_min_us + ratio * span_pulse

    def _pulse_for(self, pin, angle, duration_sec):
        pulse_us = self._angle_to_pulse_us(angle)
        period_sec = 1.0 / self.frequency_hz
        end_time = time.monotonic() + max(0.0, duration_sec)

        # Always send at least one pulse so short durations still move the servo.
        while True:
            cycle_start = time.monotonic()
            pin.write(1)
            time.sleep(pulse_us / 1_000_000.0)
            pin.write(0)

            if time.monotonic() >= end_time:
                break

            remaining = period_sec - (time.monotonic() - cycle_start)
            if remaining > 0:
                time.sleep(remaining)

    def _drive_angle(self, pin, angle, duration_sec):
        """Drive the pin to output the given angle for duration_sec."""
        if isinstance(pin, _HardwarePwmPin):
            pin.set_pulse_us(self._angle_to_pulse_us(angle))
            time.sleep(duration_sec)
        else:
            self._pulse_for(pin, angle, duration_sec)

    def _ramp_to_angle(self, pin, from_angle, to_angle, speed_deg_per_sec):
        """Move from from_angle to to_angle, returning the time spent moving.

        If speed_deg_per_sec is None/<=0 (default), jump directly to the
        target and just settle for move_settle_sec, as before. Otherwise
        interpolate in small steps so the whole movement takes
        distance/speed_deg_per_sec seconds.
        """
        distance = abs(to_angle - from_angle)
        if speed_deg_per_sec and speed_deg_per_sec > 0 and distance > 0.5:
            duration = distance / speed_deg_per_sec
            step_dt = 0.02
            steps = max(1, int(round(duration / step_dt)))
            for i in range(1, steps + 1):
                step_angle = from_angle + (to_angle - from_angle) * (i / steps)
                self._drive_angle(pin, step_angle, step_dt)
            self._drive_angle(pin, to_angle, self.move_settle_sec)
            return steps * step_dt + self.move_settle_sec

        self._drive_angle(pin, to_angle, self.move_settle_sec)
        return self.move_settle_sec

    def _move(self, pin, angle, hold_sec, track_attr):
        if pin is None:
            self.log(f"Servo move skipped: pin not initialized (angle={angle})")
            return

        from_angle = getattr(self, track_attr, angle)
        speed = self._speed_for(pin)
        speed_desc = f"{speed:g}deg/s" if speed else "max"
        self.log(
            f"Servo GPIO{pin.bcm_pin} -> angle={angle} (from {from_angle}) "
            f"hold={hold_sec:.2f}s speed={speed_desc}"
        )

        move_duration = self._ramp_to_angle(pin, from_angle, angle, speed)
        setattr(self, track_attr, angle)

        if self.release_after_move:
            pin.release()

        remaining = hold_sec - move_duration
        if remaining > 0:
            time.sleep(remaining)

    def _move_and_hold(self, pin, angle, track_attr):
        """Move to angle and keep driving that position indefinitely (no
        release, no return move). Used for servo1's eject/load rotation,
        which should simply stay at whichever end position it last reached.
        """
        if pin is None:
            self.log(f"Servo move skipped: pin not initialized (angle={angle})")
            return

        from_angle = getattr(self, track_attr, angle)
        speed = self._speed_for(pin)
        speed_desc = f"{speed:g}deg/s" if speed else "max"
        self.log(
            f"Servo GPIO{pin.bcm_pin} -> angle={angle} (from {from_angle}) "
            f"speed={speed_desc}, holding position"
        )

        self._ramp_to_angle(pin, from_angle, angle, speed)
        setattr(self, track_attr, angle)
        # Intentionally do not release: keep driving the signal so the servo
        # holds torque at the target end position.

    def _run_eject_sequence(self):
        servo1_thread = None
        try:
            self.log("Servo eject sequence started")

            # Start servo1's eject move in parallel with the door: the
            # cassette must not hit the still-closed door, so the door needs
            # to be opening (or already open) by the time servo1 pushes the
            # cassette out. eject_door_delay_sec controls how long after the
            # eject sequence starts the door begins opening.
            servo1_thread = threading.Thread(
                target=self._move_and_hold,
                args=(self._servo1, self.servo1_eject_angle, "_servo1_current_angle"),
                daemon=True,
            )
            servo1_thread.start()

            if self.eject_door_delay_sec > 0:
                time.sleep(self.eject_door_delay_sec)

            self._move(self._servo2, self.servo2_open_angle, self.eject_door_open_hold_sec, "_servo2_current_angle")
            self._move(self._servo2, self.servo2_closed_angle, self.move_settle_sec, "_servo2_current_angle")

            servo1_thread.join()
            self.log("Servo eject sequence finished")
        except Exception as exc:
            self.log(f"Servo eject sequence failed: {exc}")
        finally:
            if servo1_thread is not None:
                servo1_thread.join()
            with self._lock:
                self._busy = False

    def _run_load_sequence(self):
        try:
            self.log("Servo load sequence started")
            self._move_and_hold(self._servo1, self.servo1_load_angle, "_servo1_current_angle")
            self.log("Servo load sequence finished")
        except Exception as exc:
            self.log(f"Servo load sequence failed: {exc}")
        finally:
            with self._lock:
                self._busy = False

    def _start_sequence(self, target):
        with self._lock:
            if self._busy:
                self.log("Servo sequence ignored: another sequence is already running")
                return False
            self._busy = True

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return True

    def trigger_eject(self):
        """Servo 1 triggers the eject mechanism, then servo 2 opens the
        front-flap door and closes it again after door_open_hold_sec."""
        return self._start_sequence(self._run_eject_sequence)

    def trigger_load(self):
        """Servo 1 pulls the cassette in; servo 2 is not touched."""
        return self._start_sequence(self._run_load_sequence)

    def close(self):
        try:
            self._servo1.release()
        except Exception:
            pass
        try:
            self._servo2.release()
        except Exception:
            pass
        if self._servo1 is not None:
            self._servo1.close()
        if self._servo2 is not None:
            self._servo2.close()
