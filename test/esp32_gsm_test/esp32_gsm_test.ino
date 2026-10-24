// Select your modem before including TinyGSM
#define TINY_GSM_MODEM_SIM800
#define TINY_GSM_RX_BUFFER 1024

#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==============================================================================
// USER CONFIGURATION (Matches scripts/test_vps.py)
// ==============================================================================
// 1. Cellular APN (e.g., "gpinternet", "blweb", "internet", etc.)
const char* apn = "YOUR_APN";
const char* gprsUser = "";
const char* gprsPass = "";

// 2. MQTT Broker settings (Port 1883 for plain MQTT, 8883 for TLS)
const char* mqtt_server = "telemetry.durnibar.tech";
const int mqtt_port = 1883;

// 3. Registered Device Credentials (from IoT-Telemetry-Hub)
const char* device_id = "TEST_02";
const char* mqtt_user = "TEST_02";
const char* mqtt_password = "YOUR_MQTT_PASSWORD";

// 4. SIM800L Hardware Pins (Using ESP32 HardwareSerial 1)
#define RX_PIN 16
#define TX_PIN 17
// ==============================================================================

HardwareSerial SerialAT(1);
TinyGsm modem(SerialAT);
TinyGsmClient gsmClient(modem);
PubSubClient client(gsmClient);

unsigned long lastMsg = 0;
int messageCount = 0;

// Generates a standard RFC 4122 v4 UUID using ESP32 hardware RNG
String generateUUID() {
  char uuidStr[37];
  uint32_t d1 = esp_random();
  uint32_t d2 = esp_random();
  uint32_t d3 = esp_random();
  uint32_t d4 = esp_random();
  snprintf(uuidStr, sizeof(uuidStr), "%08x-%04x-4%03x-%04x-%04x%08x",
           d1, (d2 & 0xFFFF), ((d2 >> 16) & 0x0FFF),
           ((d3 & 0x3FFF) | 0x8000), ((d3 >> 16) & 0xFFFF), d4);
  return String(uuidStr);
}

void setup_modem() {
  SerialAT.begin(9600, SERIAL_8N1, RX_PIN, TX_PIN);
  delay(3000);

  Serial.println("[MODEM] Initializing SIM800L...");
  modem.restart();

  String modemInfo = modem.getModemInfo();
  Serial.print("[MODEM] Info: ");
  Serial.println(modemInfo);

  Serial.print("[MODEM] Waiting for cellular network...");
  if (!modem.waitForNetwork(60000L)) {
    Serial.println(" FAIL! Check SIM card & antenna.");
    while (true) { delay(1000); }
  }
  Serial.println(" Connected!");

  int csq = modem.getSignalQuality();
  Serial.print("[MODEM] Signal Quality (CSQ): ");
  Serial.print(csq);
  Serial.println(" / 31");

  Serial.print("[GPRS] Connecting to APN: ");
  Serial.println(apn);
  if (!modem.gprsConnect(apn, gprsUser, gprsPass)) {
    Serial.println("[GPRS] Connection failed!");
    while (true) { delay(1000); }
  }
  Serial.println("[GPRS] Connected! IP: " + modem.getLocalIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("[MQTT] Connecting to ");
    Serial.print(mqtt_server);
    Serial.print(":");
    Serial.print(mqtt_port);
    Serial.print(" as device: ");
    Serial.print(device_id);
    Serial.print("... ");

    String clientId = "ESP32-GSM-" + String(random(0xffff), HEX);

    if (client.connect(clientId.c_str(), mqtt_user, mqtt_password)) {
      Serial.println("CONNECTED!");
    } else {
      Serial.print("FAILED (rc=");
      Serial.print(client.state());
      Serial.println("). Retrying in 5 seconds...");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  randomSeed(analogRead(0));

  Serial.println("\n==========================================");
  Serial.println("   ESP32 + SIM800L MQTT Telemetry Node   ");
  Serial.println("==========================================");

  setup_modem();
  client.setServer(mqtt_server, mqtt_port);
  client.setBufferSize(512);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // Send telemetry every 10 seconds (matches test_vps.py interval)
  if (now - lastMsg > 10000) {
    lastMsg = now;
    messageCount++;

    // Generate simulated sensor values identical to test_vps.py
    float temperature = 24.0 + (random(0, 80) / 10.0);    // 24.0 - 32.0 C
    float humidity    = 50.0 + (random(0, 350) / 10.0);   // 50.0 - 85.0 %
    float systemTemp  = 35.0 + (random(0, 100) / 10.0);   // 35.0 - 45.0 C (health check)
    float npk         = 10.0 + (random(0, 800) / 10.0);   // 10.0 - 90.0

    // Construct JSON payload adhering to the telemetry contract
    JsonDocument doc;
    doc["message_id"] = generateUUID();

    JsonObject values = doc["values"].to<JsonObject>();
    values["temperature"] = temperature;
    values["humidity"]    = humidity;
    values["systemTemp"]  = systemTemp;
    values["NPK"]         = npk;

    char payload[384];
    serializeJson(doc, payload);

    String topic = "devices/" + String(device_id) + "/telemetry";

    Serial.println("\n[SEND] Publishing QoS 1 telemetry to: " + topic);
    Serial.println(payload);

    if (client.publish(topic.c_str(), payload)) {
      Serial.println("[ACK] Publish acknowledged by broker!");
    } else {
      Serial.println("[ERROR] Publish failed!");
    }
    Serial.println("------------------------------------------");
  }
}
