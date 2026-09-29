// ESP32 test publisher. Serial Monitor: 115200 baud.
// Libraries: PubSubClient and ArduinoJson (6 or 7).
// Sends simulated readings every 10 seconds. Plain MQTT for a trusted test network.
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// Timestamp each line. Mirror application logs to UART0 when Serial uses USB CDC.
class DebugConsole : public Print {
 public:
  using Print::write;
  size_t write(uint8_t value) override {
    if (lineStart) {
      char prefix[32];
      snprintf(prefix, sizeof(prefix), "[%10lu ms] ", (unsigned long)millis());
      Serial.print(prefix);
#if ARDUINO_USB_CDC_ON_BOOT
      Serial0.print(prefix);
#endif
      lineStart = false;
    }
    Serial.write(value);
#if ARDUINO_USB_CDC_ON_BOOT
    Serial0.write(value);
#endif
    if (value == '\n') lineStart = true;
    return 1;
  }
 private:
  bool lineStart = true;
};
DebugConsole Debug;

struct WifiDebugEvent { int event; int reason; };
QueueHandle_t wifiEvents = nullptr;

// Wi-Fi callbacks run on another task: queue events and print them from loop().
void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  WifiDebugEvent item{(int)event, 0};
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
    item.reason = info.wifi_sta_disconnected.reason;
  if (wifiEvents) xQueueSend(wifiEvents, &item, 0);
}

void printWifiEvents() {
  WifiDebugEvent item;
  while (wifiEvents && xQueueReceive(wifiEvents, &item, 0) == pdTRUE) {
    const char* label = "Other Wi-Fi/network event";
    switch (item.event) {
      case ARDUINO_EVENT_WIFI_STA_START: label = "Station started"; break;
      case ARDUINO_EVENT_WIFI_STA_CONNECTED: label = "Joined access point; waiting for IP"; break;
      case ARDUINO_EVENT_WIFI_STA_GOT_IP: label = "DHCP/IP ready"; break;
      case ARDUINO_EVENT_WIFI_STA_LOST_IP: label = "IP address lost"; break;
      case ARDUINO_EVENT_WIFI_STA_DISCONNECTED: label = "Disconnected from access point"; break;
      case ARDUINO_EVENT_WIFI_STA_STOP: label = "Station stopped"; break;
    }
    Debug.printf("[WIFI EVENT] %s event=%d reason=%d\n", label, item.event, item.reason);
    if (item.reason)
      Debug.println("[HINT] Disconnect reasons can include intentional retry resets; correlate with preceding logs.");
  }
}

#if __has_include("local_config.h")
#include "local_config.h"
#else
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "YOUR_SERVER_IP_OR_DOMAIN";
const uint16_t MQTT_PORT = 1883;
const char* DEVICE_ID = "ESP32_NODE_01";
const char* MQTT_PASSWORD = "your_secure_password";
#endif

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
uint32_t lastStatus = 0;
uint32_t lastProbe = 0;
uint32_t mqttAttempts = 0;

void printStatus() {
  Debug.printf("[STATUS] WiFi=%d MQTT=%d heap_free=%u heap_min=%u pending=%u sent=%lu failures=%lu\n",
               (int)WiFi.status(), mqtt.state(), (unsigned)ESP.getFreeHeap(),
               (unsigned)ESP.getMinFreeHeap(), (unsigned)pendingLength,
               (unsigned long)published, (unsigned long)failures);
  if (WiFi.status() == WL_CONNECTED) {
    Debug.printf("[NETWORK] IP=%s gateway=%s subnet=%s DNS=%s RSSI=%d channel=%d MAC=%s\n",
                 WiFi.localIP().toString().c_str(), WiFi.gatewayIP().toString().c_str(),
                 WiFi.subnetMask().toString().c_str(), WiFi.dnsIP().toString().c_str(),
                 (int)WiFi.RSSI(), (int)WiFi.channel(), WiFi.macAddress().c_str());
  }
}

