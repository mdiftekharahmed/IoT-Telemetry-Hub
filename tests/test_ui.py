from sqlalchemy import select

from app.models import AdminSession


def test_browser_cookie_and_csrf(client, application):
    response = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "test-password-123",
        },
    )
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/devices").status_code == 200
    assert (
        client.post(
            "/api/devices",
            json={
                "device_id": "test",
                "name": "Test",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/devices",
            headers={"X-Requested-With": "telemetry-ui"},
            json={
                "device_id": "test",
                "name": "Test",
            },
        ).status_code
        == 201
    )
    assert (
        client.post("/api/auth/logout", headers={"X-Requested-With": "telemetry-ui"}).status_code
        == 204
    )
    assert "telemetry_session" not in client.cookies
    assert client.get("/api/devices").status_code == 401
    with application.state.sessions() as db:
        assert db.scalar(select(AdminSession)) is None


def test_ui_pages_and_assets(client):
    for route in ("/login", "/", "/devices", "/parameters", "/data", "/export"):
        response = client.get(route)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert 'name="viewport"' in response.text
        assert response.headers["x-frame-options"] == "DENY"
        assert "script-src 'self'" in response.headers["content-security-policy"]
    for file in ("styles.css", "app.js", "login.js", "icons.svg", "favicon.svg"):
        assert client.get(f"/static/{file}").status_code == 200


def test_workspace_summary(seeded, authenticated_client):
    summary = authenticated_client.get("/api/summary").json()
    assert summary == {
        "devices": 1,
        "enabled_devices": 1,
        "parameters": 1,
        "enabled_parameters": 1,
        "readings": 0,
        "records": 0,
        "last_received_at": None,
    }
