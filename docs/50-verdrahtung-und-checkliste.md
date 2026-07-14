# 1:1 Verdrahtung und Erstinbetriebnahme

## Verdrahtungstabelle (Referenzprofil)

Systemprofil:
- Host: Raspberry Pi 4
- Display: SSD1306 128x64 I2C
- RFID: PN532 USB v2 (an Raspberry Pi)
- Taster: 6x direkt an Raspberry Pi GPIO gegen GND

### OLED SSD1306 -> Raspberry Pi

| OLED Pin | Raspberry Pi Pin |
| --- | --- |
| VCC | 3V3 (Pin 1) |
| GND | GND (Pin 6) |
| SDA | GPIO2 / SDA1 (Pin 3) |
| SCL | GPIO3 / SCL1 (Pin 5) |

### PN532 USB -> Raspberry Pi

| PN532 USB | Raspberry Pi |
| --- | --- |
| USB | USB Port |

### Taster -> Raspberry Pi

Jeder Taster hat 2 Pins:
1. Eine Seite an den angegebenen GPIO
2. Andere Seite an GND

| Funktion | Raspberry Pi GPIO |
| --- | --- |
| Play/Pause | GPIO17 |
| Stop | GPIO27 |
| Fast Forward | GPIO22 |
| Rewind | GPIO23 |
| Next | GPIO24 |
| Previous | GPIO25 |

## Erstinbetriebnahme-Checkliste

1. Taster gemaess Verdrahtungstabelle mit dem Raspberry Pi verbinden.
2. Addon-Ordner nach /storage/.kodi/addons kopieren und Kodi neu starten.
3. I2C in LibreELEC aktivieren (falls noch nicht aktiv).
4. In /storage/.kodi/userdata/addon_data/service.vcr.recorder/ folgende Dateien ablegen:
   - buttons.json
   - Quelle empfohlen: config/deploy/buttons.json
5. In buttons.json muessen alle Eintraege source=gpio und passende BCM Pins haben.
6. Kodi Log pruefen: /storage/.kodi/temp/kodi.log und nach service.vcr.recorder filtern.
7. Beim Start einer Wiedergabe muessen STATE:/TC:/TITLE: am Controller ankommen.
8. Wenn keine Events ankommen:
   - GPIO Verdrahtung gegen GND pruefen
   - BCM Pin-Nummern in buttons.json pruefen
   - Rechte auf /sys/class/gpio pruefen

Hinweis fuer PN532 USB Setup:
- Der PN532 USB Reader und die komplette RFID/Medienlogik werden von Zaparoo ausserhalb dieses Repos betrieben.
