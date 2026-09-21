#include "Adafruit_VL53L0X.h"
#include <Servo.h>
#include <Adafruit_NeoPixel.h>
#include <stdlib.h>   // atoi() — used by the LMOTOR:/RMOTOR: parser below
#include <string.h>   // strcmp()/strncmp() — serial command parser
#include <ctype.h>    // isspace()/toupper() — serial command parser
#ifdef __AVR__
  #include <avr/power.h>
  #include <Wire.h>
#endif

// ===============================================
// CONFIGURATION
// ===============================================
namespace Config {
  // Servo
  constexpr uint8_t SERVO_PIN            = 10;
  constexpr uint8_t SERVO_CENTER         = 90;
  constexpr uint8_t SERVO_LEFT           = 45;
  constexpr uint8_t SERVO_RIGHT          = 135;

  // Ultrasonic — US0: fixed low, US1: servo-mounted high
  constexpr uint8_t US0_TRIG             = A1;
  constexpr uint8_t US0_ECHO             = A0;
  constexpr uint8_t US1_TRIG             = A2;
  constexpr uint8_t US1_ECHO             = A3;

  // Motors
  constexpr uint8_t MOTOR_RIGHT_PWM      = 6;
  constexpr uint8_t MOTOR_RIGHT_DIR1     = 7;
  constexpr uint8_t MOTOR_RIGHT_DIR2     = 9;
  constexpr uint8_t MOTOR_LEFT_PWM       = 3;
  constexpr uint8_t MOTOR_LEFT_DIR1      = 4;
  constexpr uint8_t MOTOR_LEFT_DIR2      = 5;
  constexpr uint8_t DEFAULT_MOTOR_SPEED  = 200;

  // NeoPixel strips
  constexpr uint8_t STRIP1_PIN           = 13;
  constexpr uint8_t STRIP2_PIN           = 12;
  constexpr uint8_t NUM_PIXELS           = 8;

  // Audio
  constexpr uint8_t  BUZZER_PIN          = 8;
  constexpr uint16_t TONE_STARTUP        = 440;
  constexpr uint16_t TONE_MODE          = 1000;
  constexpr uint16_t TONE_LEFT           = 800;
  constexpr uint16_t TONE_RIGHT          = 1000;
  constexpr uint16_t TONE_REVERSE        = 400;

  // Button
  constexpr uint8_t BUTTON_PIN           = 2;

  // Obstacle thresholds
  constexpr uint8_t  OBSTACLE_CM         = 25;   // ultrasonic threshold (cm)
  constexpr uint16_t OBSTACLE_MM         = 200;  // laser threshold (mm)
  constexpr uint8_t  CLEAR_CM            = 30;   // "open route" threshold (cm)
  constexpr uint16_t TURN_MS             = 750;  // avoidance turn duration (was 350 — too short to clear obstacle)

  // Serial
  constexpr uint16_t SERIAL_BAUD         = 9600;
  constexpr uint16_t SENSOR_INTERVAL     = 200;  // ms between sensor prints

  // If the Pi dies (crash/kill -9/power loss) while AUTO_ON is active, there's
  // no more Python code running to send AUTO_OFF/STOP — the Arduino would
  // otherwise keep driving forever. The Pi sends a PING every ~500ms while
  // autonomous; if none arrives for this long, stop and drop out of auto mode.
  constexpr uint16_t AUTONOMOUS_WATCHDOG_MS = 1500;
}

// ===============================================
// TYPE DEFINITIONS
// ===============================================
enum class MotorDirection : uint8_t { STOP = 0, FORWARD, BACKWARD, LEFT, RIGHT };

struct RobotState {
  MotorDirection direction   = MotorDirection::STOP;
  uint8_t        motorSpeed  = Config::DEFAULT_MOTOR_SPEED;
  bool           btnPressed  = false;
  bool           systemReady = false;
};

// Independent per-side speed, set via LMOTOR:/RMOTOR: for tank-style drive
// (Q/A = left, W/S = right on the KIDA UIs). Reset to 0 by
// executeMotorCommand() so switching back to a preset direction (or STOP)
// never leaves a stale independent speed active on the other side.
int tankLeftSpeed  = 0;
int tankRightSpeed = 0;

