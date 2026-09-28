# ESP32 debug publisher

Open `esp32_debug.ino` in Arduino IDE. Install **PubSubClient** and **ArduinoJson 6 or 7**, select your ESP32 board, and fill in the Wi-Fi and MQTT placeholders. Upload and open Serial Monitor at **115200 baud**.

The sketch sends three simulated values every **10 seconds**. Register and enable the matching device and the `temperature`, `humidity`, and `systemTemp` parameters in the dashboard. The password must be provisioned in Mosquitto. The broker must be reachable from the ESP32 network: the repository's loopback-only MQTT binding does not allow remote devices to connect. Use this plain-port-1883 sketch on an approved trusted test network.

Serial output includes Wi-Fi status/IP/RSSI, MQTT connection error descriptions, JSON and packet-size checks, payload contents, ESP32 free heap, and publish success/failure counters. Passwords are not printed. Set `DEBUG_MODE=false` to suppress payload and sample-detail logging; errors remain visible.

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
