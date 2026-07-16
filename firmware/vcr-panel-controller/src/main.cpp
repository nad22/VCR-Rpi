#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

#include "pins.h"

namespace {
constexpr int SCREEN_WIDTH = 128;
constexpr int SCREEN_HEIGHT = 64;

U8G2_SSD1309_128X64_NONAME0_F_HW_I2C display(U8G2_R0, U8X8_PIN_NONE, PIN_I2C_SCL, PIN_I2C_SDA);

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
  display.clearBuffer();
  display.setFont(u8g2_font_6x12_tf);
  display.drawStr(0, 12, line1);
  display.drawStr(0, 28, line2);
  display.sendBuffer();
}

void renderUi() {
  char line2[32];
  char line3[32];
  snprintf(line2, sizeof(line2), "STATE: %s", uiState);
  snprintf(line3, sizeof(line3), "TC: %s", uiTimecode);

  display.clearBuffer();
  display.setFont(u8g2_font_6x12_tf);
  display.drawStr(0, 12, uiTitle);
  display.drawStr(0, 28, line2);
  display.drawStr(0, 44, line3);
  display.sendBuffer();
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

  display.begin();
  renderUi();
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