// Straight-line correction for FORWARD/BACKWARD only — LEFT/RIGHT already
// drive the two sides differentially on purpose, so trim doesn't apply
// there. Set via TRIM:<-50..50> (Python side persists it in kida_db.py and
// resends it every time dev00 (re)connects, since this firmware has no
// persistent storage of its own). Positive slows the right motor
// (corrects a rightward drift); negative slows the left motor.
int8_t wheelTrimPercent = 0;

int applyLeftTrim(int s) {
  if (wheelTrimPercent >= 0) return s;
  return (int)((long)s * (100 + wheelTrimPercent) / 100);
}

int applyRightTrim(int s) {
  if (wheelTrimPercent <= 0) return s;
  return (int)((long)s * (100 - wheelTrimPercent) / 100);
}

struct SensorReadings {
  int  laser      = -1;
  long us0        = -1;  // fixed low
  long us1        = -1;  // servo high
  bool btnState   = false;
};

bool autonomousMode = false;
unsigned long lastCommandMs = 0;   // last time a serial line was received (watchdog)

// ===============================================
// HARDWARE INSTANCES
// ===============================================
Adafruit_VL53L0X  laserSensor;
Servo             robotServo;
Adafruit_NeoPixel strip1(Config::NUM_PIXELS, Config::STRIP1_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip2(Config::NUM_PIXELS, Config::STRIP2_PIN, NEO_GRB + NEO_KHZ800);

// ===============================================
// GLOBAL STATE
// ===============================================
RobotState    robotState;
unsigned long lastSensorPrint = 0;
unsigned long lastStrobe      = 0;
unsigned long rainbowIndex    = 0;

// ===============================================
// AUDIO
// ===============================================
void playTone(uint16_t freq, uint16_t dur = 0) {
  if (dur > 0) tone(Config::BUZZER_PIN, freq, dur);
  else         tone(Config::BUZZER_PIN, freq);
}
void stopTone() { noTone(Config::BUZZER_PIN); }

// ===============================================
// LIGHT HELPERS
// ===============================================
uint32_t wheelColor(byte pos) {
  pos = 255 - pos;
  if (pos < 85)       return strip1.Color(255 - pos * 3, 0,           pos * 3);
  else if (pos < 170) { pos -= 85;  return strip1.Color(0,           pos * 3, 255 - pos * 3); }
  else                { pos -= 170; return strip1.Color(pos * 3, 255 - pos * 3, 0); }
}

// Set all pixels on both strips to one color
void setAllPixels(uint32_t color) {
  for (int i = 0; i < Config::NUM_PIXELS; i++) {
    strip1.setPixelColor(i, color);
    strip2.setPixelColor(i, color);
  }
  strip1.show();
  strip2.show();
}

// Strip1 = left color, Strip2 = right color (turn indicators)
void setSplitPixels(uint32_t leftColor, uint32_t rightColor) {
  for (int i = 0; i < Config::NUM_PIXELS; i++) {
    strip1.setPixelColor(i, leftColor);
    strip2.setPixelColor(i, rightColor);
  }
  strip1.show();
  strip2.show();
}

// Flash both strips n times
void lightFlash(uint32_t color, int times, int onMs = 120, int offMs = 80) {
  for (int i = 0; i < times; i++) {
    setAllPixels(color);
    delay(onMs);
    setAllPixels(strip1.Color(0, 0, 0));
    delay(offMs);
  }
}

// Alternating strobe between strip1 and strip2 (police-style)
void lightAlternate(uint32_t colorA, uint32_t colorB, int times, int delayMs = 90) {
  for (int i = 0; i < times; i++) {
    for (int p = 0; p < Config::NUM_PIXELS; p++) {
      strip1.setPixelColor(p, colorA);
      strip2.setPixelColor(p, 0);
    }
    strip1.show(); strip2.show();
    delay(delayMs);

    for (int p = 0; p < Config::NUM_PIXELS; p++) {
      strip1.setPixelColor(p, 0);
      strip2.setPixelColor(p, colorB);
    }
    strip1.show(); strip2.show();
    delay(delayMs);
  }
  strip1.clear(); strip2.clear();
  strip1.show();  strip2.show();
}

// Single pixel chase across both strips (opposite directions)
void lightChase(uint32_t color, int delayMs = 55) {
  for (int i = 0; i < Config::NUM_PIXELS; i++) {
    strip1.clear(); strip2.clear();
    strip1.setPixelColor(i, color);
    strip2.setPixelColor(Config::NUM_PIXELS - 1 - i, color);
    strip1.show(); strip2.show();
    delay(delayMs);
  }
  strip1.clear(); strip2.clear();
  strip1.show();  strip2.show();
}

// Color wipe left to right
void lightWipe(uint32_t color, int delayMs = 35) {
  for (int i = 0; i < Config::NUM_PIXELS; i++) {
    strip1.setPixelColor(i, color);
    strip2.setPixelColor(i, color);
    strip1.show(); strip2.show();
    delay(delayMs);
  }
}

// Breathe/pulse a color in and out
void lightPulse(uint8_t r, uint8_t g, uint8_t b, int steps = 10) {
  for (int i = 0; i <= steps; i++) {
    float t = (float)i / steps;
    setAllPixels(strip1.Color(r * t, g * t, b * t));
    delay(28);
  }
  for (int i = steps; i >= 0; i--) {
    float t = (float)i / steps;
    setAllPixels(strip1.Color(r * t, g * t, b * t));
    delay(28);
  }
}

// Non-blocking rainbow — call once per loop()
void updateRainbow() {
  for (int i = 0; i < Config::NUM_PIXELS; i++) {
    strip1.setPixelColor(i, wheelColor((i + rainbowIndex) & 255));
    strip2.setPixelColor(i, wheelColor((i + rainbowIndex) & 255));
  }
  strip1.show();
  strip2.show();
  rainbowIndex = (rainbowIndex + 1) & 255;
}

// ===============================================
// SENSOR FUNCTIONS
// ===============================================
long readUltrasonic(uint8_t trigPin, uint8_t echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH, 30000);
  return duration * 0.034 / 2; // cm
}

