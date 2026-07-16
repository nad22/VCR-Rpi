# 1:1 Verdrahtung und Erstinbetriebnahme

## Verdrahtungstabelle (Referenzprofil)

Systemprofil:
- Host: Raspberry Pi 4
- Display: SSD1309 2.42 inch 128x64 I2C
- RFID: PN532 USB v2 (an Raspberry Pi)
- Taster: 6x direkt an Raspberry Pi GPIO gegen GND

### OLED SSD1309 2.42 inch -> Raspberry Pi

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
   - display.json
   - Quelle empfohlen: config/deploy/buttons.json
   - Quelle empfohlen: config/deploy/display.json
5. In buttons.json muessen alle Eintraege source=gpio und passende BCM Pins haben.
6. Kodi Log pruefen: /storage/.kodi/temp/kodi.log und nach service.vcr.recorder filtern.
7. Bei Tastendruck muessen die zugeordneten Kodi-Aktionen (Play/Pause, Stop, FF, RW, Next, Prev) reagieren.
8. Wenn keine Events ankommen:
   - GPIO Verdrahtung gegen GND pruefen
   - BCM Pin-Nummern in buttons.json pruefen
   - Rechte auf /sys/class/gpio pruefen
9. Wenn Display leer bleibt:
   - bus=auto in display.json nutzen
   - wenn im Log nur /dev/i2c-20 und /dev/i2c-21 auftauchen: bus=1 explizit setzen
   - display.json Adresse 0x3C testen, dann 0x3D
   - probe_mode=cmd testen, danach data, danach none
   - I2C in LibreELEC aktivieren
   - /flash/config.txt pruefen: dtparam=i2c_arm=on
   - pruefen, ob /dev/i2c-* vorhanden ist
   - Verdrahtung SDA/SCL/3.3V/GND pruefen

Konkrete LibreELEC Schritte fuer I2C-GPIO:
1. per SSH auf den Pi einloggen
2. /flash beschreibbar machen: mount -o remount,rw /flash
3. in /flash/config.txt sicherstellen: dtparam=i2c_arm=on
4. optional fuer Sichtbarkeit: dtoverlay=i2c1,pins_2_3
5. /flash wieder read-only: mount -o remount,ro /flash
6. reboot
7. danach pruefen, ob /dev/i2c-1 existiert

Hinweis fuer PN532 USB Setup:
- Der PN532 USB Reader und die komplette RFID/Medienlogik werden von Zaparoo ausserhalb dieses Repos betrieben.
