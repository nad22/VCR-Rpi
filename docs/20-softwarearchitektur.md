# Softwarearchitektur

## Komponenten

1. Kodi Service Addon
   - Lifecycle in service.py
   - Polling von Player State
   - Command Routing von Buttons/RFID

2. Kodi RPC Client
   - JSON-RPC Calls fuer Play/Pause/Stop/Seek
   - Abruf von Current Item, Time, Total Time

3. Input Adapter
   - GPIO Events normalisieren
   - Debounce und Long-Press Unterstuetzung

4. OLED Renderer
   - Titelkuerzung
   - State Icon/Text
   - Timecode HH:MM:SS

5. RFID/Zaparoo Bridge
   - Liest Tag IDs
   - Mappt auf Kodi Datei/Playlist/Plugin URL

## Datenfluss

1. Button oder RFID Event kommt rein
2. Event Mapping -> Kodi Aktion
3. Aktion per JSON-RPC an Kodi
4. Status polling -> OLED Update

## Fehlertoleranz

1. Exception-safe loops mit Retry
2. Graceful fallback auf Log-only wenn Hardware fehlt
3. Heartbeat Log alle X Sekunden