int readLaserDistance() {
  // laserSensor.begin() failed in initLaser() — don't call rangingTest()
  // on an uninitialized sensor object every loop. Without this guard a
  // failed sensor keeps returning whatever garbage happens to sit in this
  // (never-actually-written) local struct, which reads as a frozen,
  // physically-impossible distance instead of an honest "unavailable".
  if (!robotState.systemReady) return -1;

  VL53L0X_RangingMeasurementData_t measurement;
  laserSensor.rangingTest(&measurement, false);
  return (measurement.RangeStatus != 4) ? measurement.RangeMilliMeter : -1;
}

bool readButtonState() { return digitalRead(Config::BUTTON_PIN) == LOW; }

// A single ping occasionally misses its echo and reads 0 ("nothing there"),
// even with a real obstacle in range — that false "clear" reading is what
// was driving bad left/right turn choices. Ping twice and trust whichever
// reading actually saw something; only call it open if both pings miss.
long readUltrasonicChecked(uint8_t trigPin, uint8_t echoPin) {
  long a = readUltrasonic(trigPin, echoPin);
  delay(15);
  long b = readUltrasonic(trigPin, echoPin);
  if (a > 0 && b > 0) return min(a, b);
  if (a > 0) return a;
  if (b > 0) return b;
  return 0;
}

SensorReadings getAllSensorReadings() {
  SensorReadings r;
  r.laser    = readLaserDistance();
  r.us0      = readUltrasonic(Config::US0_TRIG, Config::US0_ECHO);
  r.us1      = readUltrasonic(Config::US1_TRIG, Config::US1_ECHO);
  r.btnState = readButtonState();
  return r;
}

