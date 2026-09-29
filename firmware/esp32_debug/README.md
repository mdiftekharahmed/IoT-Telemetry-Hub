# ESP32 debug publisher

Open `esp32_debug.ino` in Arduino IDE. Install **PubSubClient** and **ArduinoJson 6 or 7**, select your ESP32 board, and fill in the Wi-Fi and MQTT placeholders. Upload and open Serial Monitor at **115200 baud**.

The sketch sends three simulated values every **10 seconds**. Register and enable the matching device and the `temperature`, `humidity`, and `systemTemp` parameters in the dashboard. The password must be provisioned in Mosquitto. The broker must be reachable from the ESP32 network: the repository's loopback-only MQTT binding does not allow remote devices to connect. Use this plain-port-1883 sketch on an approved trusted test network.

Serial output includes timestamped boot/chip/reset details, flash/PSRAM/free heap, queued Wi-Fi events and disconnect reason codes, IP/gateway/subnet/DNS/RSSI/channel/MAC, MQTT connection durations, JSON and packet-size checks, payload contents, and publish results and counters. Status is repeated every five seconds. After failed MQTT connections, a separate DNS/TCP probe runs at most once per 30 seconds (plus the first failure). This can create a harmless broker log about a connection closing without an MQTT CONNECT packet. Passwords are not printed. Set `DEBUG_MODE=false` to suppress periodic status, probes and payload/sample-detail logging; other diagnostics remain visible.

On ESP32-S3, with **USB CDC On Boot enabled**, application logs are mirrored to native USB Serial and UART0 (`Serial0`). With CDC disabled they go to UART0. Select the port corresponding to the physical connector and use 115200 baud. This mirrors application logs, not every internal driver or ROM message. Press RESET after opening the monitor to see startup details. All sensor values, including `systemTemp`, are simulated; this code does not measure actual chip temperature.

- `[MQTT OK]`: the broker accepted the connection credentials.
- `[PUBLISH SENT]`: PubSubClient wrote the packet locally. This is QoS 0, **not confirmation of broker authorization, worker processing, or database storage**.
- `[PUBLISH FAILED]`: a local publish failed. The same payload/UUID is kept in RAM and retried after reconnect. `state()` describes connection status, not a detailed publish failure reason.
- Connection state `-2`: inspect hostname, routing, firewall and broker listener; `-4`: timeout; `4`/`5`: credentials/authorization rejected.

If Serial says SENT but the dashboard stays empty, inspect the broker and worker logs on the VM:

```bash
cd /opt/iot-telemetry-hub
docker compose logs --tail=100 mosquitto worker
```

Check device/topic identity, enabled whitelist parameters and worker processing outcomes. The Serial Monitor cannot see a QoS 0 broker ACL rejection or a database error.

New samples use random UUIDs so rebooting does not restart an already-used sequence. This is a debug sketch: it does not collect samples during disconnection, does not keep an offline history, and loses any pending sample on reboot. Individual MQTT connect attempts can block until network timeouts expire. The buffers have extra room for testing, but validate capacity again before adding 30 real parameters. No hardware/Arduino compile verification has been performed in this workspace.
