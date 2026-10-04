#include <IRremote.h>

// ─────────────────────────────
// IR REMOTE
// ─────────────────────────────
#define IR_FORWARD 0x2F0
#define IR_RIGHT   0xCD0
#define IR_DOWN    0xAF0
#define IR_LEFT   0x2D0

#define IR_PLAY    0x2CE9
#define IR_STOP    0xCE9
#define IR_FFWD    0x1CE9
#define IR_SKIP    0x5EE9

#define IR_1       0x10
#define IR_2       0x810
#define IR_3       0x410
#define IR_4       0xC10
#define IR_5       0x210
#define IR_6       0xA10
#define IR_7       0x610
#define IR_8       0xE10
#define IR_9       0x110
#define IR_0       0x910

#define IR_LOCK    0x52E9  // Red
#define IR_UNLOCK  0x32E9  // Green
#define IR_YELLOW  0x12E9
#define IR_BLUE    0x72E9

#define RECV_PIN 5
IRrecv irrecv(RECV_PIN);
decode_results results;

bool motionDetected = false;

// ─────────────────────────────
// LED PINS
// ─────────────────────────────
const int FRONT_LIGHT = 2;
const int BACK_LIGHT  = 3;

// ─────────────────────────────
// SENSOR PINS
// ─────────────────────────────
#define METAL_PIN A0
#define PHOTO_PIN A1
#define UV_PIN    A2
#define BALL_PIN  A3
#define MOTION_PIN 4
#define LF_LEFT  8
#define LF_MID   10
#define LF_RIGHT 9

// ─────────────────────────────
// VARIABLES
// ─────────────────────────────
bool frontLights = false;
bool backLights  = false;
unsigned long lastSensorUpdate = 0;

// ─────────────────────────────
// IR STATE TRACKING
// ─────────────────────────────
unsigned long lastIRTime = 0;
unsigned long lastIRCode = 0;
bool irButtonHeld = false;
#define IR_TIMEOUT 300  // ms with no signal = button released
unsigned long irTimeoutMs = IR_TIMEOUT;   // remote or link, whichever is driving

// ─────────────────────────────
// FLEET LINK (commands relayed by NORA)
// ─────────────────────────────
// NORA's web page, Python controller and Bluetooth link can drive KIDA through
// NORA's IR transmitter: Samsung-format frames at KIDA_LINK_ADDRESS, with the
// command codes the whole fleet link uses (IDA 0x0DA1, MILA 0x0DA2, WHIP
// 0x0DA3). Each is printed as the IR line the Pi already understands, so
// arduino.py / ir_bridge.py need no changes. Drive commands repeat every
// 150 ms while held; "IRrelease" follows once they've been quiet LINK_TIMEOUT.
#define KIDA_LINK_ADDRESS 0x0DA4
#define LINK_FORWARD   0x48
#define LINK_BACKWARD  0x49
#define LINK_LEFT      0x4A
#define LINK_RIGHT     0x4B
#define LINK_STOP      0x4C
#define LINK_OBSTACLE  0x4D
#define LINK_MANUAL    0x4E   // IR remote mode
#define LINK_SPEED     0x4F   // speed up
#define LINK_TIMEOUT   500
uint8_t lastLinkCmd = 0;

// ─────────────────────────────
// SETUP
// ─────────────────────────────
void setup() {
  Serial.begin(9600);

  pinMode(FRONT_LIGHT, OUTPUT);
  pinMode(BACK_LIGHT, OUTPUT);

  pinMode(MOTION_PIN, INPUT);
  pinMode(BALL_PIN, INPUT);

  pinMode(LF_LEFT, INPUT);
  pinMode(LF_MID, INPUT);
  pinMode(LF_RIGHT, INPUT);

  irrecv.enableIRIn();

  Serial.println("DEV1_READY");

  TurnOnFrontLights();
}

// ─────────────────────────────
// MAIN LOOP
// ─────────────────────────────
void loop() {
  handleIR();
  handleSerialCommands();
  readSensors();
}

// ─────────────────────────────
// IR REMOTE HANDLER
// ─────────────────────────────
void handleIR() {
  if (irrecv.decode(&results)) {
    if (irrecv.decodedIRData.protocol == SAMSUNG && irrecv.decodedIRData.address == KIDA_LINK_ADDRESS) {
      handleLink(irrecv.decodedIRData.command);
      irrecv.resume();
      return;
    }
    unsigned long code = results.value;
    irTimeoutMs = IR_TIMEOUT;

    // 0xFFFFFFFF means "still held" — use last known code
    if (code == 0xFFFFFFFF) {
      code = lastIRCode;
    } else {
      lastIRCode = code;
    }

    lastIRTime = millis();
    irButtonHeld = true;

    switch(code) {
      case IR_FORWARD:  Serial.println("IRforward"); break;
      case IR_RIGHT:    Serial.println("IRright"); break;
      case IR_DOWN:     Serial.println("IRdown"); break;
      case IR_LEFT:     Serial.println("IRleft"); break;
      case IR_PLAY:     Serial.println("IRplay"); break;
      case IR_STOP:     Serial.println("IRstop"); break;
      case IR_FFWD:     Serial.println("IRfastforward"); break;
      case IR_SKIP:     Serial.println("IRskipforward"); break;
      case IR_1:        Serial.println("IR1"); break;
      case IR_2:        Serial.println("IR2"); break;
      case IR_3:        Serial.println("IR3"); break;
      case IR_4:        Serial.println("IR4"); break;
      case IR_5:        Serial.println("IR5"); break;
      case IR_6:        Serial.println("IR6"); break;
      case IR_7:        Serial.println("IR7"); break;
      case IR_8:        Serial.println("IR8"); break;
      case IR_9:        Serial.println("IR9"); break;
      case IR_0:        Serial.println("IR0"); break;
      case IR_LOCK:     Serial.println("IRlock"); break;
      case IR_UNLOCK:   Serial.println("IRunlock"); break;
      case IR_YELLOW:   Serial.println("IRyellow"); break;
      case IR_BLUE:     Serial.println("IRblue"); break;
      default:
        Serial.print("IRunknown 0x");
        Serial.println(code, HEX);
        break;
    }

    irrecv.resume();
  }

  // ── Button release detection ──
  if (irButtonHeld && (millis() - lastIRTime > irTimeoutMs)) {
    irButtonHeld = false;
    Serial.println("IRrelease");  // Pi knows the button was let go
    lastIRCode = 0;
    lastLinkCmd = 0;
  }
}