// ===============================================
// MOTOR FUNCTIONS
// ===============================================
void setMotorSpeeds(int leftSpeed, int rightSpeed) {
  leftSpeed  = constrain(leftSpeed,  -255, 255);
  rightSpeed = constrain(rightSpeed, -255, 255);

  // Left motor
  if      (leftSpeed > 0) { digitalWrite(Config::MOTOR_LEFT_DIR1, HIGH); digitalWrite(Config::MOTOR_LEFT_DIR2, LOW);  analogWrite(Config::MOTOR_LEFT_PWM,  leftSpeed);  }
  else if (leftSpeed < 0) { digitalWrite(Config::MOTOR_LEFT_DIR1, LOW);  digitalWrite(Config::MOTOR_LEFT_DIR2, HIGH); analogWrite(Config::MOTOR_LEFT_PWM, -leftSpeed);  }
  else                    { digitalWrite(Config::MOTOR_LEFT_DIR1, LOW);  digitalWrite(Config::MOTOR_LEFT_DIR2, LOW);  analogWrite(Config::MOTOR_LEFT_PWM,  0);           }

  // Right motor
  if      (rightSpeed > 0) { digitalWrite(Config::MOTOR_RIGHT_DIR1, HIGH); digitalWrite(Config::MOTOR_RIGHT_DIR2, LOW);  analogWrite(Config::MOTOR_RIGHT_PWM,  rightSpeed);  }
  else if (rightSpeed < 0) { digitalWrite(Config::MOTOR_RIGHT_DIR1, LOW);  digitalWrite(Config::MOTOR_RIGHT_DIR2, HIGH); analogWrite(Config::MOTOR_RIGHT_PWM, -rightSpeed);  }
  else                     { digitalWrite(Config::MOTOR_RIGHT_DIR1, LOW);  digitalWrite(Config::MOTOR_RIGHT_DIR2, LOW);  analogWrite(Config::MOTOR_RIGHT_PWM,  0);            }
}

void executeMotorCommand(MotorDirection dir) {
  int s = robotState.motorSpeed;
  tankLeftSpeed = tankRightSpeed = 0;   // preset commands always supersede tank mode
  switch (dir) {
    case MotorDirection::FORWARD:  setMotorSpeeds( applyLeftTrim(s),  applyRightTrim(s)); break;
    case MotorDirection::BACKWARD: setMotorSpeeds(applyLeftTrim(-s), applyRightTrim(-s)); break;
    case MotorDirection::LEFT:     setMotorSpeeds(-s,  s); break;
    case MotorDirection::RIGHT:    setMotorSpeeds( s, -s); break;
    case MotorDirection::STOP:     setMotorSpeeds( 0,  0); break;
  }
  robotState.direction = dir;
}

// ===============================================
// OBSTACLE AVOIDANCE
// ===============================================
void obstacleAvoidance() {
  // US0 = fixed low  (ground-level obstacles, curbs)
  // US1 = servo high (forward + L/R scanning)
  long lowFront  = readUltrasonic(Config::US0_TRIG, Config::US0_ECHO);
  long highFront = readUltrasonic(Config::US1_TRIG, Config::US1_ECHO);
  int  laser     = readLaserDistance();

  bool tooClose = (lowFront  > 0 && lowFront  < Config::OBSTACLE_CM)
               || (highFront > 0 && highFront < Config::OBSTACLE_CM)
               || (laser     > 0 && laser     < Config::OBSTACLE_MM);

  // ── ALL CLEAR ──
  if (!tooClose) {
    executeMotorCommand(MotorDirection::FORWARD);
    setAllPixels(strip1.Color(0, 80, 255)); // calm blue = cruising
    return;
  }

  // ── OBSTACLE HIT ──
  executeMotorCommand(MotorDirection::STOP);

  bool lowObstacle  = (lowFront  > 0 && lowFront  < Config::OBSTACLE_CM);
  bool highObstacle = (highFront > 0 && highFront < Config::OBSTACLE_CM)
                   || (laser     > 0 && laser     < Config::OBSTACLE_MM);

  if (lowObstacle)  Serial.println("LOW_OBSTACLE");
  if (highObstacle) Serial.println("HIGH_OBSTACLE");

  // Police strobe stop effect
  lightAlternate(strip1.Color(255, 0, 0), strip1.Color(0, 0, 255), 4, 80);

  // ── SCAN LEFT then RIGHT with US1 (servo only) ──
  lightChase(strip1.Color(255, 100, 0), 50); // orange chase = scanning

  robotServo.write(Config::SERVO_LEFT);
  delay(400);
  long leftDist = readUltrasonicChecked(Config::US1_TRIG, Config::US1_ECHO);
  Serial.print("SCAN_LEFT:"); Serial.println(leftDist);
  setSplitPixels(strip1.Color(255, 100, 0), strip1.Color(0, 0, 0)); // illuminate left

  robotServo.write(Config::SERVO_RIGHT);
  delay(400);
  long rightDist = readUltrasonicChecked(Config::US1_TRIG, Config::US1_ECHO);
  Serial.print("SCAN_RIGHT:"); Serial.println(rightDist);
  setSplitPixels(strip1.Color(0, 0, 0), strip1.Color(255, 100, 0)); // illuminate right

  robotServo.write(Config::SERVO_CENTER);
  delay(300);

  // ── DECIDE ──
  bool leftOpen  = leftDist  > Config::CLEAR_CM || leftDist  == 0;
  bool rightOpen = rightDist > Config::CLEAR_CM || rightDist == 0;

  if (leftOpen && (!rightOpen || leftDist >= rightDist)) {
    // TURN LEFT
    setSplitPixels(strip1.Color(0, 0, 255), strip1.Color(0, 0, 40));
    playTone(Config::TONE_LEFT, 150);
    executeMotorCommand(MotorDirection::LEFT);
    delay(Config::TURN_MS);

  } else if (rightOpen) {
    // TURN RIGHT
    setSplitPixels(strip1.Color(0, 40, 0), strip1.Color(0, 255, 80));
    playTone(Config::TONE_RIGHT, 150);
    executeMotorCommand(MotorDirection::RIGHT);
    delay(Config::TURN_MS);

  } else {
    // BOTH BLOCKED — reverse with angry strobe then pick best side
    Serial.println("BOTH_BLOCKED");
    playTone(Config::TONE_REVERSE, 400);
    lightAlternate(strip1.Color(255, 0, 0), strip1.Color(255, 255, 255), 5, 90);
    executeMotorCommand(MotorDirection::BACKWARD);
    lightPulse(255, 0, 0); // red breathe while reversing

    if (leftDist >= rightDist) {
      setSplitPixels(strip1.Color(0, 0, 255), strip1.Color(0, 0, 40));
      executeMotorCommand(MotorDirection::LEFT);
    } else {
      setSplitPixels(strip1.Color(0, 40, 0), strip1.Color(0, 255, 80));
      executeMotorCommand(MotorDirection::RIGHT);
    }
    delay(Config::TURN_MS);
  }

  executeMotorCommand(MotorDirection::STOP);
  lightWipe(strip1.Color(0, 0, 0), 30); // clean wipe-off
}

