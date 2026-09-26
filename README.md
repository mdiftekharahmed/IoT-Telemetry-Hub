# IoT Telemetry Hub

A production-ready backend for IoT devices, featuring an authenticated management API, global parameter whitelist, persistent telemetry storage, and a responsive administrative UI dashboard.

## Features

- **Responsive Web Dashboard**: Manage your devices, monitor health, and view data from any screen.
- **MQTT Ingestion Engine**: Robust handling of incoming telemetry via MQTT with deduplication.
- **Parameter Whitelisting**: Define exactly which sensor data you want to collect and their units.
- **Data Export**: Export your historical data as wide-format CSVs.
- **Secure**: Authentication required for all endpoints, profile management, and hashed passwords.

---

## Full Installation Process

To install and run the full backend (including the PostgreSQL database, MQTT broker, and API) on a fresh Linux server (e.g., Ubuntu), use the automated `install.sh` script.

1. **Run the installation script** (requires sudo privileges):
   ```bash
   sudo curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh | bash
   ```
2. **Follow the on-screen prompts**:
   - The script will automatically install Docker and its dependencies.
   - It will prompt you to set up passwords and environment variables.
   - It builds the Docker images and starts all backend services.
3. **Create your Admin Account**:
   - Once the script finishes, it will print a final command (e.g., `docker compose exec api python -m app.cli <username>`) for you to run. Run this command to set up your initial admin login.
4. **Access the Dashboard**:
   - Navigate to `https://<your-server-ip>` in your web browser. (Note: Because it uses a self-signed certificate by default, your browser will show a security warning. Click "Advanced" and "Proceed" to bypass it).
   - Log in using the admin account you just created.

### Managing the Background Service
The installation script creates a systemd service so your hub automatically starts on boot.
- Check Status: `sudo systemctl status iot-telemetry-hub`
- Restart Hub: `sudo systemctl restart iot-telemetry-hub`
- View Logs: `sudo journalctl -u iot-telemetry-hub -f`

---

## Securing with a Free Public SSL Certificate

By default, the hub uses a self-signed certificate for the IP address. For a proper, trusted HTTPS connection without browser warnings, you can get a free Let's Encrypt certificate:

1. Register a free domain at [DuckDNS](https://www.duckdns.org/) or [No-IP] and point it to your server's IP address.
2. Edit your Caddyfile:
   ```bash
   nano /opt/iot-telemetry-hub/Caddyfile
   ```
3. Replace the entire contents with:
   ```text
   your-project.duckdns.org {
       reverse_proxy api:8000
   }
   ```
4. Restart the system:
   ```bash
   sudo systemctl restart iot-telemetry-hub
   ```
Caddy will automatically request and renew a trusted Let's Encrypt certificate for your domain.

---

## Device Registration & ESP32 Preparation

To get an ESP32 node sending data to your server, you need to register it in both the Web Dashboard and the MQTT Broker. 

### Step 1: Register in the Web Dashboard
1. Log into your web dashboard.
2. Go to the **Devices** tab.
3. Click **Add Device** and enter a unique Device ID (e.g., `ESP32_NODE_01`) and a human-readable Name (e.g., `Greenhouse Sensor`).
4. Ensure the device is toggled to **Active**.

### Step 2: Register Parameters
1. Go to the **Parameters** tab in the dashboard.
2. Click **Add Parameter** to whitelist the data your ESP32 will send (e.g., `temperature` with unit `°C`, `humidity` with unit `%`). 
*(Note: Any parameter sent by the ESP32 that is not whitelisted here will be safely ignored).*

### Step 3: Add the Device to the MQTT Broker
Your MQTT Broker (Mosquitto) requires devices to authenticate. You must generate a password for your new device. 

On your server terminal, run the following command to add a new user to the Mosquitto password file (replace `ESP32_NODE_01` with your exact Device ID, and `your_secure_password` with a strong password):

```bash
cd /opt/iot-telemetry-hub
sudo docker compose exec mosquitto mosquitto_passwd -b /secrets/mosquitto.passwd ESP32_NODE_01 your_secure_password
```
*Note: It may take up to 5 seconds for Mosquitto to reload the new password file.*

### Step 4: ESP32 Code Example (Arduino IDE)

Use the following Arduino code template to connect your ESP32 to Wi-Fi and publish JSON telemetry to the server. 

**Dependencies**: Open the Library Manager in the Arduino IDE and install:
1. **PubSubClient** (by Nick O'Leary)
2. **ArduinoJson** (by Benoit Blanchon)

```cpp
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// 1. Wi-Fi Credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// 2. MQTT Broker Settings
const char* mqtt_server = "YOUR_SERVER_IP_OR_DOMAIN";
const int mqtt_port = 1883;
// 3. Device Credentials (Must match exactly what you added in Step 1 & 3)
const char* mqtt_user = "ESP32_NODE_01"; 
const char* mqtt_pass = "your_secure_password";

// The MQTT Topic must match the format: devices/<DEVICE_ID>/telemetry
const char* mqtt_topic = "devices/ESP32_NODE_01/telemetry";

WiFiClient espClient;
PubSubClient client(espClient);
unsigned long lastMsg = 0;
unsigned int msgCounter = 1;

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
  Serial.println("\nWiFi connected. IP: ");
  Serial.println(WiFi.localIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    // Create a random client ID to avoid conflicts
    String clientId = "ESP32Client-";
    clientId += String(random(0xffff), HEX);
    
    // Attempt to connect using the device credentials
    if (client.connect(clientId.c_str(), mqtt_user, mqtt_pass)) {
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
  setup_wifi();
  client.setServer(mqtt_server, mqtt_port);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();
  if (now - lastMsg > 10000) { // Send data every 10 seconds
    lastMsg = now;

    // Generate example sensor data
    float temp = 24.0 + random(-10, 10) / 10.0;
    float hum = 50.0 + random(-50, 50) / 10.0;
    float sysTemp = 40.0 + random(-20, 20) / 10.0;
  
    // Create JSON payload
    StaticJsonDocument<256> doc;
    
    // Unique message ID: MAC address + incrementing counter
    String msgId = WiFi.macAddress() + "-" + String(msgCounter++);
    doc["message_id"] = msgId;
    
    JsonObject values = doc.createNestedObject("values");
    values["temperature"] = temp;
    values["humidity"] = hum;
    values["systemTemp"] = sysTemp; // Built-in health check parameter
  
    char jsonBuffer[256];
    serializeJson(doc, jsonBuffer);
  
    Serial.print("Publishing message: ");
    Serial.println(jsonBuffer);
    
    client.publish(mqtt_topic, jsonBuffer);
  }
}
```

---

## Advanced / Developer Notes

- **Docker Development Stack**: To run locally on Windows/Mac, copy `.env.example` to `.env`, create a `secrets/mosquitto.passwd` file using the mosquitto container, and run `docker compose up --build -d`.
- **API Surface**: The FastAPI documentation is available at `/docs` when the server is running. All data operations are secured behind Bearer token authentication.
- **System Health**: The system continuously monitors `systemTemp` from incoming devices to display health status in the UI. Ensure you configure `SYSTEM_TEMP_MIN` and `SYSTEM_TEMP_MAX` in your `.env` file to set acceptable thresholds.
