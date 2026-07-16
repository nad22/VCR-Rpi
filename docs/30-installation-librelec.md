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
2. BCM Pins in buttons.json setzen (Referenz: 17,27,22,23,24,25,26)
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

## 5b) Echte L/R Aussteuerung per HDMI Audio Extractor + ADS1115

Empfohlener Ansatz bei HDMI Passthrough:
1. HDMI Audio Extractor verwenden und analoges Stereo Signal (L/R) abgreifen.
2. Signal auf ADS1115 fuehren (mit passender Bias-/Schutzbeschaltung fuer 3.3V ADC).
3. In display.json setzen:
	- audio_source=ads1115
	- ads1115.bus=auto (oder 1)
	- ads1115.address=0x48
	- ads1115.channel_left=0
	- ads1115.channel_right=1
	- ads1115.gain=4.096
	- ads1115.sps=860
4. Optional feinjustieren:
	- ads1115.bias (Ruhewert, typ. 16384)
	- ads1115.full_scale_delta (Empfindlichkeit VU, typ. 4000..9000)

Hinweis:
- Dieser Weg ist unabhaengig von Kodi/Pulse/ALSA Routing und funktioniert auch bei direkter HDMI-Durchleitung.

## 5c) Software Audioanalyse (optional)

Kodi JSON-RPC liefert keine echten Live-PCM-L/R-Pegel. Fuer echtes VU-Meter wird ein externer Analyzer genutzt.

1. In display.json aktivieren:
	- audio_source=external (oder auto)
	- audio_levels_file=/dev/shm/service.vcr.recorder/audio_levels.json
2. Analyzer-Script auf dem Pi starten:
	- python3 /storage/.kodi/addons/service.vcr.recorder/tools/audio_level_writer.py --device auto
3. Der Analyzer schreibt laufend left/right (0..100) in audio_levels.json
4. Das Addon liest die Datei und zeigt echte L/R-Werte ohne Fake-Modulation

Hinweis zu SD-Kartenverschleiss:
- /dev/shm ist RAM (tmpfs). Das Schreiben der Pegeldatei erfolgt damit im Arbeitsspeicher statt auf SD.

Hinweis:
- Wenn arecord auf LibreELEC nicht verfuegbar ist, muss ein alternativer Audio-Capture-Pfad verwendet werden (z.B. externer Analyzer auf anderem Host oder eigener Binary-Helper).
- Der mitgelieferte audio_level_writer.py versucht automatisch: arecord, dann ffmpeg, dann parec.
- Bei parec wird bei --device auto bevorzugt eine .monitor-Quelle des Default-Sinks verwendet (wenn pactl verfuegbar ist).
- Wenn keines verfuegbar ist, bleibt der Service stabil und schreibt 0/0 mit Hinweistext in die JSON-Datei.
- Wenn nur auto_null als Sink existiert (pactl list short sinks zeigt nur auto_null), gibt es kein echtes Playback-Audiosignal fuer VU.
- In diesem Fall muss ein realer Sink/Source verfuegbar sein (z.B. ALSA/Pulse-Ausgabegeraet) oder ein externer Analyzer verwendet werden.

Wenn HDMI Audio direkt durchgeleitet wird (Passthrough) und keine nutzbare Capture-Quelle existiert:
- audio_source in display.json auf kodi setzen
- vcr-audio-levels.service deaktivieren (systemctl disable --now vcr-audio-levels.service)

Autostart via systemd (empfohlen):
1. Datei libreelec/config/system.d/vcr-audio-levels.service nach /storage/.config/system.d/ kopieren
   - sicherstellen, dass im Addon-Pfad vorhanden ist: /storage/.kodi/addons/service.vcr.recorder/tools/audio_level_writer.py
2. Service aktivieren und starten:
	- systemctl daemon-reload
	- systemctl enable vcr-audio-levels.service
	- systemctl start vcr-audio-levels.service
3. Status pruefen:
	- systemctl status vcr-audio-levels.service
4. Bei mehreren Pulse Devices den Monitor fest setzen (Beispiel):
	- --device alsa_output.1.hdmi-stereo.monitor

## 6) Zaparoo integration

1. PN532 USB v2 am Raspberry Pi einstecken
2. Die komplette RFID-/Medienlogik wird von Zaparoo ausserhalb dieses Repos verarbeitet
3. Keine RFID-Zuordnungsskripte im Addon noetig