// ===============================================
// MANUAL SCAN COMMANDS (called from Pi)
// ===============================================
long scanLeft() {
  robotServo.write(Config::SERVO_LEFT);
  delay(500);
  long dist = readUltrasonic(Config::US1_TRIG, Config::US1_ECHO);
  Serial.print("LEFT:"); Serial.println(dist);
  robotServo.write(Config::SERVO_CENTER);
  delay(500);
  return dist;
}

long scanRight() {
  robotServo.write(Config::SERVO_RIGHT);
  delay(500);
  long dist = readUltrasonic(Config::US1_TRIG, Config::US1_ECHO);
  Serial.print("RIGHT:"); Serial.println(dist);
  robotServo.write(Config::SERVO_CENTER);
  delay(500);
  return dist;
}

// ===============================================
// SERIAL COMMANDS
// ===============================================
// Takes a mutable char buffer (owned by handleSerialInput's static buf) —
// no String class anywhere in the serial path. This board runs at 92%
// flash / 75% static SRAM (503 bytes free per the compiler's own "Low
// memory available" warning); Arduino String heap-allocates on every
// readStringUntil()/substring()/copy, and with the web HUD's drive
// heartbeat resending a command every 300ms that was a lot of tiny
// alloc/free cycles for an AVR chip with no heap compactor — exactly the
// kind of memory corruption that can silently break sensor-reporting or
// hang unrelated code elsewhere (e.g. the VL53L0X init in initLaser()).
void processSerialCommand(char *cmd) {
  size_t len = strlen(cmd);
  while (len > 0 && isspace((unsigned char)cmd[len - 1])) cmd[--len] = '\0';
  while (isspace((unsigned char)*cmd)) cmd++;
  for (char *p = cmd; *p; p++) *p = toupper((unsigned char)*p);

       if (strcmp(cmd, "FORWARD") == 0)  executeMotorCommand(MotorDirection::FORWARD);
  else if (strcmp(cmd, "BACKWARD") == 0) executeMotorCommand(MotorDirection::BACKWARD);
  else if (strcmp(cmd, "LEFT") == 0)     executeMotorCommand(MotorDirection::LEFT);
  else if (strcmp(cmd, "RIGHT") == 0)    executeMotorCommand(MotorDirection::RIGHT);
  else if (strcmp(cmd, "STOP") == 0)     executeMotorCommand(MotorDirection::STOP);
  else if (strncmp(cmd, "SPEED:", 6) == 0) {
    robotState.motorSpeed = constrain(atoi(cmd + 6), 0, 255);
  }
  else if (strncmp(cmd, "TRIM:", 5) == 0) {
    wheelTrimPercent = constrain(atoi(cmd + 5), -50, 50);
  }
  // Independent per-motor drive (tank-style: Q/A = left, W/S = right).
  // Signed speed, positive = forward. Doesn't touch the other side.
  else if (strncmp(cmd, "LMOTOR:", 7) == 0) {
    tankLeftSpeed = constrain(atoi(cmd + 7), -255, 255);
    setMotorSpeeds(tankLeftSpeed, tankRightSpeed);
  }
  else if (strncmp(cmd, "RMOTOR:", 7) == 0) {
    tankRightSpeed = constrain(atoi(cmd + 7), -255, 255);
    setMotorSpeeds(tankLeftSpeed, tankRightSpeed);
  }
  else if (strcmp(cmd, "SCANLEFT") == 0)  { long d = scanLeft();  Serial.print("SCANLEFT:");  Serial.println(d); }
  else if (strcmp(cmd, "SCANRIGHT") == 0) { long d = scanRight(); Serial.print("SCANRIGHT:"); Serial.println(d); }
  // Arbitrary-angle servo sweep for lidar_sweep.py — moves US1 (the
  // servo-mounted ultrasonic) to `angle` and reports its reading, without
  // the fixed-3-position SCANLEFT/SCANRIGHT/obstacleAvoidance() recenter
  // behavior, so a caller can step through many angles for a fine-grained
  // sweep. Caller is responsible for recentering when done (SERVO:90).
  else if (strncmp(cmd, "SERVO:", 6) == 0) {
    int angle = constrain(atoi(cmd + 6), 0, 180);
    robotServo.write(angle);
    delay(150);  // let the servo settle before the ultrasonic reads a stable distance
    long d = readUltrasonicChecked(Config::US1_TRIG, Config::US1_ECHO);
    int laser = readLaserDistance();
    Serial.print("SWEEP:"); Serial.print(angle);
    Serial.print(","); Serial.print(d);
    Serial.print(","); Serial.println(laser);
  }
  else if (strcmp(cmd, "PING") == 0) { /* heartbeat only — resets the watchdog via handleSerialInput() */ }
  else if (strcmp(cmd, "AUTO_ON") == 0) {
    autonomousMode = true;
    Serial.println("AUTO_MODE_ON");
  }
  else if (strcmp(cmd, "AUTO_OFF") == 0) {
    autonomousMode = false;
    executeMotorCommand(MotorDirection::STOP);
    Serial.println("AUTO_MODE_OFF");
  }
  else if (strcmp(cmd, "WHOAMI") == 0) {
    Serial.println("I_AM_DEV00");
  }
}

