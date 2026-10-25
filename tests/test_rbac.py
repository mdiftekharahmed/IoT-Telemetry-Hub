"""Role-Based Access Control (RBAC) tests for ColdChain.

Tests role matrix across:
- admin (full system access)
- pharmacist (inventory & batch movement, no user/fridge config or reset)
- inspector (read-only audit, report, readings, no state mutations)
- unauthenticated / invalid token (401)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Batch, Fridge, User
from app.security import create_tokens, password_hasher


@pytest.fixture
def cc_users(application):
    """Seed the 3 roles for ColdChain."""
    with application.state.sessions.begin() as db:
        users = {
            "admin": User(
                username="admin_user",
                bcrypt_hash=password_hasher.hash("pass-admin"),
                role="admin",
                active=True,
            ),
            "pharmacist": User(
                username="pharm_user",
                bcrypt_hash=password_hasher.hash("pass-pharm"),
                role="pharmacist",
                active=True,
            ),
            "inspector": User(
                username="insp_user",
                bcrypt_hash=password_hasher.hash("pass-insp"),
                role="inspector",
                active=True,
            ),
        }
        for u in users.values():
            db.add(u)
        db.flush()

        # Seed test fridge and batch
        f = Fridge(name="TestFridge-A", capacity_slots=10, location="Ward 1", device_id="fridge-A")
        db.add(f)
        db.flush()

        b = Batch(
            code="BATCH-TEST-001",
            vaccine_name="Covax",
            qty=50,
            fridge_id=f.id,
            status="DISCARD",
            discard_latched=True,
            qr_token="token-test-123",
        )
        db.add(b)
        db.flush()

        # Return dict of tokens
        secret = application.state.settings.coldchain_jwt_secret
        tokens = {role: create_tokens(u, secret)["access_token"] for role, u in users.items()}
        tokens["fridge_id"] = f.id
        tokens["batch_id"] = b.id
        return tokens


def test_unauthenticated_requests(client):
    """Endpoints protected by require_role return 401 when unauthenticated."""
    assert client.get("/api/fridges").status_code == 401
    assert client.get("/api/batches").status_code == 401
    assert client.get("/api/audit").status_code == 401
    assert client.get("/api/users").status_code == 401


def test_public_batch_no_auth(client, cc_users):
    """Public QR endpoint allows unauthenticated access."""
    res = client.get("/api/public/batch/token-test-123")
    assert res.status_code == 200
    data = res.json()
    assert data["vaccine_name"] == "Covax"
    assert data["status"] == "DISCARD"
    assert "qr_token" not in data  # internal tokens not leaked


def test_fridges_list_all_roles(client, cc_users):
    """All active roles can list fridges."""
    for role in ("admin", "pharmacist", "inspector"):
        res = client.get("/api/fridges", headers={"Authorization": f"Bearer {cc_users[role]}"})
        assert res.status_code == 200, f"Role {role} failed to list fridges"


def test_fridge_create_admin_only(client, cc_users):
    """Only admin can create a fridge."""
    payload = {"name": "NewFridge", "capacity_slots": 5}

    # Pharmacist → 403
    res_pharm = client.post(
        "/api/fridges",
        json=payload,
        headers={"Authorization": f"Bearer {cc_users['pharmacist']}"},
    )
    assert res_pharm.status_code == 403

    # Inspector → 403
    res_insp = client.post(
        "/api/fridges",
        json=payload,
        headers={"Authorization": f"Bearer {cc_users['inspector']}"},
    )
    assert res_insp.status_code == 403

    # Admin → 201
    res_admin = client.post(
        "/api/fridges",
        json=payload,
        headers={"Authorization": f"Bearer {cc_users['admin']}"},
    )
    assert res_admin.status_code == 201


def test_batch_create_admin_and_pharmacist(client, cc_users):
    """Admin and Pharmacist can create batches; Inspector cannot."""
    payload = {
        "code": "BATCH-NEW-002",
        "vaccine_name": "Polio Oral",
        "qty": 100,
        "fridge_id": cc_users["fridge_id"],
    }

    # Inspector → 403
    res_insp = client.post(
        "/api/batches",
        json=payload,
        headers={"Authorization": f"Bearer {cc_users['inspector']}"},
    )
    assert res_insp.status_code == 403

    # Pharmacist → 201
    res_pharm = client.post(
        "/api/batches",
        json=payload,
        headers={"Authorization": f"Bearer {cc_users['pharmacist']}"},
    )
    assert res_pharm.status_code == 201


def test_batch_discard_reset_admin_only(client, cc_users):
    """Only admin can reset a discarded batch."""
    batch_id = cc_users["batch_id"]

    # Pharmacist → 403
    res_pharm = client.post(
        f"/api/batches/{batch_id}/reset",
        json={"reason": "pharmacist attempt"},
        headers={"Authorization": f"Bearer {cc_users['pharmacist']}"},
    )
    assert res_pharm.status_code == 403

    # Inspector → 403
    res_insp = client.post(
        f"/api/batches/{batch_id}/reset",
        json={"reason": "inspector attempt"},
        headers={"Authorization": f"Bearer {cc_users['inspector']}"},
    )
    assert res_insp.status_code == 403

    # Admin → 200
    res_admin = client.post(
        f"/api/batches/{batch_id}/reset",
        json={"reason": "authorized admin reset"},
        headers={"Authorization": f"Bearer {cc_users['admin']}"},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["discard_latched"] is False
    assert res_admin.json()["status"] == "AT_RISK"


def test_audit_log_access(client, cc_users):
    """Admin and Inspector can view audit log; Pharmacist cannot."""
    # Pharmacist → 403
    res_pharm = client.get("/api/audit", headers={"Authorization": f"Bearer {cc_users['pharmacist']}"})
    assert res_pharm.status_code == 403

    # Inspector → 200
    res_insp = client.get("/api/audit", headers={"Authorization": f"Bearer {cc_users['inspector']}"})
    assert res_insp.status_code == 200

    # Admin → 200
    res_admin = client.get("/api/audit", headers={"Authorization": f"Bearer {cc_users['admin']}"})
    assert res_admin.status_code == 200


def test_user_management_admin_only(client, cc_users):
    """Only Admin can manage users."""
    for role in ("pharmacist", "inspector"):
        res = client.get("/api/users", headers={"Authorization": f"Bearer {cc_users[role]}"})
        assert res.status_code == 403

    res_admin = client.get("/api/users", headers={"Authorization": f"Bearer {cc_users['admin']}"})
    assert res_admin.status_code == 200