// A link command from NORA, printed as the matching remote line. A drive
// switches the Pi into IR remote mode first ("IR1") on the first frame of a
// press; repeated frames just keep the press alive.
void handleLink(uint8_t c) {
  const char* drive = nullptr;
  switch (c) {
    case LINK_FORWARD:  drive = "IRforward"; break;
    case LINK_BACKWARD: drive = "IRdown";    break;
    case LINK_LEFT:     drive = "IRleft";    break;
    case LINK_RIGHT:    drive = "IRright";   break;
    case LINK_STOP:     Serial.println("IRrelease");     irButtonHeld = false; lastLinkCmd = 0; return;
    case LINK_OBSTACLE: Serial.println("IR3");           return;
    case LINK_MANUAL:   Serial.println("IR1");           return;
    case LINK_SPEED:    Serial.println("IRfastforward"); return;
    default: return;
  }
  if (c != lastLinkCmd) {
    if (!lastLinkCmd) Serial.println("IR1");
    Serial.println(drive);
    lastLinkCmd = c;
  }
  lastIRTime   = millis();
  irButtonHeld = true;
  irTimeoutMs  = LINK_TIMEOUT;
}

// ─────────────────────────────
// SERIAL COMMANDS FROM PI
// ─────────────────────────────
void handleSerialCommands() {
  if (Serial.available() <= 0) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "LIGHT_FRONT_ON") TurnOnFrontLights();
  else if (cmd == "LIGHT_FRONT_OFF") TurnOffFrontLights();
  else if (cmd == "LIGHT_BACK_ON") TurnOnBackLights();
  else if (cmd == "LIGHT_BACK_OFF") TurnOffBackLights();
  else if (cmd == "WHOAMI") Serial.println("I_AM_DEV01");
}

// ─────────────────────────────
// SENSOR READING
// ─────────────────────────────
void readSensors() {
  if (millis() - lastSensorUpdate < 250) return;
  lastSensorUpdate = millis();

  bool motion = digitalRead(MOTION_PIN);
  int photo = analogRead(PHOTO_PIN);
  int uv = analogRead(UV_PIN);
  int metal = analogRead(METAL_PIN);
  int ball = digitalRead(BALL_PIN);
  int lfLeft  = digitalRead(LF_LEFT);
  int lfMid   = digitalRead(LF_MID);
  int lfRight = digitalRead(LF_RIGHT);

  // ─── Flattened sensor line ───
  Serial.print("MOTION:"); Serial.print(motion);
  Serial.print(" | PHOTO:"); Serial.print(photo);
  Serial.print(" | UV:"); Serial.print(uv);
  Serial.print(" | METAL:"); Serial.print(metal);
  Serial.print(" | BALL:"); Serial.print(ball);
  Serial.print(" | L:"); Serial.print(lfLeft);
  Serial.print(" | M:"); Serial.print(lfMid);
  Serial.print(" | R:"); Serial.println(lfRight);

  // ─── Alerts (new lines) ───
  if (motion) {
    Serial.println("MOTION DETECTED");

    // Strobe back lights only once per motion event
    if (!motionDetected) {
      BlinkBackLights(5, 100); // example: 5 flashes, 100ms delay
      motionDetected = true;
    }
  } else {
    motionDetected = false; // reset when motion stops
  }

  if (metal > 350) Serial.println("METAL DETECTED");
  if (ball == HIGH) Serial.println("BALL SWITCH");
}

// ─────────────────────────────
// LIGHT FUNCTIONS
// ─────────────────────────────
void TurnOnFrontLights()  { digitalWrite(FRONT_LIGHT, HIGH); frontLights = true; }
void TurnOffFrontLights() { digitalWrite(FRONT_LIGHT, LOW);  frontLights = false; }
void TurnOnBackLights()   { digitalWrite(BACK_LIGHT, HIGH);  backLights = true; }
void TurnOffBackLights()  { digitalWrite(BACK_LIGHT, LOW);   backLights = false; }

void BlinkBackLights(int times, int delayMs) {
  for (int i=0; i<times; i++) {
    TurnOnBackLights();  delay(delayMs);
    TurnOffBackLights(); delay(delayMs);
  }
}