void probeBroker() {
  IPAddress address;
  uint32_t started = millis();
  Debug.printf("[DNS] Resolving %s...\n", MQTT_HOST);
  if (!address.fromString(MQTT_HOST) && !WiFi.hostByName(MQTT_HOST, address)) {
    Debug.println("[DNS FAILED] Hostname resolution failed; MQTT credentials have not been checked.");
    return;
  }
  Debug.printf("[DNS OK] %s (%lu ms)\n", address.toString().c_str(), (unsigned long)(millis() - started));
  WiFiClient probe;
  started = millis();
  Debug.printf("[TCP TEST] Opening %s:%u; timeout 1500 ms...\n", address.toString().c_str(), MQTT_PORT);
  bool reachable = probe.connect(address, MQTT_PORT, 1500);
  Debug.printf("[TCP %s] elapsed=%lu ms\n", reachable ? "OPEN" : "FAILED", (unsigned long)(millis() - started));
  probe.stop();
  Debug.println(reachable
    ? "[HINT] TCP reachable; this probe did not authenticate MQTT. Broker may log a connection closed without CONNECT."
    : "[HINT] Check VPN routing, Docker port binding and firewall. A TCP failure is not a password rejection.");
}

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
    Debug.println("[JSON ERROR] Document capacity exceeded; sample not published.");
    return false;
  }
  size_t length = measureJson(doc);
  if (length >= sizeof(pendingPayload)) {
    Debug.printf("[JSON ERROR] Need %u bytes plus terminator; buffer=%u.\n",
                  (unsigned)length, (unsigned)sizeof(pendingPayload));
    return false;
  }
  // PubSubClient requires space for its maximum header, topic length and payload.
  size_t packetSize = 5 + 2 + topic.length() + length;
  if (packetSize > mqtt.getBufferSize()) {
    Debug.printf("[MQTT ERROR] Packet needs %u bytes; MQTT buffer=%u.\n",
                  (unsigned)packetSize, (unsigned)mqtt.getBufferSize());
    return false;
  }
  pendingLength = serializeJson(doc, pendingPayload, sizeof(pendingPayload));
  if (pendingLength != length) {
    pendingLength = 0;
    Debug.println("[JSON ERROR] Serialization length mismatch.");
    return false;
  }
  if (DEBUG_MODE) {
    Debug.printf("[SAMPLE] topic=%s bytes=%u heap=%u RSSI=%d dBm\n",
                  topic.c_str(), (unsigned)pendingLength, (unsigned)ESP.getFreeHeap(),
                  (int)WiFi.RSSI());
    Debug.println(pendingPayload);
  }
  return true;
}

void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.begin(115200);
#endif
  delay(1500);
  Debug.println("\n[BOOT] ESP32 telemetry DEBUG publisher; simulated data every 10 seconds.");
  Debug.printf("[HARDWARE] chip=%s revision=%u cores=%u CPU=%u MHz reset_reason=%d\n",
               ESP.getChipModel(), (unsigned)ESP.getChipRevision(), (unsigned)ESP.getChipCores(),
               (unsigned)ESP.getCpuFreqMHz(), (int)esp_reset_reason());
  Debug.printf("[MEMORY] flash=%u bytes PSRAM=%u bytes heap=%u bytes ArduinoJson=%s\n",
               (unsigned)ESP.getFlashChipSize(), (unsigned)ESP.getPsramSize(),
               (unsigned)ESP.getFreeHeap(), ARDUINOJSON_VERSION);
  if (esp_reset_reason() == ESP_RST_BROWNOUT)
    Debug.println("[POWER WARNING] Previous reset was a brownout. Check supply/cable/wiring; do not disable protection.");
  Debug.println("[SENSORS] All values INCLUDING systemTemp are SIMULATED; not actual chip temperature.");
  wifiEvents = xQueueCreate(16, sizeof(WifiDebugEvent));
  if (!wifiEvents) Debug.println("[WARNING] Wi-Fi event queue allocation failed; status polling still works.");
  WiFi.onEvent(onWifiEvent);
  Debug.println("[INFO] QoS 0: local send success does NOT prove broker acceptance or database storage.");
  topic = String("devices/") + DEVICE_ID + "/telemetry";
  WiFi.mode(WIFI_STA);
  // This sketch owns retries; do not overlap them with automatic reconnects.
  WiFi.setAutoReconnect(false);
  // Registered device IDs are unique; avoid reading the MAC before Wi-Fi is ready.
  clientId = String("debug-") + DEVICE_ID;
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);
  bufferReady = mqtt.setBufferSize(MQTT_BUFFER_SIZE);
  if (!bufferReady) Debug.println("[FATAL] Cannot allocate MQTT buffer; publishing disabled.");
  Debug.printf("[CONFIG] broker=%s:%u device=%s topic=%s\n",
                MQTT_HOST, MQTT_PORT, DEVICE_ID, topic.c_str());
  Debug.println("[WIFI] Starting connection (passwords are never printed).");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiAttempt = millis();
  lastMqttAttempt = millis() - RETRY_INTERVAL_MS;
}

