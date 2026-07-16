# Hardwareliste

## Pflicht

1. Raspberry Pi 4 (2GB+), Netzteil 5V/3A
2. MicroSD (32GB+, A1/A2)
3. LibreELEC Installation (bereits vorhanden)
4. Taster (mindestens 6: Play, Pause, Stop, FF, RW, Next)
5. OLED Display 2.42 inch, SSD1309, I2C
6. RFID Reader: PN532 USB Modul (v2)

## Optional, aber empfohlen

1. Pegelstabile Verkabelung, Pull-up/Pull-down Widerstaende
2. Gehaeuse mit Frontpanel
3. Kleiner Lautsprecher/Buzzer fuer Feedback
4. Echtzeituhr-Modul (RTC) falls noetig

## Verdrahtung (direkt am Pi)

1. OLED an I2C (SDA/SCL + 3.3V + GND)
2. Buttons an GPIO + GND (internal pull-up nutzen)
3. PN532 USB v2 an einen freien USB Port am Raspberry Pi

## Referenz-Wiring (im Repo umgesetzt)

Raspberry Pi 4 (BCM Pin-Nummern):
1. OLED SSD1309 2.42 inch: SDA=GPIO2 (Pin 3), SCL=GPIO3 (Pin 5), 3.3V (Pin 1), GND (Pin 6)
2. Buttons (gegen GND):
   - Play/Pause: GPIO17
   - Stop: GPIO27
   - FF: GPIO22
   - RW: GPIO23
   - Next: GPIO24
   - Prev: GPIO25
   - GoStart: GPIO26
3. PN532 USB v2 direkt an Raspberry Pi USB Port
