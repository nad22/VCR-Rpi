#include <Arduino.h>
#include <BluetoothSerial.h>
#include "config.h"

// Bluetooth instance
BluetoothSerial SerialBT;

// Encoder state - ArcadeSpinner style: raw counter in ISR, scaled in loop
volatile int32_t encoder_raw_pos = 0;
volatile int8_t encoder_prev_state = 0;

// Quadrature decode table: index = (prev_AB << 2) | new_AB
// +1 = CW, -1 = CCW, 0 = no change or invalid
static const int8_t QEM[16] = {
  0, -1,  1,  0,
  1,  0,  0, -1,
 -1,  0,  0,  1,
  0,  1, -1,  0
};

// Button timing for debounce
struct ButtonState {
  uint8_t pin;
  const char* event;
  int last_raw_state;
  int stable_state;
  unsigned long last_change_time;
  bool sent_for_press;
};

ButtonState buttons[7] = {
  {BTN_PLAY_PAUSE, "PLAY_PAUSE", HIGH, HIGH, 0, false},
  {BTN_STOP, "STOP", HIGH, HIGH, 0, false},
  {BTN_FF, "FF", HIGH, HIGH, 0, false},
  {BTN_RW, "RW", HIGH, HIGH, 0, false},
  {BTN_NEXT, "NEXT", HIGH, HIGH, 0, false},
  {BTN_PREV, "PREV", HIGH, HIGH, 0, false},
  {BTN_GO_START, "GO_START", HIGH, HIGH, 0, false}
};

const uint8_t NUM_BUTTONS = sizeof(buttons) / sizeof(ButtonState);

// Forward declarations
void IRAM_ATTR encoder_isr();
void handle_buttons();
void send_command(const char* cmd);
void setup_hardware();
void drain_bt_rx();
void log_serial(const char* msg);

/**
 * Interrupt handler for rotary encoder - full quadrature state machine.
 * Attached to CHANGE on both CLK and DT pins.
 */
void IRAM_ATTR encoder_isr() {
  int8_t a = (int8_t)digitalRead(ENCODER_CLK);
  int8_t b = (int8_t)digitalRead(ENCODER_DT);

  // Same decoder principle as Arduino_ArcadeSpinner.
  int8_t state = (b << 1) | (b ^ a);
  int8_t diff = (encoder_prev_state - state) & 3;

  if (diff == 1) {
    encoder_raw_pos += (ENCODER_DIRECTION_INVERT ? -1 : 1);
  } else if (diff == 3) {
    encoder_raw_pos += (ENCODER_DIRECTION_INVERT ? 1 : -1);
  }

  encoder_prev_state = state;
}

/**
 * Initialize all pins and peripherals
 */
void setup_hardware() {
  // Encoder pins
  pinMode(ENCODER_CLK, INPUT_PULLUP);
  pinMode(ENCODER_DT, INPUT_PULLUP);
  pinMode(ENCODER_SW, INPUT_PULLUP);
  
  // Button pins
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    pinMode(buttons[i].pin, INPUT_PULLUP);
  }
  
  // Full quadrature decoder: CHANGE on both pins for bidirectional detection.
  {
    int8_t a = (int8_t)digitalRead(ENCODER_CLK);
    int8_t b = (int8_t)digitalRead(ENCODER_DT);
    encoder_prev_state = (b << 1) | (b ^ a);
  }
  attachInterrupt(digitalPinToInterrupt(ENCODER_CLK), encoder_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENCODER_DT),  encoder_isr, CHANGE);
}

/**
 * Read button states with debouncing
 */
void handle_buttons() {
  unsigned long now = millis();
  
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    int raw_state = digitalRead(buttons[i].pin);

    // Track the latest raw transition timestamp for debounce timing.
    if (raw_state != buttons[i].last_raw_state) {
      buttons[i].last_raw_state = raw_state;
      buttons[i].last_change_time = now;
    }

    // Accept a new stable state only after DEBOUNCE_MS without transition.
    if ((now - buttons[i].last_change_time) >= DEBOUNCE_MS && raw_state != buttons[i].stable_state) {
      buttons[i].stable_state = raw_state;

      if (buttons[i].stable_state == LOW) {
        // Active-low press: emit exactly once per full press-release cycle.
        if (!buttons[i].sent_for_press) {
          send_command(buttons[i].event);
          buttons[i].sent_for_press = true;
        }
      } else {
        // Button released, next press may emit again.
        buttons[i].sent_for_press = false;
      }
    }
  }
}

