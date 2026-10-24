#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==========================================
// User Configuration
// ==========================================

const char* ssid     = "IU_SHH_2nd_303";
const char* password = "bdren@iu@303";

// MQTT Broker settings
const char* mqtt_server = "telemetry.durnibar.tech";

// Set use_tls to false for plain MQTT (port 1883), or true for MQTTS TLS (port 8883)
const bool use_tls   = false;
const int  mqtt_port = use_tls ? 8883 : 1883;

// Device credentials from IoT-Telemetry-Hub
// The user is the device_id. The password was generated when creating the device.
const char* mqtt_user     = "TEST_03";
const char* mqtt_password = "nvdzB6OuHcTwvcAW";
const char* device_id     = "TEST_03";

// ==========================================

#include <WiFiClientSecure.h>
WiFiClient       plainClient;
WiFiClientSecure secureClient;
PubSubClient     client;

unsigned long lastMsg      = 0;
int           messageCount  = 0;
String        macPrefix;    // computed once in setup(); unique per board, survives reboots

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi connected");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  // Configure MQTT client transport
  if (use_tls) {
    secureClient.setInsecure(); // Or use secureClient.setCACert(root_ca);
    client.setClient(secureClient);
    Serial.println("Configured for MQTTS (TLS) on port 8883");
  } else {
    client.setClient(plainClient);
    Serial.println("Configured for plain MQTT on port 1883");
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");

    // Create a random client ID
    String clientId = "ESP32Client-";
    clientId += String(random(0xffff), HEX);

    // Attempt to connect
    if (client.connect(clientId.c_str(), mqtt_user, mqtt_password)) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  randomSeed(analogRead(0));

  setup_wifi();

  // Build a 12-char MAC prefix (e.g. "A1B2C3D4E5F6").
  // Hardware-burned — never changes across reboots or power cycles.
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char macBuf[13];
  snprintf(macBuf, sizeof(macBuf), "%02X%02X%02X%02X%02X%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  macPrefix = String(macBuf);
  Serial.print("Device MAC prefix: ");
  Serial.println(macPrefix);

  client.setServer(mqtt_server, mqtt_port);
  client.setBufferSize(512);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // Send a message every 5 seconds
  if (now - lastMsg > 5000) {
    lastMsg = now;
    messageCount++;

    // Note: JsonDocument is for ArduinoJson v7.
    // For v6 use: StaticJsonDocument<512> doc;
    JsonDocument doc;

    // message_id: MAC(12) + "-" + millis%8digits + "-" + count = max ~24 chars (< 36 limit).
    // MAC prefix is hardware-burned, so IDs are unique across reboots and across devices.
    String messageId = macPrefix + "-" + String(millis() % 100000000UL) + "-" + String(messageCount);
    doc["message_id"] = messageId;

    // FIX 2: The optional top-level "timestamp" field must be an ISO 8601
    // timezone-aware string (e.g. "2026-10-18T15:59:00Z"). If you do not have
    // an RTC or NTP source, simply omit it — the server falls back to received_at.
    //
    // Uncomment and set correctly if you have NTP/RTC:
    // doc["timestamp"] = "2026-10-18T15:59:00Z";

    // FIX 3: "values" must contain ONLY numeric (float/int) sensor readings.
    // The old code had values["timestamp"] = "12-10-2026 12:30" which is a string,
    // not a float. This caused a server-side ValidationError and the entire message
    // was silently rejected. Remove ALL non-numeric entries from this object.
    JsonObject values = doc["values"].to<JsonObject>();

    values["systemTemp"]       = 30   + random(0, 100) / 10.0;
    values["Moisture"]         = 30   + random(0, 100) / 10.0;
    values["SoilTemperature"]  = 25   + random(0, 100) / 10.0;
    values["EC"]               = 10   + random(0, 100) / 10.0;
    values["N"]                = 40   + random(0, 100) / 10.0;
    values["P"]                = 50   + random(0, 100) / 10.0;
    values["K"]                = 80   + random(0, 100) / 10.0;
    values["Distance"]         = 120  + random(0, 100) / 10.0;
    values["TDS"]              = 1200 + random(0, 100) / 10.0;
    values["pH"]               = 5.0;
    values["Turbidity"]        = 3.15;
    values["WaterTemperature"] = 25   + random(0, 100) / 10.0;

    char payload[512];
    serializeJson(doc, payload);

    String topic = "devices/" + String(device_id) + "/telemetry";

    Serial.print("Publishing message to topic: ");
    Serial.println(topic);
    Serial.print("Payload: ");
    Serial.println(payload);

    // Publish to the MQTT broker
    if (client.publish(topic.c_str(), payload)) {
      Serial.println("Publish successful!");
    } else {
      Serial.println("Publish failed!");
    }
    Serial.println("-------------------------");
  }
}
