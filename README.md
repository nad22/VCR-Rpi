# VCR-Rpi — Klassischer VCR Controller mit Kodi

Ein Raspberry Pi 4 mit LibreELEC wird zur Fernbedienungs-fähigen VCR-ähnlichen Controller für Kodi Videos. Mit OLED-Display, physischen Tasten und einer drahtlosen Bluetooth-Fernbedienung mit Jog-Wheel.

## Features

✅ **7 Hardware-Tasten** + **ESP32 Bluetooth-Fernbedienung**  
✅ **SSD1309 OLED Display** mit VFD-Stilanzeige  
✅ **Optischer Drehencoder** für Spulen (±10s / Detent)  
✅ **Echtes L/R VU-Meter** via ADS1115 ADC  
✅ **Kodi JSON-RPC** Integration für volle Playback-Kontrolle  
✅ **RFID-Unterstützung** (via Zaparoo)  

## Quick-Start

**Dokumentation:** Siehe `docs/` Verzeichnis (Start mit [00-projektueberblick.md](docs/00-projektueberblick.md))

### Hardware aufbauen
```bash
# Verdrahtungs-Referenz: docs/50-verdrahtung-und-checkliste.md
- Raspberry Pi 4 + LibreELEC
- SSD1309 OLED an I2C
- 7 Tasten an GPIO (17, 27, 22, 23, 24, 25, 26)
- ADS1115 ADC für Audio (optional)
- ESP32 per USB/Bluetooth für Fernbedienung (optional)
```

### Installation

```bash
# Kodi Addon:
scp -r libreelec/addons/service.vcr.recorder root@pi:/storage/.kodi/addons/

# Config:
scp config/deploy/* root@pi:/storage/.kodi/userdata/addon_data/service.vcr.recorder/

# Fernbedienung (optional):
cd esp32_remote
pio run -e esp32dev -t upload
```

## Dokumentation

| Datei | Inhalt |
| --- | --- |
| [00-projektueberblick.md](docs/00-projektueberblick.md) | Ziele & Architektur |
| [10-hardwareliste.md](docs/10-hardwareliste.md) | Komponenten & Pinning |
| [20-softwarearchitektur.md](docs/20-softwarearchitektur.md) | Code-Struktur |
| [30-installation-librelec.md](docs/30-installation-librelec.md) | Pi-Setup |
| [50-verdrahtung-und-checkliste.md](docs/50-verdrahtung-und-checkliste.md) | Vollständige Verdrahtung |
| [60-esp32-fernbedienung.md](docs/60-esp32-fernbedienung.md) | Bluetooth-Remote Anleitung |

## Repository Structure

- docs/: planning and setup documentation
- libreelec/addons/service.vcr.recorder/: Kodi service addon (Python)
- config/: button configuration files

## Recommended Architecture

Direct-on-Raspberry-Pi (current default):
- Buttons are connected directly to Raspberry Pi GPIO
- PN532 USB reader is connected to Raspberry Pi and handled by Zaparoo directly
- Kodi addon in this repo consumes GPIO button events and controls playback via JSON-RPC

## Quick Start

1. Read docs/10-hardwareliste.md
2. Read docs/50-verdrahtung-und-checkliste.md
3. Read docs/30-installation-librelec.md
4. Use config/deploy/buttons.json
5. Use config/deploy/display.json
6. Install addon from libreelec/addons/service.vcr.recorder/

## Notes

- This repo is a starter framework with templates and script skeletons.
- Pin mappings and RFID providers can be adapted to your final build.
