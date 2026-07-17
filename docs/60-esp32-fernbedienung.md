# ESP32 Bluetooth Fernbedienung

Die VCR-Fernbedienung ist eine drahtlose Steuerung basierend auf ESP32 mit:
- **7 Tasten** (Play/Pause, Stop, FF, RW, Next, Prev, GoStart)
- **Optischer Drehencoder** (Jog-Wheel für Spulen)
- **Bluetooth Classic** (RFCOMM) Verbindung zum Raspberry Pi

## Hardware

### Komponenten Übersicht
| Komponente | Modell | Anschluss |
| --- | --- | --- |
| Microcontroller | ESP32 DevKit | USB-C zum Pi |
| Drehencoder | KY-040 oder optisch | GPIO Pins 18, 19, 5 |
| Tasten | Momentary Buttons | GPIO 4, 12-17 gegen GND |
| Stromversorgung | USB-C | 5V vom Pi oder USB-Netzteil |

### Pinbelegung

```
ESP32 GPIO -> Komponente
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GPIO4   -> GO_START Button
GPIO5   -> Encoder SW (optional)
GPIO12  -> PLAY_PAUSE Button
GPIO13  -> STOP Button
GPIO14  -> FF Button
GPIO15  -> RW Button
GPIO16  -> NEXT Button
GPIO17  -> PREV Button
GPIO18  -> Encoder DT (Data)
GPIO19  -> Encoder CLK (Clock)
GND     -> Alle Buttons + GND vom Encoder
3.3V    -> +3.3V vom Encoder
```

## Installation & Setup

### 1. PlatformIO installieren
```bash
pip install platformio
```

### 2. Firmware kompilieren & hochladen
```bash
cd esp32_remote
pio run -e esp32dev -t upload

# Mit Monitor-Output:
pio run -e esp32dev -t upload -t monitor
```

### 3. Bluetooth-Pairing (Kodi Pi)

Zuerst die Remote einschalten / USB anstecken.

```bash
# SSH auf dem Pi
ssh root@libreelec

# bluetoothctl starten
bluetoothctl

# Im bluetoothctl Prompt:
agent on
scan on

# Warten bis "VCR_REMOTE" erscheint, z.B.:
# [NEW] Device XX:XX:XX:XX:XX:XX VCR_REMOTE

# Dann:
trust XX:XX:XX:XX:XX:XX
pair XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX

# Bestätigung:
# [CHG] Device XX:XX:XX:XX:XX:XX Connected: yes
```

## Kommunikationsprotokoll

Die Remote sendet Events über Bluetooth RFCOMM (SPP) im Format:
```
COMMAND\r\n
COMMAND:VALUE\r\n
```

### Button-Events
```
PLAY_PAUSE
STOP
FF
RW
NEXT
PREV
GO_START
```

### Encoder-Events (Jog-Wheel)
```
SEEK:+10    (spule 10 Sekunden vor)
SEEK:-30    (spule 30 Sekunden zurück)
SEEK:+60    (spule 1 Minute vor)
```

Der Encoder sendet sich selbst zurücksetzen, d.h. nach jeder Drehung wird die Position wieder auf 0 gesetzt.

## Kodi Service Integration

Der Service (`service.py`) liest die Bluetooth-Events und mappt sie auf:
1. **Button-Events** → Kodi JSON-RPC Actions (Play, Stop, etc.)
2. **SEEK-Events** → `Player.Seek` mit relativ offset

Neue Methode in `kodi_rpc.py`:
```python
rpc.seek_relative(offset_seconds)  # z.B. +10, -30
```

Die Logging-Ausgabe zeigt erfolgreiche Events:
```
[BT event SEEK +10s]
[BT event NEXT -> Player.GoNext]
[BT event STOP -> Player.Stop]
```

## Konfiguration

### Encoder-Empfindlichkeit
In `esp32_remote/include/config.h`:
```c
#define ENCODER_SEEK_STEP 10  // Sekunden pro Detent
```

Standard: 10 Sekunden
- 5sec: feine Kontrolle
- 20sec: grobe Kontrolle

### Pin-Mapping
Alle Pins sind in `include/config.h` definiert und können angepasst werden:
```c
#define BTN_PLAY_PAUSE 12
#define ENCODER_CLK 19
```

### Debounce-Zeit
```c
#define DEBOUNCE_MS 50  // 50ms
```

## Debugging

### Serial Monitor (ESP32)
```bash
pio run -t monitor -e esp32dev
# oder
screen /dev/ttyUSB0 115200
```

Beispiel-Ausgabe:
```
[OK] Bluetooth device: VCR_REMOTE
[INIT] VCR Remote ready
[TX] PLAY_PAUSE
[ENC] pos=1 delta=1
[TX] SEEK:+10
```

### Bluetooth-Status prüfen (Pi)
```bash
bluetoothctl info XX:XX:XX:XX:XX:XX
```

Sollte zeigen:
```
Connected: yes
RSSI: -50
```

## Troubleshooting

### Bluetooth verbindet sich nicht
```bash
bluetoothctl
devices
# Sollte VCR_REMOTE zeigen
connect XX:XX:XX:XX:XX:XX
# Falls denied, remove + re-pair
remove XX:XX:XX:XX:XX:XX
```

### Encoder dreht sich nicht
- Überprüfen ob die Pins CLK (19) und DT (18) korrekt sind
- Mit Multimeter: Encoder sollte gegen GND gehen
- ISRint-Rate: sollten 100+ Impulse/Sekunde sein
- Mit `screen /dev/ttyUSB0 115200` Debug ausgeben lassen

### Buttons reagieren nicht
- Alle Buttons sind Active-Low (gegen GND)
- GPIO Pull-up ist im ESP32 konfiguriert (INPUT_PULLUP)
- Mit Serial Monitor checken ob Button-Drucke ankommen

### Remote-Events erreichen nicht Kodi
- Mit `tail -f /storage/.kodi/temp/kodi.log | grep BT` checken
- Bluetooth-Verbindung läuft noch? → `bluetoothctl info XX:...`
- Kodi Service neu starten: `systemctl restart service.vcr.recorder`

## Erweiterungen

### Weitere Tasten hinzufügen
1. Button in `config.h` definieren
2. GPIO in `bluetooth_remote.py` Button-Array ergänzen
3. Event-Name wählen, z.B. "CUSTOM1"
4. Im Service oder button_mapping.json die Aktion zuordnen

### Andere Encoder-Modi
- Schneller drehen = größere Schritte (möglich durch Schnellerkennung)
- Drücken auf Encoder = Spulen-Mode toggle (optional)

## Referenzen

- **PlatformIO Docs**: https://docs.platformio.org/
- **ESP32 Arduino Docs**: https://docs.espressif.com/projects/arduino-esp32/en/latest/
- **BluetoothSerial Lib**: Arduino Core für ESP32

## Lizenz & Hinweise

Der Code basiert auf Arduino Core für ESP32 und ist unter den gleichen Bedingungen wie das Kodi-Addon verfügbar.
