#ifndef CONFIG_H
#define CONFIG_H

// Bluetooth configuration
#define BT_DEVICE_NAME "VCR_REMOTE"

// Encoder pins (KY-040 or similar optical/mechanical rotary encoder)
// Macro for stringifying macro values (for debug logging)
#define STR(x) #x

#define ENCODER_CLK 18  // GPIO18 (weiss)
#define ENCODER_DT  23  // GPIO23 (grün)
#define ENCODER_SW  5   // GPIO5 (encoder button, optional)
#define ENCODER_DIRECTION_INVERT 1  // set to 1 to swap + / - direction

// Button pins
#define BTN_PLAY_PAUSE  12
#define BTN_STOP        13
#define BTN_FF          14
#define BTN_RW          15
#define BTN_NEXT        16
#define BTN_PREV        17
#define BTN_GO_START    4

// Timing constants
#define DEBOUNCE_MS 50
#define LOOP_DELAY_MS 20
#define ENCODER_SEEK_STEP 1        // seconds per seek step (slow mode)
#define ENCODER_SEEK_STEP_FAST 10  // seconds per seek step (fast mode)
#define ENCODER_FAST_FACTOR 10     // consume this many logical steps per fast event
#define ENCODER_FAST_TRIGGER_STEPS 10  // fast mode when pending logical delta reaches this value
#define ENCODER_SENSITIVITY 100    // raw encoder ticks per logical seek step
#define ENCODER_MIN_EVENT_MS 80    // minimum spacing between emitted seek events (ms)

#endif
