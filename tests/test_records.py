'''Tests for grouped transmission records, device health, and CSV exclusion.'''
import csv
import io
import json
from uuid import uuid4

from app.config import Settings
from app.ingestion import ingest

TOPIC = 'devices/sensor-01/telemetry'


def _payload(values, timestamp=None):
    data = {'message_id': str(uuid4()), 'values': values}
    if timestamp:
        data['timestamp'] = timestamp
    return json.dumps(data).encode()


# ---------------------------------------------------------------------------
# /api/telemetry/records - matrix endpoint
# ---------------------------------------------------------------------------


def test_records_endpoint_returns_matrix(seeded, authenticated_client):
    '''One record per transmission; values are keyed by parameter name.'''
    authenticated_client.post('/api/parameters', json={'name': 'humidity'})
    ingest(seeded, TOPIC, _payload({'temperature': 23.5, 'humidity': 60.2}))

    result = authenticated_client.get('/api/telemetry/records').json()
    assert 'columns' in result and 'records' in result
    assert 'temperature' in result['columns']
    assert 'systemTemp' not in result['columns']
    row = result['records'][0]
    assert 'registry_id' in row
    assert 'device_id' in row
    assert 'device_name' in row
    assert 'timestamp' in row
    assert 'values' in row
    assert 'health' in row


def test_records_one_row_per_transmission(seeded, authenticated_client):
    '''Two ingest calls must produce exactly two rows.'''
    ingest(seeded, TOPIC, _payload({'temperature': 20.0}))
    ingest(seeded, TOPIC, _payload({'temperature': 21.0}))

    result = authenticated_client.get('/api/telemetry/records').json()
    assert len(result['records']) == 2


def test_records_missing_parameter_absent_from_values(seeded, authenticated_client):
    '''A parameter not included in a transmission has no key in that row values dict.'''
    authenticated_client.post('/api/parameters', json={'name': 'pressure'})
    ingest(seeded, TOPIC, _payload({'temperature': 20.0}))

    result = authenticated_client.get('/api/telemetry/records').json()
    row = result['records'][0]
    assert 'temperature' in row['values']
    assert 'pressure' not in row['values']


def test_records_pagination(seeded, authenticated_client):
    '''Cursor-based pagination over registry IDs works correctly.'''
    for i in range(15):
        ingest(seeded, TOPIC, _payload({'temperature': float(i)}))

    first = authenticated_client.get('/api/telemetry/records', params={'limit': 5}).json()
    assert len(first['records']) == 5
    assert first['next_cursor'] is not None

    second = authenticated_client.get(
        '/api/telemetry/records',
        params={'limit': 5, 'before_id': first['next_cursor']},
    ).json()
    assert len(second['records']) == 5
    assert all(r['registry_id'] < first['next_cursor'] for r in second['records'])


def test_records_health_rule_returned(seeded, authenticated_client):
    '''health_rule must always be present in the response.'''
    result = authenticated_client.get('/api/telemetry/records').json()
    rule = result['health_rule']
    assert rule['parameter'] == 'systemTemp'
    assert 'min' in rule and 'max' in rule and 'unit' in rule


# ---------------------------------------------------------------------------
# Device-health evaluation (pure unit tests on device_health())
# ---------------------------------------------------------------------------


def test_health_ok_within_range():
    from app.health import device_health
    s = Settings(system_temp_min=10.0, system_temp_max=60.0, _env_file=None)
    assert device_health({'systemTemp': 35.0}, s) == 'ok'
    assert device_health({'systemTemp': 10.0}, s) == 'ok'
    assert device_health({'systemTemp': 60.0}, s) == 'ok'


def test_health_not_ok_outside_range():
    from app.health import device_health
    s = Settings(system_temp_min=10.0, system_temp_max=60.0, _env_file=None)
    assert device_health({'systemTemp': 9.9}, s) == 'not_ok'
    assert device_health({'systemTemp': 60.1}, s) == 'not_ok'


def test_health_unknown_when_no_thresholds():
    from app.health import device_health
    s = Settings(system_temp_min=None, system_temp_max=None, _env_file=None)
    assert device_health({'systemTemp': 35.0}, s) == 'unknown'


def test_health_unknown_when_no_system_temp():
    from app.health import device_health
    s = Settings(system_temp_min=10.0, system_temp_max=60.0, _env_file=None)
    assert device_health({}, s) == 'unknown'
    assert device_health({'temperature': 22.0}, s) == 'unknown'


def test_health_with_only_min_threshold():
    from app.health import device_health
    s = Settings(system_temp_min=10.0, system_temp_max=None, _env_file=None)
    assert device_health({'systemTemp': 10.0}, s) == 'ok'
    assert device_health({'systemTemp': 9.9}, s) == 'not_ok'
    assert device_health({'systemTemp': 999.0}, s) == 'ok'


def test_health_with_only_max_threshold():
    from app.health import device_health
    s = Settings(system_temp_min=None, system_temp_max=60.0, _env_file=None)
    assert device_health({'systemTemp': 60.0}, s) == 'ok'
    assert device_health({'systemTemp': 60.1}, s) == 'not_ok'
    assert device_health({'systemTemp': -99.0}, s) == 'ok'


# ---------------------------------------------------------------------------
# systemTemp excluded from CSV export
# ---------------------------------------------------------------------------


def test_csv_excludes_system_temp(seeded, authenticated_client):
    '''systemTemp readings must never appear in exported CSV rows.'''
    authenticated_client.post('/api/parameters', json={'name': 'systemTemp', 'enabled': True})
    ingest(
        seeded, TOPIC,
        _payload({'temperature': 22.5, 'systemTemp': 42.0}, timestamp='2026-09-25T10:00:00Z'),
    )

    response = authenticated_client.get(
        '/api/telemetry/export',
        params={'start': '2026-09-25T00:00:00Z', 'end': '2026-09-26T00:00:00Z'},
    )
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    columns = response.text.split('\r\n')[0].split(',')
    assert 'systemTemp' not in columns
    assert 'temperature' in columns
    assert rows[0]['temperature'] == '22.5'


def test_csv_only_system_temp_yields_header_only(seeded, authenticated_client):
    '''If the only parameter in the range is systemTemp, the export is header-only.'''
    authenticated_client.post('/api/parameters', json={'name': 'systemTemp', 'enabled': True})
    authenticated_client.put('/api/parameters/temperature', json={'enabled': False})
    ingest(
        seeded, TOPIC,
        _payload({'systemTemp': 42.0}, timestamp='2026-09-25T10:00:00Z'),
    )

    response = authenticated_client.get(
        '/api/telemetry/export',
        params={'start': '2026-09-25T00:00:00Z', 'end': '2026-09-26T00:00:00Z'},
    )
    assert response.status_code == 200
    assert response.text == 'timestamp,device_id,device_name\r\n'

