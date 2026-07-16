# Installation auf LibreELEC

## 1) Kodi Addon deployment

1. Ordner libreelec/addons/service.vcr.recorder nach /storage/.kodi/addons kopieren
2. Kodi neustarten
3. Addon in Services aktivieren

## 2) Runtime config

1. config/buttons.example.json -> buttons.json kopieren und anpassen
2. config/display.example.json -> display.json kopieren und anpassen
3. Dateien nach /storage/.kodi/userdata/addon_data/service.vcr.recorder/ legen
4. Fuer Direktbetrieb auf Raspberry Pi GPIO nutzen (source=gpio, pin=...)

Alternativ direkt die produktionsnahen Vorlagen verwenden:
1. config/deploy/buttons.json
2. config/deploy/display.json

## 3) Log debugging

1. Kodi log pruefen: /storage/.kodi/temp/kodi.log
2. Filter nach service.vcr.recorder

## 4) Direkte Tastenanbindung am Raspberry Pi

1. Taster jeweils zwischen GPIO und GND verschalten
2. BCM Pins in buttons.json setzen (Referenz: 17,27,22,23,24,25)
3. active_low=true und debounce_ms setzen
4. GPIO Backend in buttons.json:
	- backend=sysfs (empfohlen fuer minimales LibreELEC ohne gpioget)
	- backend=auto oder gpiod nur wenn gpioget vorhanden ist
5. Bei Problemen mit GPIO pruefen:
	- ohne gpioget direkt backend=sysfs nutzen
	- ob gpiochip0 der richtige Chip ist (ggf. gpiochip4)

## 5) SSD1309 Display (VFD Design)

1. Display-Konfig in display.json setzen:
	- bus=auto (empfohlen)
	- address=0x3C (alternativ 0x3D)
	- probe_mode=cmd (alternativ data oder none bei hartnaeckigem Errno 121)
	- invert/rotate180 bei Bedarf
   - Hinweis: Auf manchen Modulen steht 0x78/0x7A aufgedruckt (8-bit). Das entspricht 0x3C/0x3D (7-bit).
2. Addon rendert:
	- Titelzeile (scrollend)
	- Grossen Timecode (HH:MM:SS)
	- Status (PLAY/PAUSE/FF/RW/STOP)
	- L/R Aussteuerung
3. Bei leerem Display pruefen:
	- I2C aktiviert
	- auf LibreELEC zusaetzlich /flash/config.txt pruefen: dtparam=i2c_arm=on
	- im Kodi-Log auf "SSD1309 config" achten (zeigt gefundene /dev/i2c-* Devices)
	- dort pruefen, ob bus=1 gesetzt werden kann (falls auto nur HDMI-DDC Busse sieht)
	- richtige Adresse (0x3C/0x3D)
	- korrekte 3.3V/GND/SDA/SCL Verdrahtung

## 6) Zaparoo integration

1. PN532 USB v2 am Raspberry Pi einstecken
2. Die komplette RFID-/Medienlogik wird von Zaparoo ausserhalb dieses Repos verarbeitet
3. Keine RFID-Zuordnungsskripte im Addon noetig
