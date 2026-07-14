# Installation auf LibreELEC

## 1) Kodi Addon deployment

1. Ordner libreelec/addons/service.vcr.recorder nach /storage/.kodi/addons kopieren
2. Kodi neustarten
3. Addon in Services aktivieren

## 2) Runtime config

1. config/buttons.example.json -> buttons.json kopieren und anpassen
2. Dateien nach /storage/.kodi/userdata/addon_data/service.vcr.recorder/ legen
3. Fuer Direktbetrieb auf Raspberry Pi GPIO nutzen (source=gpio, pin=...)

Alternativ direkt die produktionsnahen Vorlagen verwenden:
1. config/deploy/buttons.json

## 3) Log debugging

1. Kodi log pruefen: /storage/.kodi/temp/kodi.log
2. Filter nach service.vcr.recorder

## 4) Direkte Tastenanbindung am Raspberry Pi

1. Taster jeweils zwischen GPIO und GND verschalten
2. BCM Pins in buttons.json setzen (Referenz: 17,27,22,23,24,25)
3. active_low=true und debounce_ms setzen
4. Addon liest GPIO ueber /sys/class/gpio

## 5) Zaparoo integration

1. PN532 USB v2 am Raspberry Pi einstecken
2. Die komplette RFID-/Medienlogik wird von Zaparoo ausserhalb dieses Repos verarbeitet
3. Keine RFID-Zuordnungsskripte im Addon noetig
