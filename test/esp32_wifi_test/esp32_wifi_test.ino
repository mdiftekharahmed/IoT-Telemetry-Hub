#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ==========================================
// User Configuration
// ==========================================
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// MQTT Broker settings
const char* mqtt_server = "YOUR_MQTT_SERVER_HOST"; // e.g., "192.168.1.100" or "mqtt.yourdomain.com"
const int mqtt_port = 8883;

// Device credentials from IoT-Telemetry-Hub
// The user is the device_id. The password was generated when creating the device.
const char* mqtt_user = "test_device_01"; 
const char* mqtt_password = "YOUR_MQTT_PASSWORD";
const char* device_id = "test_device_01";

// ==========================================

#include <WiFiClientSecure.h>
WiFiClientSecure espClient;
PubSubClient client(espClient);

unsigned long lastMsg = 0;
int messageCount = 0;

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

  // Use insecure mode (doesn't verify Let's Encrypt Root CA) 
  // If you want full security, you must provide the ISRG Root X1 cert via espClient.setCACert(root_ca);
  espClient.setInsecure();
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
  // Optional: wait for serial port to connect
  // while(!Serial) {} 
  randomSeed(analogRead(0));
  
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
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

    // Create JSON payload
    // Note: 'JsonDocument' is for ArduinoJson v7. 
    // If you are using v6, use 'StaticJsonDocument<256> doc;' instead.
    JsonDocument doc;
    
    String messageId = "msg-" + String(millis()) + "-" + String(messageCount);
    doc["message_id"] = messageId;
    
    JsonObject values = doc["values"].to<JsonObject>();
    
    // Example parameters (ensure these are registered in the Telemetry Hub)
    values["temperature"] = 20.0 + random(0, 100) / 10.0;
    values["humidity"] = 50.0 + random(0, 100) / 10.0;
    
    char payload[256];
    serializeJson(doc, payload);

    String topic = "devices/" + String(device_id) + "/telemetry";

    Serial.print("Publishing message to topic: ");
    Serial.println(topic);
    Serial.print("Payload: ");
    Serial.println(payload);

    // Publish to the MQTT broker
    if(client.publish(topic.c_str(), payload)) {
       Serial.println("Publish successful!");
    } else {
       Serial.println("Publish failed!");
    }
    Serial.println("-------------------------");
  }
}
