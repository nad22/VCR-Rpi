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
