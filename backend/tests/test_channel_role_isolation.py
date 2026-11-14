"""Departmental roles cannot use operator-only channel endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import ChannelAccount, ChannelGrant
from app.models.user import User


DEPARTMENT_PASSWORD = "deptpass1"


@pytest.fixture
def channel_isolation_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        admin = User(username="admin", password_hash=hash_password("adminpass1"), role="admin", department="administration", is_active=True, must_change_password=False)
        db.add(admin)
        db.flush()
        account = ChannelAccount(owner_user_id=admin.id, channel_type="gmail", status="verified_inbound")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=admin.id))
        for role in ("engineering", "production", "procurement"):
            db.add(User(
                username=role,
                password_hash=hash_password(DEPARTMENT_PASSWORD),
                role=role,
                department=role,
                is_active=True,
                must_change_password=False,
            ))
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    response = client.post(
        "/auth/login",
        json={"username": username, "password": DEPARTMENT_PASSWORD},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return csrf


@pytest.mark.parametrize("role", ["engineering", "production", "procurement"])
def test_department_roles_cannot_onboard_or_mutate_channels(channel_isolation_client, role):
    client = channel_isolation_client
    csrf = login(client, role)
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    assert client.get("/api/channels").status_code == 403
    assert client.post("/api/channels/gmail/accounts", headers=headers).status_code == 403
    assert client.post("/api/channels/outlook/accounts", headers=headers).status_code == 403
    assert client.post("/api/channels/whatsapp/accounts", headers=headers).status_code == 403
    assert client.post("/api/channels/gmail/authorize", headers=headers).status_code == 403
    assert client.post(
        "/api/channels/accounts/1/external-binding",
        json={"external_account_id": "synthetic-external-id"},
        headers=headers,
    ).status_code == 403
    assert client.post("/api/channels/accounts/1/revoke", headers=headers).status_code == 403


@pytest.mark.parametrize("role", ["engineering", "production", "procurement"])
def test_department_roles_receive_no_channel_data(channel_isolation_client, role):
    client = channel_isolation_client
    login(client, role)

    # These read endpoints intentionally return an empty scope rather than
    # exposing the admin-owned synthetic account.
    assert client.get("/api/channels/accounts").json() == []
    assert client.get("/api/channel-accounts").json() == []
    assert client.get("/api/channel-accounts/1/refetch-check").status_code == 404
