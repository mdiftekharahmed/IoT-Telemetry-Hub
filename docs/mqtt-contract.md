# MQTT telemetry contract v1

This is the initial proposed firmware contract. Review it against real device
messages before production deployment.

## Transport and identity

- Topic: `devices/<device_id>/telemetry`.
- Device IDs: 1–64 characters; start with a letter or digit, then letters, digits,
  underscores or hyphens. IDs are case-sensitive.
- Broker username equals device ID. Provision its password separately from device
  registration in the API. Registration alone does not grant broker access.
- Collector username is `collector`; reserve it and do not use it as a device ID.
- Publish QoS 1, `retain=false`. Collector subscribes with QoS 1 and a stable client ID.
- Local Compose exposes the broker only on loopback. Before connecting physical
  devices, configure a private network/Tailscale binding or TLS with firewall rules.
- Never use the collector credentials on a device.

## Payload

UTF-8 JSON, at most 16 KiB, with no duplicate keys or extra envelope fields:

```json
{
  "message_id": "f2e86d8d-b575-493d-8753-649e6b84cda4",
  "timestamp": "2026-09-25T16:00:00+06:00",
  "values": {
    "temperature": 23.5,
    "humidity": 61
  }
}
```

- `message_id`: required UUID, unique per device reading. Reuse it when retrying
  the same reading. Reusing it with different values does not overwrite history.
- `timestamp`: optional ISO 8601 timestamp with `Z` or an explicit UTC offset.
  Missing/null means server receipt time. Naive timestamps are rejected.
- `values`: 1–100 numeric values. Parameter names start with a letter and contain
  only letters, digits and underscores (maximum 64 characters).
- Numeric strings, booleans, null, objects, arrays, NaN and infinity are rejected.
  Values use double-precision floating point; exact decimal arithmetic is not promised.
- The complete envelope is validated first. An invalid value makes the whole
  message invalid, even if that parameter is not whitelisted.

## Processing and recovery

1. Validate size, topic and JSON contract.
2. Ignore unknown/disabled devices.
3. Ignore a previously committed `(device_id, message_id)`.
4. Select currently enabled global parameters and discard unapproved values.
5. Commit a deduplication receipt and approved telemetry rows together.
6. Acknowledge successful or deliberately rejected messages. On an unexpected
   processing/database failure, do not acknowledge; reconnect to allow redelivery.

Each approved parameter becomes one telemetry row. Receipts are kept even if no
parameter is approved, so a later whitelist change cannot make a retry into new data.
Rejected devices and malformed messages have no receipt. Historical telemetry
survives disabling a device or deleting a whitelist entry.

Retained deliveries are ignored. Publishers must not set retention; a live retained
publish may arrive with its retained flag cleared under MQTT 3.1.1.

This is at-least-once transport with application deduplication, not a guarantee of
lossless collection: QoS 0, queue overflow, unpersisted broker state, invalid messages,
or a device that does not retry can lose readings. The worker must establish its
subscription before an initial device publish. Broker restart/outage tests remain
part of the VM milestone.

## Data retrieval

The API view is newest-ingested-first, using `before_id` for pagination. CSV exports
are ordered by event timestamp then row ID, with columns:

```text
timestamp,device_id,parameter,value
```

Export requires timezone-aware `start` and `end`, with `start < end` and interval
`start <= timestamp < end`. Empty intervals return a header-only CSV. There are
no device or parameter export filters in the initial scope.
