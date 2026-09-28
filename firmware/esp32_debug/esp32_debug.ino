// ESP32 test publisher. Serial Monitor: 115200 baud.
// Libraries: PubSubClient and ArduinoJson (6 or 7).
// Sends simulated readings every 10 seconds. Plain MQTT for a trusted test network.
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <esp_system.h>

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "YOUR_SERVER_IP_OR_DOMAIN";
const uint16_t MQTT_PORT = 1883;
const char* DEVICE_ID = "ESP32_NODE_01";
const char* MQTT_PASSWORD = "your_secure_password";

constexpr bool DEBUG_MODE = true;
constexpr uint32_t SEND_INTERVAL_MS = 10000;
constexpr uint32_t RETRY_INTERVAL_MS = 5000;
constexpr uint16_t MQTT_BUFFER_SIZE = 2048;
constexpr size_t PAYLOAD_SIZE = 1536;

WiFiClient network;
PubSubClient mqtt(network);
String topic;
String clientId;
char pendingPayload[PAYLOAD_SIZE];
size_t pendingLength = 0;
uint32_t lastSample = 0;
uint32_t lastPublishAttempt = 0;
uint32_t lastMqttAttempt = 0;
uint32_t lastWifiAttempt = 0;
uint32_t published = 0;
uint32_t failures = 0;
int previousWifiStatus = -1;
bool wasMqttConnected = false;
bool bufferReady = false;

const char* mqttStateText(int state) {
  switch (state) {
    case -4: return "Connection timeout: broker did not respond";
    case -3: return "Connection lost";
    case -2: return "TCP connection failed: check DNS/IP, port, firewall and broker";
    case -1: return "Disconnected";
    case 0: return "Connected (not a publish acknowledgement)";
    case 1: return "Broker rejected MQTT protocol version";
    case 2: return "Broker rejected client ID";
    case 3: return "Broker unavailable";
    case 4: return "Broker rejected username/password";
    case 5: return "Broker denied authorization";
    default: return "Unknown MQTT connection state";
  }
}

void makeMessageId(char* output, size_t size) {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  snprintf(output, size,
           "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
           bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15]);
}

bool prepareSample() {
#if ARDUINOJSON_VERSION_MAJOR >= 7
  JsonDocument doc;
#else
  StaticJsonDocument<1536> doc;
#endif
  char messageId[37];
  makeMessageId(messageId, sizeof(messageId));
  doc["message_id"] = messageId;
  JsonObject values = doc["values"].to<JsonObject>();
  values["temperature"] = 24.0 + random(-10, 10) / 10.0;
  values["humidity"] = 50.0 + random(-50, 50) / 10.0;
  values["systemTemp"] = 40.0 + random(-20, 20) / 10.0;

  if (doc.overflowed()) {
    Serial.println("[JSON ERROR] Document capacity exceeded; sample not published.");
    return false;
  }
  size_t length = measureJson(doc);
  if (length >= sizeof(pendingPayload)) {
    Serial.printf("[JSON ERROR] Need %u bytes plus terminator; buffer=%u.\n",
                  (unsigned)length, (unsigned)sizeof(pendingPayload));
    return false;
  }
  // PubSubClient requires space for its maximum header, topic length and payload.
  size_t packetSize = 5 + 2 + topic.length() + length;
  if (packetSize > mqtt.getBufferSize()) {
    Serial.printf("[MQTT ERROR] Packet needs %u bytes; MQTT buffer=%u.\n",
                  (unsigned)packetSize, (unsigned)mqtt.getBufferSize());
    return false;
  }
  pendingLength = serializeJson(doc, pendingPayload, sizeof(pendingPayload));
  if (pendingLength != length) {
    pendingLength = 0;
    Serial.println("[JSON ERROR] Serialization length mismatch.");
    return false;
  }
  if (DEBUG_MODE) {
    Serial.printf("[SAMPLE] topic=%s bytes=%u heap=%u RSSI=%d dBm\n",
                  topic.c_str(), (unsigned)pendingLength, (unsigned)ESP.getFreeHeap(),
                  (int)WiFi.RSSI());
    Serial.println(pendingPayload);
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[BOOT] ESP32 telemetry DEBUG publisher; simulated data every 10 seconds.");
  Serial.println("[INFO] QoS 0: local send success does NOT prove broker acceptance or database storage.");
  topic = String("devices/") + DEVICE_ID + "/telemetry";
  WiFi.mode(WIFI_STA);
  clientId = String("debug-") + WiFi.macAddress();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);
  bufferReady = mqtt.setBufferSize(MQTT_BUFFER_SIZE);
  if (!bufferReady) Serial.println("[FATAL] Cannot allocate MQTT buffer; publishing disabled.");
  Serial.printf("[CONFIG] broker=%s:%u device=%s topic=%s\n",
                MQTT_HOST, MQTT_PORT, DEVICE_ID, topic.c_str());
  Serial.println("[WIFI] Starting connection (passwords are never printed).");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiAttempt = millis();
  lastMqttAttempt = millis() - RETRY_INTERVAL_MS;
}

