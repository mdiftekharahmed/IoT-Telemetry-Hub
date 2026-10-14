# ESP32 TLS & SIM800L Firmware Security Guide

This document explains the TLS/SSL security architecture between ESP32 devices and the IoT-Telemetry-Hub MQTT broker, detailing how to properly implement TLS encryption across Wi-Fi and GSM (SIM800L) cellular connections.

---

## 1. Broker TLS Architecture & Protocol Support

The IoT-Telemetry-Hub uses **Eclipse Mosquitto 2.x** (`eclipse-mosquitto:2`) exposed on port **8883** with certificates automatically managed by Caddy via Let's Encrypt / ZeroSSL.

* **Supported TLS Versions:** **TLS 1.2** and **TLS 1.3**.
* **Unsupported / Rejected Protocols:** **TLS 1.0, TLS 1.1, SSLv2, and SSLv3** are rejected by OpenSSL defaults due to known cryptographic vulnerabilities (POODLE, BEAST, SWEET32).
* **Certificates:** Provisioned under the **ISRG Root X1** trust chain using modern SHA-256 cipher suites with Server Name Indication (SNI).

---

## 2. The SIM800L Hardware Limitation

The SIM800L cellular module is a legacy 2G modem with internal firmware constraints:
* **Native SSL Stack:** The SIM800L internal TCP/IP stack (`AT+CIPSSL`) natively supports only **SSLv2, SSLv3, and TLS 1.0**.
* **Why `TinyGsmClientSecure` Fails:** Using `TinyGsmClientSecure` delegates TLS negotiation to the SIM800L firmware. Because the Mosquitto broker strictly requires TLS 1.2+, the handshake is immediately dropped.

### The Solution: ESP32-Side TLS Offloading

Rather than relying on the modem's outdated SSL stack, the **ESP32 handles all TLS cryptography locally** using its dual-core CPU and hardware encryption accelerators.

```text
+-------------------+              +-------------------+              +-----------------------+
|   ESP32 CPU       |              |   SIM800L Modem   |              |  MQTT Broker (VPS)    |
|                   |              |                   |              |  Port 8883            |
|  PubSubClient     |              |                   |              |                       |
|       |           |              |                   |              |                       |
|  ESP_SSLClient    |              |                   |              |                       |
|  (TLS 1.2 Engine) |              |                   |              |                       |
|       |           |  Raw Bytes   |                   |  GPRS / TCP  |                       |
|  TinyGsmClient    | -----------> |   Transparent     | -----------> |  Mosquitto (OpenSSL)  |
|  (Serial1 / UART) |  (Encrypted) |   TCP Data Pipe   |  (Encrypted) |  (TLS 1.2 Handshake)  |
+-------------------+              +-------------------+              +-----------------------+
```

1. **`TinyGsmClient`** creates a standard, unencrypted TCP stream via GPRS. The SIM800L acts solely as a transparent data modem.
2. **`ESP_SSLClient`** wraps `TinyGsmClient` and performs TLS 1.2 handshakes, certificate parsing, and payload encryption inside the ESP32.
3. **`PubSubClient`** sends MQTT frames to `ESP_SSLClient`. All data travelling over the ESP32-to-SIM800L UART connection is already TLS ciphertext.

---

## 3. ISRG Root X1 Certificate (Let's Encrypt)

To authenticate the broker and prevent Man-In-The-Middle (MITM) attacks in production, flash the **ISRG Root X1** root CA certificate into the ESP32 firmware:

```cpp
// Let's Encrypt ISRG Root X1 (Valid until: Jun 4 11:04:38 2035 GMT)
const char ROOT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
)EOF";
```

### Retrieving and Verifying the Root CA Independently

You can verify or re-download the root certificate at any time:

1. **Official Let's Encrypt Portal:**
   ```bash
   curl -s https://letsencrypt.org/certs/isrgrootx1.pem
   ```
2. **From Live Broker Host:**
   ```bash
   openssl s_client -showcerts -connect telemetry.durnibar.tech:8883 </dev/null
   ```

