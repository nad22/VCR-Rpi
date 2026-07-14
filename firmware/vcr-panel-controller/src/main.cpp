#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "pins.h"

namespace {
constexpr int SCREEN_WIDTH = 128;
constexpr int SCREEN_HEIGHT = 64;
constexpr int OLED_RESET = -1;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

struct Button {
  int pin;
  const char* eventName;
  bool lastState;
  unsigned long lastChangeMs;
};

Button buttons[] = {
  {PIN_BTN_PLAY_PAUSE, "BTN:PLAY_PAUSE", true, 0},
  {PIN_BTN_STOP, "BTN:STOP", true, 0},
  {PIN_BTN_FF, "BTN:FF", true, 0},
  {PIN_BTN_RW, "BTN:RW", true, 0},
  {PIN_BTN_NEXT, "BTN:NEXT", true, 0},
  {PIN_BTN_PREV, "BTN:PREV", true, 0},
};

constexpr unsigned long DEBOUNCE_MS = 30;

char uiState[16] = "READY";
char uiTimecode[16] = "00:00:00";
char uiTitle[32] = "VCR Panel";

void renderStatus(const char* line1, const char* line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  display.println(line2);
  display.display();
}

void renderUi() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(uiTitle);
  display.setCursor(0, 20);
  display.print("STATE: ");
  display.println(uiState);
  display.setCursor(0, 36);
  display.print("TC: ");
  display.println(uiTimecode);
  display.display();
}

void setSafeText(char* dst, size_t dstSize, const String& src) {
  if (dstSize == 0) {
    return;
  }
  size_t len = src.length();
  if (len >= dstSize) {
    len = dstSize - 1;
  }
  memcpy(dst, src.c_str(), len);
  dst[len] = '\0';
}

void handleIncomingSerial() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) {
      continue;
    }

    if (line.startsWith("STATE:")) {
      setSafeText(uiState, sizeof(uiState), line.substring(6));
      renderUi();
      continue;
    }
    if (line.startsWith("TC:")) {
      setSafeText(uiTimecode, sizeof(uiTimecode), line.substring(3));
      renderUi();
      continue;
    }
    if (line.startsWith("TITLE:")) {
      setSafeText(uiTitle, sizeof(uiTitle), line.substring(6));
      renderUi();
      continue;
    }
  }
}

}

void setup() {
  Serial.begin(115200);

  for (auto& btn : buttons) {
    pinMode(btn.pin, INPUT_PULLUP);
    btn.lastState = digitalRead(btn.pin);
    btn.lastChangeMs = millis();
  }

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    renderUi();
  }
}

void loop() {
  const unsigned long now = millis();

  handleIncomingSerial();

  for (auto& btn : buttons) {
    bool state = digitalRead(btn.pin);
    if (state != btn.lastState && (now - btn.lastChangeMs) > DEBOUNCE_MS) {
      btn.lastState = state;
      btn.lastChangeMs = now;
      if (state == LOW) {
        Serial.println(btn.eventName);
        renderStatus("INPUT", btn.eventName);
      }
    }
  }

  static unsigned long lastPing = 0;
  if ((now - lastPing) > 5000) {
    lastPing = now;
    Serial.println("PING");
  }
}