/**
 * Send command to Kodi Pi over Bluetooth
 */
void send_command(const char* cmd) {
  char msg[64];
  snprintf(msg, sizeof(msg), "%s\r\n", cmd);
  
  if (SerialBT.write((uint8_t*)msg, strlen(msg))) {
    Serial.print("[TX] ");
    Serial.println(cmd);
  } else {
    Serial.print("[TX FAILED] ");
    Serial.println(cmd);
  }
}

/**
 * Drain incoming SPP bytes to avoid BluetoothSerial RX overflow.
 */
void drain_bt_rx() {
  while (SerialBT.available() > 0) {
    (void)SerialBT.read();
  }
}

/**
 * Arduino setup()
 */
void setup() {
  Serial.begin(115200);
  delay(100);
  
  // Initialize Bluetooth
  if (!SerialBT.begin(BT_DEVICE_NAME)) {
    Serial.println("[ERR] Bluetooth init failed!");
  } else {
    Serial.print("[OK] Bluetooth device: ");
    Serial.println(BT_DEVICE_NAME);
  }
  
  // Initialize hardware
  setup_hardware();
  
  Serial.println("[INIT] VCR Remote ready");
  Serial.println("[INFO] Encoder: CLK=" STR(ENCODER_CLK) " DT=" STR(ENCODER_DT));
  Serial.println("[INFO] Buttons: 7 GPIO inputs configured");
}

/**
 * Arduino loop()
 */
void loop() {
  static unsigned long last_heartbeat_ms = 0;
  static unsigned long last_encoder_event_ms = 0;
  static int32_t logical_pos_prev = 0;
  static int last_raw_clk = HIGH;
  static int last_raw_dt = HIGH;

  // Handle button presses
  handle_buttons();

  // Keep SPP RX queue empty; otherwise BT stack reports RX Full.
  drain_bt_rx();

  // Raw encoder pin diagnostics.
  int raw_clk = digitalRead(ENCODER_CLK);
  int raw_dt = digitalRead(ENCODER_DT);
  if (raw_clk != last_raw_clk || raw_dt != last_raw_dt) {
    last_raw_clk = raw_clk;
    last_raw_dt = raw_dt;
    Serial.print("[ENC_RAW] clk=");
    Serial.print(raw_clk);
    Serial.print(" dt=");
    Serial.println(raw_dt);
  }

  // Read ISR raw counter and map to logical position via sensitivity divisor.
  int32_t raw_pos = 0;
  noInterrupts();
  raw_pos = encoder_raw_pos;
  interrupts();

  if (ENCODER_SENSITIVITY <= 0) {
    return;
  }

  int32_t logical_pos = raw_pos / ENCODER_SENSITIVITY;
  int32_t logical_delta = logical_pos - logical_pos_prev;

  // Emit seek events with fast-turn aggregation to reduce event volume.
  unsigned long now = millis();
  while (logical_delta != 0) {
    if ((last_encoder_event_ms > 0) && ((now - last_encoder_event_ms) < ENCODER_MIN_EVENT_MS)) {
      break;
    }

    char cmd[32];
    bool use_fast = (abs((int)logical_delta) >= ENCODER_FAST_TRIGGER_STEPS);
    int step_seconds = use_fast ? ENCODER_SEEK_STEP_FAST : ENCODER_SEEK_STEP;
    int consume_steps = use_fast ? ENCODER_FAST_FACTOR : 1;

    if (logical_delta > 0) {
      snprintf(cmd, sizeof(cmd), "SEEK:+%d", step_seconds);
      int take = min<int32_t>(logical_delta, consume_steps);
      logical_delta -= take;
      logical_pos_prev += take;
      send_command(cmd);
      Serial.print("[ENC] SEEK +");
      Serial.println(step_seconds);
    } else {
      snprintf(cmd, sizeof(cmd), "SEEK:-%d", step_seconds);
      int take = min<int32_t>(-logical_delta, consume_steps);
      logical_delta += take;
      logical_pos_prev -= take;
      send_command(cmd);
      Serial.print("[ENC] SEEK -");
      Serial.println(step_seconds);
    }
    last_encoder_event_ms = now;
    now = millis();
  }

  // Periodic link heartbeat for end-to-end debugging.
  if (millis() - last_heartbeat_ms >= 5000) {
    last_heartbeat_ms = millis();
    send_command("HEARTBEAT");
  }

  delay(LOOP_DELAY_MS);
}

#undef STR
#define STR(x) #x