void loop() {
  uint32_t now = millis();
  int wifiStatus = WiFi.status();
  if (wifiStatus != previousWifiStatus) {
    Serial.printf("[WIFI] status=%d (3=connected, 1=SSID unavailable, 4=connect failed, 6=disconnected)\n", wifiStatus);
    previousWifiStatus = wifiStatus;
    if (wifiStatus == WL_CONNECTED) {
      Serial.printf("[WIFI] IP=%s RSSI=%d dBm\n", WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
      lastMqttAttempt = now - RETRY_INTERVAL_MS;
    } else {
      network.stop();
      wasMqttConnected = false;
    }
  }
  if (wifiStatus != WL_CONNECTED) {
    if (now - lastWifiAttempt >= 15000) {
      lastWifiAttempt = now;
      Serial.println("[WIFI] Still offline; retrying. Check SSID, password and signal.");
      WiFi.reconnect();
    }
    delay(10);
    return;
  }
  if (!bufferReady) { delay(100); return; }

  if (mqtt.connected()) mqtt.loop();
  if (!mqtt.connected()) {
    if (wasMqttConnected) {
      Serial.printf("[MQTT LOST] state=%d: %s\n", mqtt.state(), mqttStateText(mqtt.state()));
      wasMqttConnected = false;
    }
    if (now - lastMqttAttempt >= RETRY_INTERVAL_MS) {
      lastMqttAttempt = now;
      Serial.printf("[MQTT CONNECT] %s:%u client=%s\n", MQTT_HOST, MQTT_PORT, clientId.c_str());
      // A single connect attempt can block while TCP/MQTT timeouts expire.
      if (mqtt.connect(clientId.c_str(), DEVICE_ID, MQTT_PASSWORD)) {
        wasMqttConnected = true;
        Serial.println("[MQTT OK] Authenticated; ready to publish.");
      } else {
        Serial.printf("[MQTT ERROR] state=%d: %s\n", mqtt.state(), mqttStateText(mqtt.state()));
      }
    }
    delay(10);
    return;
  }

  if (!pendingLength && now - lastSample >= SEND_INTERVAL_MS) {
    lastSample = now;
    if (prepareSample()) lastPublishAttempt = now - RETRY_INTERVAL_MS;
  }
  if (pendingLength && now - lastPublishAttempt >= RETRY_INTERVAL_MS) {
    lastPublishAttempt = now;
    bool sent = mqtt.publish(topic.c_str(),
                             reinterpret_cast<const uint8_t*>(pendingPayload),
                             (unsigned int)pendingLength, false);
    if (sent) {
      published++;
      Serial.printf("[PUBLISH SENT] bytes=%u local_sends=%lu failures=%lu; QoS 0, no broker ACK.\n",
                    (unsigned)pendingLength, (unsigned long)published, (unsigned long)failures);
      pendingLength = 0;
    } else {
      failures++;
      Serial.printf("[PUBLISH FAILED] state=%d: %s; bytes=%u buffer=%u heap=%u\n",
                    mqtt.state(), mqttStateText(mqtt.state()), (unsigned)pendingLength,
                    (unsigned)mqtt.getBufferSize(), (unsigned)ESP.getFreeHeap());
      Serial.println("[RETRY] Keeping the same payload and message ID; retry in 5 seconds.");
      // state() is connection status, not an exact publish-error code.
      network.stop();
    }
  }
  delay(2);
}