void loop() {
  uint32_t now = millis();
  printWifiEvents();
  if (DEBUG_MODE && now - lastStatus >= 5000) {
    lastStatus = now;
    printStatus();
  }
  int wifiStatus = WiFi.status();
  if (wifiStatus != previousWifiStatus) {
    Debug.printf("[WIFI] status=%d (3=connected, 1=SSID unavailable, 4=connect failed, 6=disconnected)\n", wifiStatus);
    previousWifiStatus = wifiStatus;
    if (wifiStatus == WL_CONNECTED) {
      Debug.printf("[WIFI] IP=%s RSSI=%d dBm\n", WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
      lastMqttAttempt = now - RETRY_INTERVAL_MS;
    } else {
      network.stop();
      wasMqttConnected = false;
    }
  }
  if (wifiStatus != WL_CONNECTED) {
    if (now - lastWifiAttempt >= 30000) {
      Debug.println("[WIFI] Connection timed out; restarting the attempt. Check hotspot band and credentials.");
      WiFi.disconnect(false, false);
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastWifiAttempt = millis();
    }
    delay(10);
    return;
  }
  if (!bufferReady) { delay(100); return; }

  if (mqtt.connected()) mqtt.loop();
  if (!mqtt.connected()) {
    if (wasMqttConnected) {
      Debug.printf("[MQTT LOST] state=%d: %s\n", mqtt.state(), mqttStateText(mqtt.state()));
      wasMqttConnected = false;
    }
    if (now - lastMqttAttempt >= RETRY_INTERVAL_MS) {
      lastMqttAttempt = now;
      mqttAttempts++;
      uint32_t started = millis();
      Debug.printf("[MQTT ATTEMPT] number=%lu\n", (unsigned long)mqttAttempts);
      Debug.printf("[MQTT CONNECT] %s:%u client=%s\n", MQTT_HOST, MQTT_PORT, clientId.c_str());
      // A single connect attempt can block while TCP/MQTT timeouts expire.
      if (mqtt.connect(clientId.c_str(), DEVICE_ID, MQTT_PASSWORD)) {
        wasMqttConnected = true;
        Debug.println("[MQTT OK] Authenticated; ready to publish.");
      } else {
        Debug.printf("[MQTT ERROR] state=%d: %s\n", mqtt.state(), mqttStateText(mqtt.state()));
        if (DEBUG_MODE && (mqttAttempts == 1 || millis() - lastProbe >= 30000)) {
          probeBroker();
          lastProbe = millis();
        }
      }
      Debug.printf("[MQTT ATTEMPT END] elapsed=%lu ms (including diagnostic probe, if any)\n",
                   (unsigned long)(millis() - started));
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
    uint32_t publishStarted = millis();
    Debug.printf("[PUBLISH START] topic=%s bytes=%u QoS=0 retain=false\n", topic.c_str(), (unsigned)pendingLength);
    bool sent = mqtt.publish(topic.c_str(),
                             reinterpret_cast<const uint8_t*>(pendingPayload),
                             (unsigned int)pendingLength, false);
    Debug.printf("[PUBLISH RESULT] return=%s elapsed=%lu ms\n", sent ? "true" : "false",
                 (unsigned long)(millis() - publishStarted));
    if (sent) {
      published++;
      Debug.printf("[PUBLISH SENT] bytes=%u local_sends=%lu failures=%lu; QoS 0, no broker ACK.\n",
                    (unsigned)pendingLength, (unsigned long)published, (unsigned long)failures);
      pendingLength = 0;
    } else {
      failures++;
      Debug.printf("[PUBLISH FAILED] state=%d: %s; bytes=%u buffer=%u heap=%u\n",
                    mqtt.state(), mqttStateText(mqtt.state()), (unsigned)pendingLength,
                    (unsigned)mqtt.getBufferSize(), (unsigned)ESP.getFreeHeap());
      Debug.println("[RETRY] Keeping the same payload and message ID; retry in 5 seconds.");
      // state() is connection status, not an exact publish-error code.
      network.stop();
    }
  }
  delay(2);
}
