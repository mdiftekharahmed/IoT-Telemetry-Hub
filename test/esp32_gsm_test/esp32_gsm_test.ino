// Select your modem before including TinyGSM
#define TINY_GSM_MODEM_SIM800
// Increase serial RX buffer size for TLS handshakes
#define TINY_GSM_RX_BUFFER 1024

#include <TinyGsmClient.h>
#include <ESP_SSLClient.h> // Performs TLS encryption on the ESP32 (Install "ESP_SSLClient" by Mobizt in Arduino Library Manager)
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==========================================
// User Configuration
// ==========================================
// Cellular Network
// Set your SIM card APN here (e.g., "gpinternet" for Grameenphone, "blweb" for Banglalink)
const char* apn = "YOUR_APN"; 
const char* gprsUser = "";
const char* gprsPass = "";

// MQTT Broker settings
const char* mqtt_server = "telemetry.durnibar.tech";

// Set use_tls to false for plain MQTT (port 1883), or true for MQTTS TLS (port 8883)
const bool use_tls = false;
const int mqtt_port = use_tls ? 8883 : 1883;

// Device credentials from IoT-Telemetry-Hub
const char* mqtt_user = "test_device_01"; 
const char* mqtt_password = "YOUR_MQTT_PASSWORD";
const char* device_id = "test_device_01";

// SIM800L Serial connection (Using ESP32 Hardware Serial 1)
#define RX_PIN 16
#define TX_PIN 17
// ==========================================

HardwareSerial SerialAT(1);
TinyGsm modem(SerialAT);

// 1. Plain TCP client: SIM800L transparent data transport pipe
TinyGsmClient gsmClient(modem);

// 2. SSL/TLS client: Only used if use_tls is set to true
ESP_SSLClient secureClient;

// 3. MQTT Client
PubSubClient client;

unsigned long lastMsg = 0;
int messageCount = 0;

void setup_modem() {
  // Start AT communication
  SerialAT.begin(9600, SERIAL_8N1, RX_PIN, TX_PIN);
  delay(3000);

  Serial.println("Initializing modem...");
  modem.restart();

  Serial.print("Connecting to APN: ");
  Serial.println(apn);
  
  if (!modem.gprsConnect(apn, gprsUser, gprsPass)) {
    Serial.println("Failed to connect to GPRS");
    while (true) { delay(1000); }
  }
  Serial.println("GPRS connected!");
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection via GSM...");
    
    String clientId = "ESP32GSM-";
    clientId += String(random(0xffff), HEX);
    
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
  
  setup_modem();

  if (use_tls) {
    // Attach GSM stream to ESP32 TLS client
    secureClient.setClient(&gsmClient);
    secureClient.setBufferSizes(2048, 512);
    secureClient.setTimeout(15000);
    secureClient.setInsecure(); // For production with cert validation: secureClient.setRootCA(root_ca);
    client.setClient(secureClient);
    Serial.println("Configured for MQTTS (TLS) on port 8883");
  } else {
    // Direct plain TCP via GSM module without TLS overhead
    client.setClient(gsmClient);
    Serial.println("Configured for plain MQTT on port 1883");
  }

  client.setServer(mqtt_server, mqtt_port);
  client.setBufferSize(512);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();
  
  // Send a message every 10 seconds
  if (now - lastMsg > 10000) {
    lastMsg = now;
    messageCount++;

    // For ArduinoJson v6 use: StaticJsonDocument<256> doc;
    JsonDocument doc;
    String messageId = "msg-gsm-" + String(millis()) + "-" + String(messageCount);
    doc["message_id"] = messageId;
    
    JsonObject values = doc["values"].to<JsonObject>();
    values["temperature"] = 25.0 + random(0, 100) / 10.0;
    values["humidity"] = 60.0 + random(0, 100) / 10.0;
    
    char payload[256];
    serializeJson(doc, payload);

    String topic = "devices/" + String(device_id) + "/telemetry";

    Serial.print("Publishing message over GSM to topic: ");
    Serial.println(topic);
    Serial.print("Payload: ");
    Serial.println(payload);

    if(client.publish(topic.c_str(), payload)) {
       Serial.println("Publish successful!");
    } else {
       Serial.println("Publish failed!");
    }
    Serial.println("-------------------------");
  }
}
