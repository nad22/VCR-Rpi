import json

import xbmc


class KodiRpc:
    def _call(self, method, params=None):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        return json.loads(raw)

    def get_active_player_id(self):
        result = self._call("Player.GetActivePlayers")
        players = result.get("result", [])
        if not players:
            return None
        return players[0].get("playerid")

    def get_player_state_text(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return "STOP"

        result = self._call(
            "Player.GetProperties",
            {"playerid": player_id, "properties": ["speed"]},
        )
        speed = result.get("result", {}).get("speed", 0)
        if speed == 0:
            return "PAUSE"
        if speed == 1:
            return "PLAY"
        if speed > 1:
            return "FF"
        return "RW"

    def play_pause(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return
        self._call("Player.PlayPause", {"playerid": player_id})

    def stop(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            self.execute_action("stop")
            return
        try:
            self._call("Player.Stop", {"playerid": player_id})
        except Exception:
            self.execute_action("stop")

    def goto_next(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return
        self._call("Player.GoTo", {"playerid": player_id, "to": "next"})

    def goto_previous(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return
        self._call("Player.GoTo", {"playerid": player_id, "to": "previous"})

    def seek_to_start(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            self.execute_action("skipprevious")
            return
        # For video playback, skipprevious is usually the most reliable way to jump
        # to the beginning of the current item.
        try:
            self.execute_action("skipprevious")
            return
        except Exception:
            pass

        # Some Kodi builds differ in accepted seek value formats.
        try:
            self._call(
                "Player.Seek",
                {
                    "playerid": player_id,
                    "value": {"hours": 0, "minutes": 0, "seconds": 0, "milliseconds": 0},
                },
            )
            return
        except Exception:
            pass

        try:
            self._call("Player.Seek", {"playerid": player_id, "value": 0})
        except Exception:
            self.execute_action("skipprevious")

    def seek_relative(self, offset_seconds):
        """Seek by a relative offset in seconds (can be positive or negative)."""
        player_id = self.get_active_player_id()
        if player_id is None:
            return False
        
        try:
            # Get current position
            props_result = self._call(
                "Player.GetProperties",
                {"playerid": player_id, "properties": ["time", "totaltime"]},
            )
            props = props_result.get("result", {})
            
            current_time = props.get("time", {})
            total_time = props.get("totaltime", {})
            hours = int(current_time.get("hours", 0))
            minutes = int(current_time.get("minutes", 0))
            seconds = int(current_time.get("seconds", 0))
            milliseconds = int(current_time.get("milliseconds", 0))

            total_hours = int(total_time.get("hours", 0))
            total_minutes = int(total_time.get("minutes", 0))
            total_seconds_whole = int(total_time.get("seconds", 0))
            total_milliseconds = int(total_time.get("milliseconds", 0))
            
            # Convert to total seconds
            total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
            duration_seconds = (
                total_hours * 3600
                + total_minutes * 60
                + total_seconds_whole
                + total_milliseconds / 1000.0
            )

            new_seconds = max(0.0, total_seconds + float(offset_seconds))
            if duration_seconds > 0:
                # Keep inside valid range; many Kodi builds ignore out-of-range seeks.
                new_seconds = min(new_seconds, max(0.0, duration_seconds - 0.25))

            new_seconds_int = int(new_seconds)
            seek_value = {
                "hours": new_seconds_int // 3600,
                "minutes": (new_seconds_int % 3600) // 60,
                "seconds": new_seconds_int % 60,
                "milliseconds": 0,
            }

            # Seek to new position — value must be wrapped in {"time": ...}
            seek_result = self._call(
                "Player.Seek",
                {
                    "playerid": player_id,
                    "value": {"time": seek_value},
                },
            )
            if "error" not in seek_result:
                return True

            # Percentage fallback — value must be wrapped in {"percentage": ...}
            if duration_seconds > 0:
                percent = max(0.0, min(100.0, (new_seconds / duration_seconds) * 100.0))
                percent_result = self._call(
                    "Player.Seek",
                    {"playerid": player_id, "value": {"percentage": percent}},
                )
                if "error" not in percent_result:
                    return True

            return False
        except Exception as exc:
            return False

    def execute_action(self, action):
        self._call("Input.ExecuteAction", {"action": action})

    def open_target(self, target):
        self._call("Player.Open", {"item": {"file": target}})

    def get_playback_snapshot(self):
        player_id = self.get_active_player_id()
        if player_id is None:
            return {
                "state": "STOP",
                "timecode": "00:00:00",
                "title": "-",
            }

        properties = self._call(
            "Player.GetProperties",
            {
                "playerid": player_id,
                "properties": ["speed", "time"],
            },
        ).get("result", {})

        item = self._call(
            "Player.GetItem",
            {
                "playerid": player_id,
                "properties": ["title", "showtitle", "label"],
            },
        ).get("result", {}).get("item", {})

        speed = properties.get("speed", 0)
        state = "PAUSE"
        if speed == 1:
            state = "PLAY"
        elif speed > 1:
            state = "FF"
        elif speed < 0:
            state = "RW"

        t = properties.get("time", {})
        hh = int(t.get("hours", 0))
        mm = int(t.get("minutes", 0))
        ss = int(t.get("seconds", 0))
        timecode = f"{hh:02d}:{mm:02d}:{ss:02d}"

        title = item.get("title") or item.get("showtitle") or item.get("label") or "-"
        return {
            "state": state,
            "timecode": timecode,
            "title": title,
        }

    def get_audio_level(self):
        # Kodi JSON-RPC does not expose real-time per-channel PCM peak data.
        result = self._call("Application.GetProperties", {"properties": ["volume", "muted"]})
        props = result.get("result", {})
        volume = int(props.get("volume", 0))
        muted = bool(props.get("muted", False))
        return 0 if muted else max(0, min(100, volume))