void handleSerialInput() {
  static char buf[32];
  while (Serial.available()) {
    size_t len = Serial.readBytesUntil('\n', buf, sizeof(buf) - 1);
    buf[len] = '\0';
    lastCommandMs = millis();   // any line at all counts as "Pi is alive"
    processSerialCommand(buf);
  }
}

// ===============================================
// BUTTON HANDLER
// ===============================================
void handleButton(bool state) {
  static bool          lastState    = false;
  static unsigned long lastDebounce = 0;

  if (state != lastState) lastDebounce = millis();

  if ((millis() - lastDebounce) > 50) {
    if (state != robotState.btnPressed) {
      robotState.btnPressed = state;
      if (state) {
        playTone(Config::TONE_STARTUP);
        setAllPixels(strip1.Color(255, 0, 0));
      } else {
        stopTone();
        setAllPixels(strip1.Color(0, 0, 0));
      }
    }
  }
  lastState = state;
}

// ===============================================
// INIT HELPERS
// ===============================================
bool initLaser() {
  if (!laserSensor.begin()) {
    Serial.println(F("ERROR: VL53L0X init failed"));
    return false;
  }
  Serial.println(F("VL53L0X ready"));
  return true;
}

void initServo() {
  robotServo.attach(Config::SERVO_PIN);
  robotServo.write(Config::SERVO_CENTER);
  delay(500);
  const uint8_t testPositions[] = {45, 135, 90};
  for (uint8_t i = 0; i < 3; i++) {
    robotServo.write(testPositions[i]);
    delay(500);
  }
}

