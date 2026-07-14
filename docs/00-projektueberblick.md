# Projektueberblick

## Ziel

Ein Raspberry Pi 4 mit LibreELEC soll sich wie ein klassischer VCR bedienen lassen:
- Tasten am Geraet fuer Transportfunktionen
- OLED fuer Status und Timecode
- RFID Tags starten definierte Videos ueber Zaparoo

## Kernkomponenten

1. Kodi Service Addon auf LibreELEC
2. Input-Layer (GPIO direkt oder externe MCU per USB)
3. Display-Layer fuer OLED Updates
4. Zaparoo RFID Mapping auf Kodi Aktionen

## Betriebsmodi

1. Standby
2. Browsing
3. Playing
4. Paused
5. Error/Offline

## Erste Milestones

1. Tasten -> Kodi JSON-RPC (Play/Pause/Stop)
2. OLED zeigt Titel, State und Timecode
3. RFID Tag startet ein lokales Video
4. Debounce/Timeout/Recovery robust machen
