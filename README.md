# IoT Telemetry Hub

**Client documentation:** [User manual and administrator handover guide](CLIENT_USER_MANUAL.md) | [ESP32 TLS & SIM800L Firmware Security Guide](docs/tls-firmware-guide.md)

A production-ready backend for IoT devices, featuring an authenticated management API, global parameter whitelist, persistent telemetry storage, and a responsive administrative UI dashboard.

## Features

- **Responsive Web Dashboard**: Manage your devices, monitor health, and view data from any screen.
- **MQTT Ingestion Engine**: Robust handling of incoming telemetry via MQTT with deduplication.
- **Parameter Whitelisting**: Define exactly which sensor data you want to collect and their units.
- **Data Export**: Export your historical data as wide-format CSVs.
- **Secure**: Authentication required for all endpoints, profile management, and hashed passwords.

---

## Full Installation Process

To install and run the full stack (Docker, PostgreSQL, Mosquitto MQTT, FastAPI
backend, React dashboard, Caddy proxy) on a fresh Linux server (e.g. Ubuntu 24.04),
use the automated `install.sh` script as a sudo-capable user (not root):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh)
# or:
curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh | bash
```

The script will:
1. Install Docker Engine and required system packages.
2. Clone the repository to `/opt/coldchain` (a fresh server needs nothing preinstalled).
3. Prompt for a domain/IP, generate secure secrets, and write the `.env` file and the
   Mosquitto broker credentials (`secrets/mosquitto.passwd`).
4. Build the images, run database migrations, seed demo data, and train the ML models.
5. Create the admin accounts and enable the `coldchain.service` systemd auto-start.

Admin credentials to note:
- Seeded admin: `admin` / `admin123` (**change this** from the admin panel).
- Demo users: `pharmacist1` / `pharma123` and `inspector1` / `inspect123`.
- Five extra administrators are created (`mehedi1`–`mehedi5`); their passwords are
  printed at the end of the install together with all generated secrets — save them.

Deploy a specific branch instead of the GitHub default (e.g. the hackathon build):

```bash
REPO_BRANCH=BUBT_IOT_HACKATHON bash install.sh
```

Access the dashboard at `https://<your-server-ip>`. Caddy serves HTTPS with its
internal CA by default, so the browser shows a security warning — click
**Advanced → Proceed**. To use a trusted Let's Encrypt certificate later, point a
real domain at the server, remove the single `tls internal` line from
`/opt/coldchain/Caddyfile`, and restart the service (Caddy auto-requests the certificate).

### Managing the Background Service
The installation script creates a systemd service so your hub automatically starts on boot.
- Check Status: `sudo systemctl status coldchain`
- Restart Hub: `sudo systemctl restart coldchain`
- View Logs: `sudo journalctl -u coldchain -f`

---

## Securing with a Free Public SSL Certificate

By default, the hub uses a self-signed certificate for the IP address. For a proper, trusted HTTPS connection without browser warnings, you can get a free Let's Encrypt certificate:

1. Register a free domain at [DuckDNS](https://www.duckdns.org/) or [No-IP] and point it to your server's IP address.
2. Edit your Caddyfile:
   ```bash
   nano /opt/coldchain/Caddyfile
   ```
3. Replace the entire contents with:
   ```text
   your-project.duckdns.org {
       reverse_proxy api:8000
   }
   ```
4. Restart the system:
   ```bash
   sudo systemctl restart coldchain
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


### Step 3: ESP32 Code Example (Arduino IDE)

The default MQTT connection port is **1883**. Use the following Arduino code template to connect your ESP32 to Wi-Fi and publish JSON telemetry to the server. 

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
// 3. Device Credentials (Must match exactly what you added in Step 1)
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