---

## 4. Implementation Guidelines

### A. Wi-Fi Deployment (`esp32_wifi_test.ino`)

For Wi-Fi connections, ESP32 uses `WiFiClientSecure`:

```cpp
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>

WiFiClientSecure espClient;
PubSubClient client(espClient);

void setup() {
  Serial.begin(115200);
  WiFi.begin("SSID", "PASSWORD");
  while (WiFi.status() != WL_CONNECTED) { delay(500); }

  // 1. Sync clock via NTP (REQUIRED for certificate date validation)
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  time_t now = time(nullptr);
  while (now < 1700000000) { // Wait until epoch advances past 2023
    delay(500);
    now = time(nullptr);
  }

  // 2. Set Root CA certificate
  espClient.setCACert(ROOT_CA);

  // 3. Configure MQTT
  client.setServer("telemetry.durnibar.tech", 8883);
}
```

### B. GSM / SIM800L Deployment (`esp32_gsm_test.ino`)

Requires library: **`ESP_SSLClient` by Mobizt** (available in Arduino Library Manager).

```cpp
#define TINY_GSM_MODEM_SIM800
#define TINY_GSM_RX_BUFFER 1024 // Buffer for TLS handshake packets over serial

#include <TinyGsmClient.h>
#include <ESP_SSLClient.h>
#include <PubSubClient.h>

HardwareSerial SerialAT(1);
TinyGsm modem(SerialAT);

// 1. Transparent TCP client (SIM800L)
TinyGsmClient gsmClient(modem);

// 2. Local ESP32 TLS Client
ESP_SSLClient secureClient;

// 3. MQTT Client
PubSubClient client(secureClient);

void setup() {
  Serial.begin(115200);
  SerialAT.begin(9600, SERIAL_8N1, 16, 17);
  modem.restart();
  modem.gprsConnect("YOUR_APN", "", "");

  // Attach GSM stream to ESP32 TLS engine
  secureClient.setClient(&gsmClient);
  secureClient.setBufferSizes(2048, 512); // RX buffer for TLS records, TX buffer
  secureClient.setTimeout(15000);         // Cellular latency timeout

  // Production: Enforce Root CA validation
  secureClient.setRootCA(ROOT_CA);
  // Bench testing only: secureClient.setInsecure();

  client.setServer("telemetry.durnibar.tech", 8883);
  client.setBufferSize(512);
}
```

---

## 5. Critical Deployment Gotchas

### 1. Clock Synchronization is Mandatory for TLS
X.509 certificates define validity windows (`Not Before` and `Not After`).
* ISRG Root X1 is valid from **2015** to **2035**.
* On boot, an ESP32 without an RTC chip resets its clock to **Jan 1, 1970**.
* If certificate validation is enabled (`setCACert` / `setRootCA`) before the clock is synchronized, the ESP32 will reject the certificate as **not yet valid**.
* **Wi-Fi:** Call `configTime(0, 0, "pool.ntp.org")` and wait for the time to synchronize.
* **GSM:** Use the cellular network clock (NITZ) by sending `AT+CLTS=1` to the modem, or query time using `modem.getNetworkTime()`.

### 2. UART Serial Buffer Sizing (`TINY_GSM_RX_BUFFER`)
During the TLS handshake, the server sends a certificate chain of approximately 2–3 KiB. The standard Arduino HardwareSerial buffer is only 64 or 256 bytes, which will cause dropped bytes and handshake failure.
* Always define `#define TINY_GSM_RX_BUFFER 1024` (or `2048`) **before** `#include <TinyGsmClient.h>`.

### 3. Latency & Timeouts
Cellular round-trip latency over 2G GPRS typically ranges between 300 ms and 1500 ms.
* Increase client timeout on `ESP_SSLClient`: `secureClient.setTimeout(15000);`.
* Configure PubSubClient keep-alive accordingly: `client.setKeepAlive(30);`.
