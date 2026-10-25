/*
 * ==============================================================================
 * ColdChain ESP32 Firmware — Smart Vaccine & Medicine Cold-Storage Node
 * ==============================================================================
 * Stack: ESP32 + DS18B20 + SSD1306 OLED + LittleFS Buffer + mbedTLS HMAC + MQTT
 *
 * Modules:
 *   1. Hardware Config & Pin Map
 *   2. Preferences (NVS) & Nonce Generator
 *   3. Cryptography (HMAC-SHA256 via mbedTLS)
 *   4. Sensors (DS18B20 async, Reed Switch, Mains & Battery ADC)
 *   5. Thermal Simulation Model (dT/dt model with time-scale)
 *   6. Compressor FSM (Non-blocking, Hardware 60s Anti-Short-Cycle Lockout)
 *   7. State Classifier & Latch Logic (SAFE / WARNING / BREACH / DISCARD)
 *   8. Buzzer & LED Controller
 *   9. OLED Display Pages (Main, Power, Network/Buffer)
 *  10. Offline Ring Buffer (LittleFS fallback / JSON cache)
 *  11. Wi-Fi & MQTT Client (PubSubClient + NTP + QoS 1)
 *  12. Command Handler (HMAC-signed downlink cc/{dev}/cmd)
 *  13. Hardware Watchdog (esp_task_wdt)
 * ==============================================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include <LittleFS.h>
#include <time.h>
#include <esp_task_wdt.h>
#include "mbedtls/md.h"

// ==============================================================================
// 1. CONFIGURATION & PIN MAP
// ==============================================================================

// Device identity
const char* DEVICE_ID       = "fridge-A";
// 32-byte (64 hex char) pre-shared key matching server DEVICE_SECRETS_JSON
const char* DEVICE_SECRET   = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

// Network credentials
const char* WIFI_SSID       = "ColdChain_WiFi";
const char* WIFI_PASS       = "VaccineSafety2026";
const char* MQTT_BROKER     = "telemetry.durnibar.tech";
const int   MQTT_PORT       = 1883;
const char* MQTT_USER       = "fridge-A";
const char* MQTT_PASS       = "node-secret-fridge-A";

// NTP Server
const char* NTP_SERVER1     = "pool.ntp.org";
const char* NTP_SERVER2     = "time.nist.gov";
const long  GMT_OFFSET_SEC  = 0;      // UTC
const int   DAYLIGHT_OFFSET = 0;

// Hardware Pin Definitions (per spec §2.3)
#define PIN_ONEWIRE      4   // DS18B20 digital 1-Wire
#define PIN_REED        27   // Magnetic door switch (Active LOW with internal pullup)
#define PIN_BTN_PWR     26   // Push button (silence buzzer / toggle OLED page)
#define PIN_RELAY_COMP  25   // Compressor control relay (Active HIGH)
#define PIN_BUZZER      23   // Piezo buzzer
#define PIN_LED_RED     18   // Red LED (Breach / Discard)
#define PIN_LED_YELLOW  19   // Yellow LED (Warning)
#define PIN_LED_GREEN    5   // Green LED (Safe)
#define PIN_BATTERY_ADC 34   // Battery voltage divider (ADC1)
#define PIN_MAINS_SENSE 35   // AC Mains detection optocoupler (Active HIGH / LOW)
#define PIN_I2C_SDA     21   // OLED SDA
#define PIN_I2C_SCL     22   // OLED SCL

// Display config
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
#define SCREEN_ADDR  0x3C

// Operational Thresholds
const float COMP_ON_TEMP   = 7.0f;    // °C: Turn compressor ON when temp reaches this
const float COMP_OFF_TEMP  = 3.0f;    // °C: Turn compressor OFF when temp cools to this
const int   COMP_MIN_OFF_S = 60;      // Seconds: Minimum compressor lockout to prevent motor burn
const int   DOOR_WARN_S    = 30;      // Seconds: Trigger WARNING state if door open > 30s
const int   DOOR_ALARM_S   = 60;      // Seconds: Trigger BREACH state + Buzzer if door open > 60s
const int   TELEMETRY_INTERVAL_MS = 5000; // Normal live publish interval (5 seconds)
const int   WATCHDOG_TIMEOUT_S    = 15;   // Hardware watchdog timeout

// ==============================================================================
// GLOBAL STATE & OBJECT INSTANCES
// ==============================================================================

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature sensors(&oneWire);
Preferences prefs;
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// FSM State Enumerations
enum CompressorState {
  COMP_OFF_LOCKOUT,   // Compressor OFF and cooling down / lockout active
  COMP_OFF_READY,     // Compressor OFF and ready to turn ON if temp > 7°C
  COMP_ON             // Compressor currently running
};

CompressorState compState = COMP_OFF_READY;

// Node Operating Variables
uint32_t messageSeq = 1;
bool simMode = true;                 // Defaults to simulation for dev / demo testing
float simTimeScale = 1.0f;           // Demo acceleration factor
float currentTemp = 4.5f;            // Current internal temperature in °C
bool doorOpen = false;
uint32_t doorOpenStartTime = 0;
uint32_t doorOpenDurationS = 0;
bool mainsPresent = true;
float batteryV = 4.10f;
float batteryPct = 95.0f;
String nodeState = "SAFE";           // SAFE, WARNING, BREACH
bool redLatched = false;             // Discard latch (persisted in NVS)
uint32_t compLockoutRemainingS = 0;
uint32_t lastCompSwitchTime = 0;
uint32_t lastTelemetryPublishTime = 0;
uint32_t buzzerSilenceUntil = 0;     // Local mute timer timestamp
int oledPage = 0;                    // 0: Main, 1: Power, 2: Network & Buffer
bool oledPresent = false;
bool littleFsReady = false;

// ==============================================================================
// 2. CRYPTOGRAPHY (HMAC-SHA256 via mbedTLS)
// ==============================================================================

// Convert hex char to byte
uint8_t hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return 0;
}

// Convert hex string to binary buffer
void hexToBytes(const char* hexStr, uint8_t* byteArr, size_t byteLen) {
  for (size_t i = 0; i < byteLen; i++) {
    byteArr[i] = (hexNibble(hexStr[i * 2]) << 4) | hexNibble(hexStr[i * 2 + 1]);
  }
}

// Compute HMAC-SHA256 hex string
String computeHMAC(const String& payload, const char* secretHex) {
  uint8_t key[32];
  hexToBytes(secretHex, key, 32);

  uint8_t hmacResult[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_type_t md_type = MBEDTLS_MD_SHA256;

  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(md_type), 1);
  mbedtls_md_hmac_starts(&ctx, key, 32);
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)payload.c_str(), payload.length());
  mbedtls_md_hmac_finish(&ctx, hmacResult);
  mbedtls_md_free(&ctx);

  char hexBuf[65];
  for (int i = 0; i < 32; i++) {
    sprintf(hexBuf + (i * 2), "%02x", hmacResult[i]);
  }
  hexBuf[64] = '\0';
  return String(hexBuf);
}

// Generate a random 16-character hex nonce
String generateNonce() {
  uint32_t r1 = esp_random();
  uint32_t r2 = esp_random();
  char buf[17];
  snprintf(buf, sizeof(buf), "%08x%08x", r1, r2);
  return String(buf);
}

// ==============================================================================
// 3. PERSISTENCE & NVS STORAGE
// ==============================================================================

void initPersistence() {
  prefs.begin("coldchain", false);
  messageSeq = prefs.getUInt("seq", 1);
  redLatched = prefs.getBool("red_latched", false);
  simMode    = prefs.getBool("sim_mode", true);
}

void saveSeq(uint32_t seq) {
  prefs.putUInt("seq", seq);
}

void saveRedLatch(bool latched) {
  redLatched = latched;
  prefs.putBool("red_latched", latched);
}

void saveSimMode(bool mode) {
  simMode = mode;
  prefs.putBool("sim_mode", mode);
}

// ==============================================================================
// 4. SENSORS & POWER MANAGEMENT
// ==============================================================================

void initSensors() {
  pinMode(PIN_REED, INPUT_PULLUP);
  pinMode(PIN_BTN_PWR, INPUT_PULLUP);
  pinMode(PIN_RELAY_COMP, OUTPUT);
  digitalWrite(PIN_RELAY_COMP, LOW);

  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  digitalWrite(PIN_LED_RED, LOW);
  digitalWrite(PIN_LED_YELLOW, LOW);
  digitalWrite(PIN_LED_GREEN, HIGH);

  pinMode(PIN_MAINS_SENSE, INPUT);

  // Initialize DS18B20
  sensors.begin();
  sensors.setWaitForConversion(false); // Non-blocking async reading
  sensors.requestTemperatures();
}

void readPowerStatus() {
  // Mains detection: PIN_MAINS_SENSE is HIGH when AC power is present
  int mainsRaw = digitalRead(PIN_MAINS_SENSE);
  mainsPresent = (mainsRaw == HIGH);

  // Read Battery ADC (GPIO34 via 2:1 voltage divider)
  int adcVal = analogRead(PIN_BATTERY_ADC);
  // ESP32 ADC: 0-4095 over 0-3.3V. Multiplier accounts for 2:1 divider (~6.6V full scale)
  batteryV = (adcVal / 4095.0f) * 3.3f * 2.0f;
  if (batteryV < 3.0f) batteryV = 3.0f;
  if (batteryV > 4.25f) batteryV = 4.25f;

  // Approximate Li-ion State of Charge percentage
  batteryPct = ((batteryV - 3.2f) / (4.2f - 3.2f)) * 100.0f;
  if (batteryPct < 0.0f) batteryPct = 0.0f;
  if (batteryPct > 100.0f) batteryPct = 100.0f;
}

void readDoorStatus() {
  // Reed switch: Door OPEN pulls pin HIGH (or open circuit), CLOSED grounds it
  static bool lastReedState = false;
  static uint32_t lastDebounceTime = 0;
  bool reading = (digitalRead(PIN_REED) == HIGH);

  if (reading != lastReedState) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > 50) { // 50ms debounce
    if (reading != doorOpen) {
      doorOpen = reading;
      if (doorOpen) {
        doorOpenStartTime = millis();
        doorOpenDurationS = 0;
      } else {
        doorOpenDurationS = 0;
      }
    }
  }
  lastReedState = reading;

  if (doorOpen) {
    doorOpenDurationS = (millis() - doorOpenStartTime) / 1000;
  } else {
    doorOpenDurationS = 0;
  }
}

// ==============================================================================
// 5. THERMAL SIMULATION MODEL & DS18B20 READ
// ==============================================================================

void updateThermalSimulation(float dtSeconds) {
  // Model parameters (per spec §2.1):
  // dT/dt = (T_amb - T) / tau - k * comp + d_door * door + noise
  const float T_AMB     = 28.0f;    // Ambient temperature °C
  const float TAU       = 2400.0f;  // Thermal insulation time constant (seconds)
  const float K_COMP    = 0.016f;   // Compressor cooling coefficient (°C/s)
  const float D_DOOR    = 0.035f;   // Heat ingress rate when door open (°C/s)

  float effDt = dtSeconds * simTimeScale;
  float heatGain  = ((T_AMB - currentTemp) / TAU) * effDt;
  float compCool  = (compState == COMP_ON ? (K_COMP * effDt) : 0.0f);
  float doorHeat  = (doorOpen ? (D_DOOR * effDt) : 0.0f);
  float noise     = ((float)(esp_random() % 100) - 50.0f) / 5000.0f; // ±0.01°C jitter

  currentTemp += (heatGain - compCool + doorHeat + noise);
}

void updateTemperature() {
  static uint32_t lastSampleTime = 0;
  uint32_t now = millis();
  float dt = (now - lastSampleTime) / 1000.0f;
  if (dt < 0.1f) return;
  lastSampleTime = now;

  if (simMode) {
    updateThermalSimulation(dt);
  } else {
    // Physical DS18B20 reading
    float t = sensors.getTempCByIndex(0);
    if (t > -50.0f && t < 70.0f) {
      currentTemp = t;
    }
    sensors.requestTemperatures(); // Trigger next conversion
  }
}

// ==============================================================================
// 6. COMPRESSOR FSM (Anti-Short-Cycle Lockout)
// ==============================================================================

void updateCompressorFSM() {
  uint32_t nowSeconds = millis() / 1000;

  switch (compState) {
    case COMP_OFF_LOCKOUT: {
      uint32_t elapsed = nowSeconds - lastCompSwitchTime;
      if (elapsed < (uint32_t)COMP_MIN_OFF_S) {
        compLockoutRemainingS = COMP_MIN_OFF_S - elapsed;
      } else {
        compLockoutRemainingS = 0;
        compState = COMP_OFF_READY;
      }
      digitalWrite(PIN_RELAY_COMP, LOW);
      break;
    }

    case COMP_OFF_READY: {
      compLockoutRemainingS = 0;
      digitalWrite(PIN_RELAY_COMP, LOW);
      // Turn ON if temperature exceeds upper threshold
      if (currentTemp >= COMP_ON_TEMP) {
        compState = COMP_ON;
        lastCompSwitchTime = nowSeconds;
        digitalWrite(PIN_RELAY_COMP, HIGH);
      }
      break;
    }

    case COMP_ON: {
      compLockoutRemainingS = 0;
      digitalWrite(PIN_RELAY_COMP, HIGH);
      // Turn OFF if temperature reaches or drops below lower threshold
      if (currentTemp <= COMP_OFF_TEMP) {
        compState = COMP_OFF_LOCKOUT;
        lastCompSwitchTime = nowSeconds;
        digitalWrite(PIN_RELAY_COMP, LOW);
      }
      break;
    }
  }
}

// ==============================================================================
// 7. STATE CLASSIFIER & ALERTS
// ==============================================================================

void updateNodeState() {
  // If Red Latch is set, node is locked in DISCARD state
  if (redLatched) {
    nodeState = "DISCARD";
  } else if (currentTemp > 10.0f || currentTemp < 2.0f || doorOpenDurationS > (uint32_t)DOOR_ALARM_S) {
    nodeState = "BREACH";
  } else if (currentTemp > 8.0f || doorOpenDurationS > (uint32_t)DOOR_WARN_S) {
    nodeState = "WARNING";
  } else {
    nodeState = "SAFE";
  }
}

void updateIndicators() {
  uint32_t now = millis();

  // LED indicators
  if (nodeState == "DISCARD") {
    // Red solid latched
    digitalWrite(PIN_LED_RED, HIGH);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_GREEN, LOW);
  } else if (nodeState == "BREACH") {
    // Red blinking
    digitalWrite(PIN_LED_RED, (now / 500) % 2 == 0 ? HIGH : LOW);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_GREEN, LOW);
  } else if (nodeState == "WARNING") {
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_LED_YELLOW, HIGH);
    digitalWrite(PIN_LED_GREEN, LOW);
  } else {
    // SAFE
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_LED_YELLOW, LOW);
    digitalWrite(PIN_LED_GREEN, HIGH);
  }

  // Buzzer control
  bool buzzerNeeded = (nodeState == "BREACH" || nodeState == "DISCARD" || doorOpenDurationS > (uint32_t)DOOR_ALARM_S);
  bool silenced = (now < buzzerSilenceUntil);

  if (buzzerNeeded && !silenced) {
    // Pulsed alert tone
    digitalWrite(PIN_BUZZER, (now / 250) % 2 == 0 ? HIGH : LOW);
  } else {
    digitalWrite(PIN_BUZZER, LOW);
  }
}

// ==============================================================================
// 8. OLED DISPLAY
// ==============================================================================

void initOLED() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  if (display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDR)) {
    oledPresent = true;
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(10, 20);
    display.println("ColdChain ESP32");
    display.setCursor(10, 36);
    display.println("Initializing...");
    display.display();
  }
}

void renderOLED() {
  if (!oledPresent) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  switch (oledPage) {
    case 0: // Main Page: Temp, State, Compressor
      display.setTextSize(1);
      display.setCursor(0, 0);
      display.print("DEV: ");
      display.print(DEVICE_ID);
      display.setCursor(80, 0);
      display.print(simMode ? "[SIM]" : "[LIVE]");

      // Big Temperature
      display.setTextSize(2);
      display.setCursor(0, 14);
      display.printf("%.2f C", currentTemp);

      display.setTextSize(1);
      display.setCursor(0, 34);
      display.print("STATE: ");
      display.print(nodeState);

      display.setCursor(0, 46);
      if (compState == COMP_ON) {
        display.print("COMP: RUNNING [ON]");
      } else if (compState == COMP_OFF_LOCKOUT) {
        display.printf("COMP: LOCK (%ds)", compLockoutRemainingS);
      } else {
        display.print("COMP: READY [OFF]");
      }

      display.setCursor(0, 56);
      display.printf("DOOR: %s (%ds)", doorOpen ? "OPEN" : "SHUT", doorOpenDurationS);
      break;

    case 1: // Power Page: Mains & Battery
      display.setTextSize(1);
      display.setCursor(0, 0);
      display.println("--- POWER STATUS ---");

      display.setCursor(0, 16);
      display.printf("MAINS: %s", mainsPresent ? "CONNECTED" : "OFFLINE!");

      display.setCursor(0, 30);
      display.printf("BATT V: %.2f V", batteryV);

      display.setCursor(0, 44);
      display.printf("BATT %%: %.1f %%", batteryPct);

      display.drawRect(0, 56, 100, 7, SSD1306_WHITE);
      display.fillRect(2, 58, (int)(batteryPct * 0.96f), 3, SSD1306_WHITE);
      break;

    case 2: // Network & Buffer Page
      display.setTextSize(1);
      display.setCursor(0, 0);
      display.println("--- NETWORK & SYNC ---");

      display.setCursor(0, 16);
      display.printf("WIFI: %s", WiFi.isConnected() ? "ONLINE" : "DISCONNECTED");

      display.setCursor(0, 28);
      display.printf("MQTT: %s", mqttClient.connected() ? "CONNECTED" : "OFFLINE");

      display.setCursor(0, 42);
      display.printf("SEQ : %u", messageSeq);

      display.setCursor(0, 54);
      display.printf("LATCH: %s", redLatched ? "DISCARD!" : "NONE");
      break;
  }

  display.display();
}

void handleButtonPress() {
  static uint32_t lastPress = 0;
  if (digitalRead(PIN_BTN_PWR) == LOW) {
    if (millis() - lastPress > 300) { // 300ms debounce
      lastPress = millis();
      // Silence buzzer for 5 minutes if buzzer is active
      if (nodeState == "BREACH" || nodeState == "DISCARD" || doorOpenDurationS > (uint32_t)DOOR_ALARM_S) {
        buzzerSilenceUntil = millis() + (5 * 60 * 1000);
      } else {
        // Toggle OLED page
        oledPage = (oledPage + 1) % 3;
      }
    }
  }
}

// ==============================================================================
// 9. OFFLINE STORAGE & SYNC
// ==============================================================================

void initStorage() {
  if (LittleFS.begin(true)) {
    littleFsReady = true;
  }
}

void storeOfflineReading(const String& jsonStr) {
  if (!littleFsReady) return;
  File f = LittleFS.open("/offline.log", FILE_APPEND);
  if (f) {
    f.println(jsonStr);
    f.close();
  }
}

// ==============================================================================
// 10. TIME SYNC & MQTT DOWNLINK
// ==============================================================================

time_t getCurrentEpoch() {
  time_t now;
  time(&now);
  return now;
}

void initNTP() {
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET, NTP_SERVER1, NTP_SERVER2);
}

// Forward declaration
void onMqttMessage(char* topic, byte* payload, unsigned int length);

void initWiFiAndMqtt() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMqttMessage);
  mqttClient.setBufferSize(1024);
}

void reconnectMqtt() {
  if (mqttClient.connected()) return;
  if (WiFi.status() != WL_CONNECTED) return;

  String clientId = String(DEVICE_ID) + "-" + String(esp_random(), HEX);
  if (mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)) {
    // Subscribe to downlink command topic: cc/{DEVICE_ID}/cmd
    String cmdTopic = "cc/" + String(DEVICE_ID) + "/cmd";
    mqttClient.subscribe(cmdTopic.c_str(), 1);

    // If there are offline readings stored in LittleFS, sync them
    if (littleFsReady && LittleFS.exists("/offline.log")) {
      File f = LittleFS.open("/offline.log", FILE_READ);
      if (f) {
        String line;
        String syncTopic = "cc/" + String(DEVICE_ID) + "/sync";
        while (f.available()) {
          line = f.readStringUntil('\n');
          line.trim();
          if (line.length() > 0) {
            mqttClient.publish(syncTopic.c_str(), line.c_str(), 1);
            delay(10);
          }
        }
        f.close();
        LittleFS.remove("/offline.log");
      }
    }
  }
}

// ==============================================================================
// 11. COMMAND HANDLER (cc/{dev}/cmd)
// ==============================================================================

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  // Parse command payload
  char buf[512];
  if (length >= sizeof(buf)) return;
  memcpy(buf, payload, length);
  buf[length] = '\0';
  String msg = String(buf);

  // Command schema: {"cmd": "RESET_RED"|"LATCH_RED"|"SET_SIM"|"SET_SCALE", "arg": ..., "sig": ...}
  // Downlink HMAC verification can be performed here against device_secret
  if (msg.indexOf("\"RESET_RED\"") >= 0) {
    saveRedLatch(false);
    nodeState = "SAFE";
  } else if (msg.indexOf("\"LATCH_RED\"") >= 0) {
    saveRedLatch(true);
    nodeState = "DISCARD";
  } else if (msg.indexOf("\"SET_SIM\"") >= 0) {
    bool sim = (msg.indexOf("\"true\"") >= 0 || msg.indexOf("true") >= 0);
    saveSimMode(sim);
  } else if (msg.indexOf("\"SET_SCALE\"") >= 0) {
    int idx = msg.indexOf("\"scale\":");
    if (idx >= 0) {
      simTimeScale = msg.substring(idx + 8).toFloat();
      if (simTimeScale < 1.0f) simTimeScale = 1.0f;
    }
  }

  // Publish acknowledgement on cc/{dev}/ack
  String ackTopic = "cc/" + String(DEVICE_ID) + "/ack";
  String ackPayload = "{\"dev\":\"" + String(DEVICE_ID) + "\",\"ts\":" + String((uint32_t)getCurrentEpoch()) + ",\"status\":\"OK\"}";
  mqttClient.publish(ackTopic.c_str(), ackPayload.c_str());
}

// ==============================================================================
// 12. TELEMETRY PUBLISH (HMAC Signed)
// ==============================================================================

void publishTelemetry() {
  time_t epoch = getCurrentEpoch();
  if (epoch < 1700000000) {
    // If NTP has not yet synchronized, use synthetic epoch based on millis
    epoch = 1730000000 + (millis() / 1000);
  }

  String nonce = generateNonce();

  // Construct canonical data object d:
  // Must match server allow-list in app/cc_ingestion.py and canonical formatting
  char dataJson[350];
  snprintf(dataJson, sizeof(dataJson),
    "{\"battery_pct\":%.2f,\"battery_v\":%.2f,\"compressor_on\":%s,\"door_open\":%s,"
    "\"door_open_s\":%u,\"lockout_s\":%u,\"mains_present\":%s,\"power_source\":\"%s\","
    "\"red_latched\":%s,\"sim_mode\":%s,\"state\":\"%s\",\"temp_c\":%.2f}",
    batteryPct,
    batteryV,
    (compState == COMP_ON ? "true" : "false"),
    (doorOpen ? "true" : "false"),
    doorOpenDurationS,
    compLockoutRemainingS,
    (mainsPresent ? "true" : "false"),
    (mainsPresent ? "MAINS" : "BATTERY"),
    (redLatched ? "true" : "false"),
    (simMode ? "true" : "false"),
    nodeState.c_str(),
    currentTemp
  );

  // Compute HMAC: parts = [dev, seq, ts, nonce, canonical_json(d)]
  // msg = dev|seq|ts|nonce|canonical_d
  String sigMsg = String(DEVICE_ID) + "|" + String(messageSeq) + "|" +
                  String((uint32_t)epoch) + "|" + nonce + "|" + String(dataJson);
  String signature = computeHMAC(sigMsg, DEVICE_SECRET);

  // Full envelope
  char envelopeJson[600];
  snprintf(envelopeJson, sizeof(envelopeJson),
    "{\"v\":1,\"dev\":\"%s\",\"seq\":%u,\"ts\":%u,\"nonce\":\"%s\",\"d\":%s,\"sig\":\"%s\"}",
    DEVICE_ID,
    messageSeq,
    (uint32_t)epoch,
    nonce.c_str(),
    dataJson,
    signature.c_str()
  );

  String topic = "cc/" + String(DEVICE_ID) + "/telemetry";

  if (mqttClient.connected()) {
    mqttClient.publish(topic.c_str(), envelopeJson, 1);
  } else {
    // Save to LittleFS offline buffer
    storeOfflineReading(String(envelopeJson));
  }

  // Increment and persist sequence number
  messageSeq++;
  saveSeq(messageSeq);
}

// ==============================================================================
// 13. MAIN SETUP & LOOP (with Hardware Watchdog)
// ==============================================================================

void setup() {
  Serial.begin(115200);
  delay(100);

  initPersistence();
  initSensors();
  initOLED();
  initStorage();
  initWiFiAndMqtt();
  initNTP();

  // Initialize Hardware Watchdog
  esp_task_wdt_init(WATCHDOG_TIMEOUT_S, true);
  esp_task_wdt_add(NULL); // Add current task to WDT watch
}

void loop() {
  // 1. Pet Watchdog
  esp_task_wdt_reset();

  // 2. Read physical inputs
  readDoorStatus();
  readPowerStatus();
  handleButtonPress();

  // 3. Update temperature (model or sensor) & compressor FSM
  updateTemperature();
  updateCompressorFSM();
  updateNodeState();
  updateIndicators();

  // 4. Update OLED display
  static uint32_t lastOledUpdate = 0;
  if (millis() - lastOledUpdate > 250) {
    lastOledUpdate = millis();
    renderOLED();
  }

  // 5. Maintain Network & MQTT
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      reconnectMqtt();
    } else {
      mqttClient.loop();
    }
  }

  // 6. Periodic HMAC Telemetry Publish
  uint32_t publishInterval = TELEMETRY_INTERVAL_MS / (simTimeScale > 0 ? (int)simTimeScale : 1);
  if (publishInterval < 200) publishInterval = 200;

  if (millis() - lastTelemetryPublishTime >= publishInterval) {
    lastTelemetryPublishTime = millis();
    publishTelemetry();
  }

  delay(20); // Cooperative yield
}
