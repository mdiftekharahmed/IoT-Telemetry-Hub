import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.models import Admin
from app.security import password_hasher


@pytest.fixture
def application(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(Settings(database_url=url, _env_file=None))
    with app.state.sessions.begin() as db:
        db.add(Admin(username="admin", password_hash=password_hasher.hash("test-password-123")))
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(application):
    with TestClient(application) as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    result = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "test-password-123",
        },
    )
    assert result.status_code == 200
    client.headers["Authorization"] = f"Bearer {result.json()['access_token']}"
    return client


@pytest.fixture
def seeded(application, authenticated_client):
    assert (
        authenticated_client.post(
            "/api/devices",
            json={
                "device_id": "sensor-01",
                "name": "Workshop",
            },
        ).status_code
        == 201
    )
    assert (
        authenticated_client.post(
            "/api/parameters",
            json={
                "name": "temperature",
            },
        ).status_code
        == 201
    )
    return application.state.sessions