void initMotors() {
  pinMode(Config::MOTOR_RIGHT_PWM,  OUTPUT);
  pinMode(Config::MOTOR_RIGHT_DIR1, OUTPUT);
  pinMode(Config::MOTOR_RIGHT_DIR2, OUTPUT);
  pinMode(Config::MOTOR_LEFT_PWM,   OUTPUT);
  pinMode(Config::MOTOR_LEFT_DIR1,  OUTPUT);
  pinMode(Config::MOTOR_LEFT_DIR2,  OUTPUT);
}

void initSensors() {
  pinMode(Config::US0_TRIG,    OUTPUT);
  pinMode(Config::US0_ECHO,    INPUT);
  pinMode(Config::US1_TRIG,    OUTPUT);
  pinMode(Config::US1_ECHO,    INPUT);
  pinMode(Config::BUTTON_PIN,  INPUT_PULLUP);
}

void initAudio()  { pinMode(Config::BUZZER_PIN, OUTPUT); }

void initLights() {
  strip1.begin(); strip2.begin();
  strip1.show();  strip2.show();
}

// ===============================================
// SETUP
// ===============================================
void setup() {
  Serial.begin(Config::SERIAL_BAUD);
  while (!Serial);

  Serial.println(F("=== DEV00 Startup ==="));

  // Give the VL53L0X I2C init a hard timeout. Without this, a
  // disconnected/miswired/dead sensor leaves Wire's blocking calls
  // spinning forever inside laserSensor.begin() — hanging the whole
  // board before motors/servo/lights ever get to run. 25ms is generous
  // for a healthy bus; reset_with_timeout=true recovers the TWI hardware
  // state afterward so the rest of setup() can still proceed.
  Wire.begin();
  Wire.setWireTimeout(25000, true);

  robotState.systemReady = initLaser();
  initServo();
  initMotors();
  initSensors();
  initAudio();
  initLights();

  // Startup sequence
  playTone(Config::TONE_STARTUP, 500);
  lightWipe(strip1.Color(255, 255, 255), 40);
  delay(300);
  lightWipe(strip1.Color(0, 0, 0), 40);

  Serial.println(F("DEV00_READY"));
  lastCommandMs = millis();
}

// ===============================================
// LOOP
// ===============================================
void loop() {

  // Serial commands (AUTO_OFF, STOP, mode switches, ...) must always be
  // read, even while autonomousMode is true — otherwise the Pi can never
  // reach the Arduino to turn autonomous mode off again.
  handleSerialInput();

if (autonomousMode) {
  if (millis() - lastCommandMs > Config::AUTONOMOUS_WATCHDOG_MS) {
    // Pi has gone silent (crashed/killed/lost power) — don't keep driving blind.
    autonomousMode = false;
    executeMotorCommand(MotorDirection::STOP);
    Serial.println("WATCHDOG_STOP_NO_HEARTBEAT");
  } else {
    obstacleAvoidance();
  }
  return;
}

  SensorReadings readings = getAllSensorReadings();
  handleButton(readings.btnState);

  // Sensor print (non-blocking)
  if (millis() - lastSensorPrint >= Config::SENSOR_INTERVAL) {
    lastSensorPrint = millis();
    Serial.print("LASER:");       Serial.print(readings.laser);
    Serial.print("|US0:");        Serial.print(readings.us0);
    Serial.print("|US1:");        Serial.println(readings.us1);
  }

  // Button held — strobe white (non-blocking)
  if (robotState.btnPressed) {
    if (millis() - lastStrobe >= 100) {
      static bool strobeOn = false;
      setAllPixels(strobeOn ? strip1.Color(255, 255, 255) : strip1.Color(0, 0, 0));
      strobeOn   = !strobeOn;
      lastStrobe = millis();
    }
    return; // skip rainbow while button held
  }

  // Idle rainbow
  updateRainbow();
}
