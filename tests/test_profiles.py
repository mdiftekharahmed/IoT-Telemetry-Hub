from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.models import Admin, UserProfile


def test_profile_requires_authentication(client):
    assert client.get("/api/profile").status_code == 401


def test_profile_details_are_separate_and_persist(application, authenticated_client):
    client = authenticated_client
    before = client.get("/api/profile").json()
    assert before["username"] == "admin"
    assert before["full_name"] is None
    response = client.put(
        "/api/profile",
        json={
            "full_name": "  Demo Operator  ",
            "email": "  operator@example.com  ",
        },
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["full_name"] == "Demo Operator"
    assert profile["email"] == "operator@example.com"
    assert profile["created_at"].endswith("Z")
    assert profile["updated_at"].endswith("Z")
    assert "password_hash" not in profile
    assert client.get("/api/profile").json() == profile
    assert client.get("/api/auth/me").json()["full_name"] == "Demo Operator"
    with application.state.sessions() as db:
        assert db.get(UserProfile, "admin").email == "operator@example.com"
        assert not hasattr(db.get(Admin, "admin"), "email")
    assert client.put("/api/profile", json={"full_name": "", "email": ""}).json()["email"] is None


def test_profile_validation(authenticated_client):
    assert (
        authenticated_client.put("/api/profile", json={"email": "not an email"}).status_code == 422
    )
    assert (
        authenticated_client.put("/api/profile", json={"full_name": "x" * 121}).status_code == 422
    )
    assert (
        authenticated_client.put("/api/profile", json={"username": "someone-else"}).status_code
        == 422
    )


def test_profile_cannot_read_or_change_another_account(application, authenticated_client):
    with application.state.sessions.begin() as db:
        db.add(Admin(username="another", password_hash="unused-test-hash"))
        db.flush()
        db.add(UserProfile(username="another", full_name="Another User"))
    authenticated_client.put("/api/profile", json={"full_name": "Current User"})
    assert authenticated_client.get("/api/profile").json()["username"] == "admin"
    with application.state.sessions() as db:
        assert db.get(UserProfile, "another").full_name == "Another User"


def test_migration_creates_profiles_for_existing_accounts(application):
    config = Config("alembic.ini")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")
    with application.state.sessions() as db:
        profile = db.scalar(select(UserProfile))
        assert profile.username == "admin"
        assert profile.email is None
