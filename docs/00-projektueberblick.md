# Projektueberblick

## Ziel

Ein Raspberry Pi 4 mit LibreELEC soll sich wie ein klassischer VCR bedienen lassen:
- **Tasten am Gerät** + **drahtlose Fernbedienung** (ESP32) für Transportfunktionen
- **OLED-Display** für Status und Timecode mit Dithering-Effekten
- **Optischer Drehencoder** (Jog-Wheel) für präzises Spulen
- **RFID Tags** starten definierte Videos über Zaparoo

## Kernkomponenten

1. **Kodi Service Addon** auf LibreELEC (Python)
2. **Input-Layer** (GPIO am Pi + Bluetooth Remote vom ESP32)
3. **Display-Layer** (SSD1309 OLED mit VFD-Rendering)
4. **Audio-Layer** (ADS1115 ADC für echtes L/R VU-Meter)
5. **ESP32 Firmware** (PlatformIO) für drahtlose Fernbedienung
6. **Zaparoo RFID** Mapping auf Kodi Aktionen

## Betriebsmodi

1. **Standby** (Display zeigt Zeit)
2. **Browsing** (Menü Navigation)
3. **Playing** (Video läuft)
4. **Paused** (Video pausiert)
5. **Error/Offline** (Fehlerstate)

## Erste Milestones

1. Tasten -> Kodi JSON-RPC (Play/Pause/Stop)
2. OLED zeigt Titel, State und Timecode
3. RFID Tag startet ein lokales Video
4. Debounce/Timeout/Recovery robust machen
