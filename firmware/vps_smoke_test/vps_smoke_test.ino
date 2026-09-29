// ESP32 / ESP32-S3 smoke test. Libraries: PubSubClient, ArduinoJson 7.
// Serial Monitor: 115200. Publishes simulated data every 10 seconds.
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include <time.h>

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "YOUR_VPS_IP_OR_MQTT_HOSTNAME";
const char* DEVICE_ID = "ESP32_TEST_01";
const char* MQTT_PASSWORD = "YOUR_DEVICE_MQTT_PASSWORD";

// Match the VPS broker configuration. HTTPS on the dashboard does not enable MQTT TLS.
// Plain MQTT should only be used over a trusted/private test network.
constexpr bool USE_TLS = false;
constexpr uint16_t MQTT_PORT = 1883; // Typically 8883 for a configured TLS listener.
const char* ROOT_CA = R"PEM(REPLACE_WITH_BROKER_CA_CERTIFICATE_IF_USING_TLS)PEM";

WiFiClient plainSocket;
WiFiClientSecure secureSocket;
PubSubClient mqtt;
String topic;
String clientId;
uint32_t lastConnect = 0, lastSample = 0, lastWifiRetry = 0;
uint32_t sentCount = 0;
bool bufferReady = false;

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n[BOOT] VPS smoke test; all sensor readings are simulated.");
  topic = String("devices/") + DEVICE_ID + "/telemetry";
  clientId = String("smoke-") + DEVICE_ID;
  if (USE_TLS) {
    secureSocket.setCACert(ROOT_CA); // Never disable certificate validation.
    mqtt.setClient(secureSocket);
  } else {
    mqtt.setClient(plainSocket);
  }
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setSocketTimeout(5);
  bufferReady = mqtt.setBufferSize(1024);
  if (!bufferReady) Serial.println("[ERROR] MQTT buffer allocation failed.");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  if (USE_TLS) configTime(0, 0, "pool.ntp.org", "time.google.com");
  lastWifiRetry = millis();
  lastConnect = millis() - 5000;
  Serial.printf("[CONFIG] host=%s port=%u TLS=%s device=%s\n",
                MQTT_HOST, MQTT_PORT, USE_TLS ? "yes" : "no", DEVICE_ID);
}

void loop() {
  uint32_t now = millis();
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWifiRetry >= 30000) {
      Serial.printf("[WIFI] Not ready; status=%d. Restarting connection attempt.\n", (int)WiFi.status());
      WiFi.disconnect(false, false);
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastWifiRetry = millis();
    }
    delay(10);
    return;
  }
  if (!bufferReady) { delay(100); return; }
  if (!mqtt.connected()) {
    if (now - lastConnect >= 5000) {
      lastConnect = now;
      Serial.printf("[CONNECT] WiFi IP=%s; MQTT=%s:%u\n",
                    WiFi.localIP().toString().c_str(), MQTT_HOST, MQTT_PORT);
      if (mqtt.connect(clientId.c_str(), DEVICE_ID, MQTT_PASSWORD)) {
        Serial.println("[MQTT OK] Broker accepted connection.");
      } else {
        Serial.printf("[MQTT ERROR] state=%d (-2=TCP/TLS failure, -4=timeout, 4=credentials, 5=authorization)\n", mqtt.state());
      }
    }
    delay(10);
    return;
  }
  mqtt.loop();
  if (now - lastSample < 10000) { delay(2); return; }
  lastSample = now;

  // A fresh UUID avoids duplicate IDs after reset. The server deduplicates by ID.
  uint8_t b[16];
  esp_fill_random(b, sizeof(b));
  b[6] = (b[6] & 15) | 64;
  b[8] = (b[8] & 63) | 128;
  char id[37];
  snprintf(id, sizeof(id), "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
  JsonDocument doc;
  doc["message_id"] = id;
  doc["values"]["temperature"] = random(240, 320) / 10.0;
  doc["values"]["humidity"] = random(500, 850) / 10.0;
  doc["values"]["systemTemp"] = random(350, 450) / 10.0;
  char payload[512];
  if (doc.overflowed() || measureJson(doc) >= sizeof(payload)) {
    Serial.println("[JSON ERROR] Sample exceeds buffer capacity.");
    return;
  }
  size_t size = serializeJson(doc, payload, sizeof(payload));
  Serial.printf("[PAYLOAD] %s\n", payload);
  bool sent = mqtt.publish(topic.c_str(), (const uint8_t*)payload, size, false);
  if (sent) sentCount++;
  Serial.printf("[PUBLISH] %s total_local_sends=%lu state=%d\n",
                sent ? "SENT" : "FAILED", (unsigned long)sentCount, mqtt.state());
  Serial.println("[VERIFY] QoS 0 has no acknowledgement. Refresh Stored Data to confirm database storage.");
}
