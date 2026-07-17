#include <BluetoothSerial.h>

BluetoothSerial SerialBT;

// Encoder pins (KY-040 style optical or mechanical rotary encoder)
#define ENCODER_CLK 19  // GPIO19
#define ENCODER_DT  18  // GPIO18
#define ENCODER_SW  5   // GPIO5 (button on encoder, optional)

// Button pins
#define BTN_PLAY_PAUSE  12
#define BTN_STOP        13
#define BTN_FF          14
#define BTN_RW          15
#define BTN_NEXT        16
#define BTN_PREV        17
#define BTN_GO_START    4

// Encoder state
volatile int encoder_pos = 0;
volatile int last_clk = HIGH;
volatile int last_dt = HIGH;

// Debounce
unsigned long last_button_time[7] = {0};
const unsigned long DEBOUNCE_MS = 50;

// Function prototypes
void IRAM_ATTR encoder_isr();
void read_buttons();
void send_command(const char* cmd);

void setup() {
  Serial.begin(115200);
  SerialBT.begin("VCR_REMOTE");  // Bluetooth device name
  
  // Encoder pins
  pinMode(ENCODER_CLK, INPUT_PULLUP);
  pinMode(ENCODER_DT, INPUT_PULLUP);
  pinMode(ENCODER_SW, INPUT_PULLUP);
  
  // Button pins
  pinMode(BTN_PLAY_PAUSE, INPUT_PULLUP);
  pinMode(BTN_STOP, INPUT_PULLUP);
  pinMode(BTN_FF, INPUT_PULLUP);
  pinMode(BTN_RW, INPUT_PULLUP);
  pinMode(BTN_NEXT, INPUT_PULLUP);
  pinMode(BTN_PREV, INPUT_PULLUP);
  pinMode(BTN_GO_START, INPUT_PULLUP);
  
  // Attach encoder interrupt (only on CLK change)
  attachInterrupt(digitalPinToInterrupt(ENCODER_CLK), encoder_isr, CHANGE);
  
  Serial.println("VCR Remote initialized");
  SerialBT.println("VCR Remote ready");
}

void loop() {
  read_buttons();
  
  // Check if encoder position changed
  static int last_encoder_pos = 0;
  if (encoder_pos != last_encoder_pos) {
    if (encoder_pos > last_encoder_pos) {
      send_command("SEEK:+10");  // Forward 10 seconds
    } else {
      send_command("SEEK:-10");  // Backward 10 seconds
    }
    last_encoder_pos = encoder_pos;
  }
  
  delay(20);  // Polling interval
}

void IRAM_ATTR encoder_isr() {
  int clk = digitalRead(ENCODER_CLK);
  int dt = digitalRead(ENCODER_DT);
  
  // Simple quadrature decoder
  if (clk != last_clk) {
    if (clk == LOW) {
      if (dt == LOW) {
        encoder_pos++;  // CW
      } else {
        encoder_pos--;  // CCW
      }
    }
    last_clk = clk;
  }
  last_dt = dt;
}

void read_buttons() {
  struct ButtonMap {
    int pin;
    const char* event;
  };
  
  ButtonMap buttons[] = {
    {BTN_PLAY_PAUSE, "PLAY_PAUSE"},
    {BTN_STOP, "STOP"},
    {BTN_FF, "FF"},
    {BTN_RW, "RW"},
    {BTN_NEXT, "NEXT"},
    {BTN_PREV, "PREV"},
    {BTN_GO_START, "GO_START"}
  };
  
  unsigned long now = millis();
  
  for (int i = 0; i < 7; i++) {
    if (digitalRead(buttons[i].pin) == LOW) {  // Button pressed (active low)
      if (now - last_button_time[i] > DEBOUNCE_MS) {
        send_command(buttons[i].event);
        last_button_time[i] = now;
      }
    }
  }
}

void send_command(const char* cmd) {
  // Format: "CMD:value"
  char msg[32];
  snprintf(msg, sizeof(msg), "%s\n", cmd);
  
  SerialBT.print(msg);
  Serial.print("TX: ");
  Serial.println(msg);
}
