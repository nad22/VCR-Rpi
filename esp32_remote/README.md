# VCR Remote — ESP32 Bluetooth Controller

Bluetooth-Fernbedienung für Kodi mit optischem Drehencoder (Jog-Wheel) und 7 Tasten.

## Hardware-Anforderungen

### Komponenten
- **ESP32 DevKit** (30-Pin oder 38-Pin)
- **KY-040 Rotary Encoder** (optisch oder mechanisch)
- **7x Push-Buttons** (momentary contact, active low)
- **Draht + Löten + USB-C Kabel** zum Pi

### Pinbelegung (ESP32 DevKit)

| Komponente | ESP32 GPIO | Pin |
| --- | --- | --- |
| Encoder CLK | GPIO19 | D23 |
| Encoder DT | GPIO18 | D18 |
| Encoder SW | GPIO5 | D5 |
| Play/Pause Button | GPIO12 | D12 |
| Stop Button | GPIO13 | D13 |
| FF Button | GPIO14 | D14 |
| RW Button | GPIO15 | D15 |
| Next Button | GPIO16 | D16 |
| Prev Button | GPIO17 | RX2 |
| Go Start Button | GPIO4 | D4 |
| GND | GND | GND |
| 3.3V | 3.3V | 3.3V |

**Alle Buttons und Encoder gegen GND!**

## Installation & Setup

### 1. PlatformIO installieren
```bash
# VSCode Extension
# Oder über pip:
pip install platformio
```

### 2. Build & Upload
```bash
# Im esp32_remote/ Verzeichnis:
pio run -e esp32dev -t upload

# Oder zum Monitor während Upload:
pio run -e esp32dev -t upload --monitor

# Serial Monitor (115200 baud):
pio run -t monitor
```

### 3. Bluetooth-Pairing (Kodi Pi)
```bash
# SSH auf Pi
sudo bluetoothctl
# agent on
# scan on
# [Warte auf "VCR_REMOTE" in der Liste]
# trust <mac_address>
# pair <mac_address>
# Hinweis: bei BluetoothSerial/SPP kann "connect" mit
# "br-connection-profile-unavailable" fehlschlagen.
# Das ist normal - wichtig sind trust/pair.
# Die Kodi-Addon-Verbindung erfolgt per RFCOMM-Socket.
```

## Konfiguration

### pin-Mapping anpassen
Editiere `include/config.h`:
```c
#define ENCODER_CLK 19  // Dein GPIO für Encoder CLK
#define BTN_PLAY_PAUSE 12  // Dein GPIO für Play/Pause
// ... etc
```

### Encoder-Sensitivität
```c
#define ENCODER_SEEK_STEP 0.5f  // Sekunden pro Schritt
#define ENCODER_TICKS_PER_STEP 4  // Quadratur-Flanken pro Event
#define ENCODER_MIN_EVENT_MS 25   // Mindestabstand zwischen SEEK-Events
```
- `0.5f`: sehr fein (0.5s Schritte)
- `1.0f`: fein (1s Schritte)
- `5.0f`: grob (5s Schritte)

Wenn bei einer Drehrichtung gleichzeitig `+` und `-` Events auftreten:
- `ENCODER_TICKS_PER_STEP` auf `8` erhöhen
- `ENCODER_MIN_EVENT_MS` auf `40` oder `60` erhöhen

## Kommunikationsformat

Die Remote sendet Events im Format:
```
PLAY_PAUSE
STOP
FF
RW
NEXT
PREV
GO_START
SEEK:+10
SEEK:-30
SEEK:+0.5
SEEK:-0.5
```

Der Kodi-Service (`bluetooth_remote.py`) liest diese und mappt sie auf Kodi-Aktionen.

## Debugging

### Serial Monitor (115200 baud)
```
[OK] Bluetooth device: VCR_REMOTE
[INIT] VCR Remote ready
[TX] PLAY_PAUSE
[ENC] pos=1 delta=1
[TX] SEEK:+10
```

### Bluetooth-Verbindung prüfen (Pi)
```bash
bluetoothctl
devices
info <mac_address>
```

## Troubleshooting

### Encoder dreht sich nicht
- Pin-Nummern in `config.h` prüfen
- Encoder ist auf Pull-Up konfiguriert — Pin muss gegen GND gehen
- ISR-Rate mit Oszilloskop prüfen (sollten ~ 100+ Impulse/Sekunde sein)

Bei industriellen Encodern (z. B. 600P/R, NPN Open-Collector, 5-24V):
- Versorgung oft `+5V` und `GND` am Encoder, aber `A`/`B` Signale nur auf ESP32 `3.3V`-Pullups führen
- `GND` vom Encoder und ESP32 muss gemeinsam verbunden sein (Common Ground)
- Optional externe Pullups `4.7k` von `A` und `B` nach `3.3V`, falls Signal instabil ist
- Typische Farbzuordnung laut Reviews: `Rot=VCC`, `Schwarz=GND`, `Weiss/Grün=A/B` (vendorabhängig prüfen)

### Buttons reagieren nicht
- Active-low Logik: Button gegen GND, nicht gegen 3.3V!
- Pull-up Widerstände sind schon im ESP32 aktiviert
- Debounce-Zeit erhöhen falls zu sensitiv: `#define DEBOUNCE_MS 100`

### Bluetooth-Verknüpfung fehlgeschlagen
```bash
# auf dem Pi:
bluetoothctl remove <mac_address>
bluetoothctl scan on
# und neu pairen
```

Wenn im Log "Connected: yes" und "ServicesResolved: yes" erscheint,
aber danach "br-connection-profile-unavailable", ist das bei SPP oft unkritisch.
Entscheidend ist, dass das Addon anschließend den RFCOMM-Kanal öffnen kann.

## Verdrahtungsbeispiel (KY-040)

```
Encoder:
  +----- CLK -----> ESP32 GPIO19
  +----- DT  -----> ESP32 GPIO18
  +----- SW  -----> ESP32 GPIO5
  +----- +   -----> 3.3V
  +----- GND -----> GND

Button (alle gleich):
  +----- Pin1  -----> ESP32 GPIO (12/13/14/15/16/17/4)
  +----- Pin2  -----> GND
```

## Projektstruktur

```
esp32_remote/
├── platformio.ini       # PlatformIO Konfiguration
├── src/
│   └── main.cpp         # Hauptprogramm
├── include/
│   └── config.h         # Pinbelegung & Konstanten
└── README.md            # Diese Datei
```

## Lizenz & Hinweise

- Code-Basis: Arduino IDE / PlatformIO
- BluetoothSerial: Arduino Core für ESP32
- Optisch oder mechanisch: je nach gewähltem Encoder-Typ
