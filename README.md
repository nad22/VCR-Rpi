# VCR-Rpi

Raspberry Pi 4 based VCR style media controller on LibreELEC/Kodi.

Project goals:
- Hardware buttons like an old VCR (Play, Pause, Stop, FF, RW, Next, Prev)
- OLED status display with timecode and playback state
- RFID/media logic handled externally by Zaparoo (out of this codebase)

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
5. Install addon from libreelec/addons/service.vcr.recorder/

## Notes

- This repo is a starter framework with templates and script skeletons.
- Pin mappings and RFID providers can be adapted to your final build.
