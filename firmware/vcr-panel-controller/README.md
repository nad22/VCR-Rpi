# vcr-panel-controller

Optional PlatformIO firmware for an external controller board.

## Reference setup

- MCU: ESP32 DevKit v1
- OLED: SSD1306 128x64 over I2C
- RFID: PN532 USB v2 connected to Raspberry Pi
- Buttons: 6x momentary to GND (INPUT_PULLUP)

Pin mapping is defined in include/pins.h.

## Purpose

1. Read physical buttons with debouncing
2. Render state text on OLED
3. Send button events to Raspberry Pi over USB Serial

RFID events are provided by PN532 USB via Zaparoo on Raspberry Pi side.

## Event Protocol (line based)

Examples:
- BTN:PLAY_PAUSE
- BTN:STOP
- PING

Incoming lines from Kodi service to controller:
- STATE:PLAY
- TC:00:13:42
- TITLE:Blade Runner

## Build

1. Install PlatformIO
2. Open this folder as project
3. Build and upload to your MCU
