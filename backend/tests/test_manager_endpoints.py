"""Focused coverage for manager endpoints and retry-only authorization."""

import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.business import Inquiry, InquiryMessage, Message, ChannelAccount, ChannelGrant
from app.models.overview import MessageOverview
from app.models.permissions import ManagerPermissionGrant
from app.models.user import User


@pytest.fixture
def manager_client(monkeypatch):
    monkeypatch.setenv("AUTH_ORIGIN", "https://testserver")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with Session() as db:
        db.add_all([
            User(username="admin", password_hash=hash_password("adminpass1"), role="admin", department="administration", is_active=True, must_change_password=False),
            User(username="manager", password_hash=hash_password("managerpass1"), role="operations", manager_overlay_enabled=True, department="inquiry", is_active=True, must_change_password=False),
            User(username="worker", password_hash=hash_password("workerpass1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
            User(username="other-dept", password_hash=hash_password("otherpass1"), role="staff", department="after_sales", is_active=True, must_change_password=False),
        ])
        db.commit()
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="adjust_grants", granted_by_user_id=1),)
        db.commit()

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver") as client:
        yield client, Session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username, password):
    client.cookies.clear()
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    return client.post("/auth/login", json={"username": username, "password": password}, headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})


def headers(client):
    return {"Origin": "https://testserver", "X-CSRF-Token": client.cookies.get("ea_csrf")}


def test_manager_overlay_is_opt_in_for_base_role_and_default_denies(manager_client):
    client, Session = manager_client
    assert login(client, "admin", "adminpass1").status_code == 200
    response = client.post("/auth/admin/users", json={"username": "new-manager", "role": "operations", "department": "inquiry", "manager_overlay_enabled": True, "temporary_password": "managernew1"}, headers=headers(client))
    assert response.status_code == 201
    assert response.json()["manager_overlay_enabled"] is True
    with Session() as db:
        created = db.query(User).filter_by(username="new-manager").one()
        assert created.role == "operations"
        assert created.manager_overlay_enabled is True
    listed = client.get("/auth/admin/users").json()
    assert next(item for item in listed if item["username"] == "new-manager")["manager_overlay_enabled"] is True
    assert client.post("/auth/admin/managers/2/users/3/grants", json={"department": "inquiry", "permission": "password_reset"}, headers=headers(client)).status_code == 200
    assert client.get("/auth/me").status_code == 200

    # The admin grant is for the existing manager account (id 2), not the newly
    # created overlay-enabled account.
    assert login(client, "manager", "managerpass1").status_code == 200
    # The admin explicitly granted password-reset to manager id 2 above.
    allowed = client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client))
    assert allowed.status_code == 200


def test_manager_grant_is_bounded_to_target_department_and_action(manager_client):
    client, _ = manager_client
    assert login(client, "manager", "managerpass1").status_code == 200
    h = headers(client)
    assert client.post("/auth/manager/users/3/grants", json={"department": "inquiry", "permission": "password_reset"}, headers=h).status_code == 200
    assert client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client)).status_code == 200
    wrong_department = client.post("/auth/manager/users/4/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client))
    assert wrong_department.status_code == 403
    wrong_action = client.post("/auth/manager/users/3/deactivate", headers=headers(client))
    assert wrong_action.status_code == 403
    self_target = client.post("/auth/manager/users/2/grants", json={"department": "inquiry", "permission": "retry"}, headers=headers(client))
    assert self_target.status_code == 403
    admin_target = client.post("/auth/manager/users/1/grants", json={"department": "inquiry", "permission": "retry"}, headers=headers(client))
    assert admin_target.status_code == 403


@pytest.mark.parametrize("action,path,body", [
    ("password_reset", "/auth/manager/users/3/password-reset", {"temporary_password": "resetpass1"}),
    ("deactivate", "/auth/manager/users/3/deactivate", None),
    ("reactivate", "/auth/manager/users/3/reactivate", None),
])
def test_each_manager_mutation_requires_its_relevant_grant(manager_client, action, path, body):
    client, Session = manager_client
    with Session() as db:
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission=action, granted_by_user_id=1))
        if action == "reactivate":
            db.get(User, 3).is_active = False
        db.commit()
    assert login(client, "manager", "managerpass1").status_code == 200
    # The fixture's adjust_grants grant must not substitute for the action grant.
    response = client.post(path, json=body, headers=headers(client)) if body else client.post(path, headers=headers(client))
    assert response.status_code == 200


def test_revoke_grant_revokes_target_session_immediately(manager_client):
    client, Session = manager_client
    with Session() as db:
        db.add_all([
            ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="password_reset", granted_by_user_id=1),
            ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="deactivate", granted_by_user_id=1),
        ])
        db.commit()
    assert login(client, "worker", "workerpass1").status_code == 200
    target_cookies = dict(client.cookies)
    assert login(client, "manager", "managerpass1").status_code == 200
    assert client.delete("/auth/manager/users/3/grants/password_reset", headers=headers(client)).status_code == 200
    client.cookies.clear(); client.cookies.update(target_cookies)
    assert client.get("/auth/me").status_code == 401


def test_retry_requires_inquiry_grant_and_never_reads_customer_data(manager_client):
    client, Session = manager_client
    with Session() as db:
        account = ChannelAccount(owner_user_id=3, channel_type="gmail", status="not_ready")
        db.add(account); db.flush()
        inquiry = Inquiry(customer_contact="synthetic@example.invalid", normalized_customer_contact="synthetic@example.invalid", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="Synthetic", raw_message="synthetic", department="inquiry", source_channel_account_id=account.id, status="assigned", assigned_sales_user_id=3, handling_status="pending")
        db.add(inquiry); db.flush()
        message = Message(channel_account_id=account.id, provider="fixture", external_message_id="fixture-1", raw_content="synthetic customer secret", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc))
        db.add(message); db.flush()
        db.add(InquiryMessage(inquiry_id=inquiry.id, message_id=message.id, position=1, link_source="fixture"))
        db.add(MessageOverview(message_id=message.id, status="failed", failure_code="fixture"))
        db.commit(); message_id = message.id
    assert login(client, "manager", "managerpass1").status_code == 200
    denied = client.post(f"/api/messages/{message_id}/overview/retry", headers=headers(client))
    assert denied.status_code == 403
    with Session() as db:
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="retry", granted_by_user_id=1)); db.commit()
    allowed = client.post(f"/api/messages/{message_id}/overview/retry", headers=headers(client))
    assert allowed.status_code == 200
    assert "synthetic customer secret" not in allowed.text
    assert client.delete("/auth/manager/users/3/grants/retry", headers=headers(client)).status_code == 200
    # Revoking a manager grant invalidates the manager's current session too.
    assert client.post(f"/api/messages/{message_id}/overview/retry", headers=headers(client)).status_code == 401
    assert login(client, "manager", "managerpass1").status_code == 200
    assert client.post(f"/api/messages/{message_id}/overview/retry", headers=headers(client)).status_code == 403


def test_admin_bootstraps_exact_manager_grant_and_rejects_invalid_targets(manager_client):
    client, Session = manager_client
    assert login(client, "admin", "adminpass1").status_code == 200
    h = headers(client)
    grant = {"department": "inquiry", "permission": "password_reset"}
    response = client.post("/auth/admin/managers/2/users/3/grants", json=grant, headers=h)
    assert response.status_code == 200
    with Session() as db:
        row = db.query(ManagerPermissionGrant).filter_by(manager_user_id=2, target_user_id=3, permission="password_reset").one()
        assert row.department == "inquiry"
        assert row.permission == "password_reset"

    assert client.post("/auth/admin/managers/2/users/4/grants", json=grant, headers=h).status_code == 403
    assert client.post("/auth/admin/managers/1/users/3/grants", json=grant, headers=h).status_code == 409
    assert client.post("/auth/admin/managers/3/users/3/grants", json=grant, headers=h).status_code == 409
    with Session() as db:
        db.get(User, 3).is_active = False
        db.commit()
    assert client.post("/auth/admin/managers/2/users/3/grants", json=grant, headers=h).status_code == 409


def test_admin_revoke_deletes_grant_and_invalidates_manager_session(manager_client):
    client, Session = manager_client
    assert login(client, "admin", "adminpass1").status_code == 200
    h = headers(client)
    grant = {"department": "inquiry", "permission": "password_reset"}
    assert client.post("/auth/admin/managers/2/users/3/grants", json=grant, headers=h).status_code == 200
    assert login(client, "manager", "managerpass1").status_code == 200
    manager_cookies = dict(client.cookies)
    assert login(client, "admin", "adminpass1").status_code == 200
    assert client.delete("/auth/admin/managers/2/users/3/grants/password_reset", headers=headers(client)).status_code == 200
    with Session() as db:
        assert db.query(ManagerPermissionGrant).filter_by(manager_user_id=2, target_user_id=3, permission="password_reset").count() == 0
    client.cookies.clear(); client.cookies.update(manager_cookies)
    assert client.get("/auth/me").status_code == 401


def test_manager_deactivation_clears_grants_and_revokes_target_session(manager_client):
    client, Session = manager_client
    with Session() as db:
        db.add_all([
            ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="deactivate", granted_by_user_id=1),
            ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="reactivate", granted_by_user_id=1),
            ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="password_reset", granted_by_user_id=1),
        ])
        db.commit()

    assert login(client, "worker", "workerpass1").status_code == 200
    worker_cookies = dict(client.cookies)
    assert login(client, "manager", "managerpass1").status_code == 200
    assert client.post("/auth/manager/users/3/deactivate", headers=headers(client)).status_code == 200

    with Session() as db:
        grants = db.query(ManagerPermissionGrant).filter_by(manager_user_id=2, target_user_id=3).all()
        assert grants == []
        assert db.get(User, 3).is_active is False

    client.cookies.clear()
    client.cookies.update(worker_cookies)
    assert client.get("/auth/me").status_code == 401
    assert login(client, "worker", "workerpass1").status_code == 401

    client.cookies.clear()
    assert login(client, "manager", "managerpass1").status_code == 200
    assert client.post("/auth/manager/users/3/reactivate", headers=headers(client)).status_code == 403
    assert login(client, "admin", "adminpass1").status_code == 200
    assert client.post("/auth/admin/users/3/reactivate", headers=headers(client)).status_code == 200
    client.cookies.clear()
    client.cookies.update(worker_cookies)
    assert client.get("/auth/me").status_code == 401
    assert login(client, "worker", "workerpass1").status_code == 200


def test_mapping_manager_or_target_clears_affected_grants(manager_client):
    client, Session = manager_client
    assert login(client, "admin", "adminpass1").status_code == 200
    h = headers(client)
    grant = {"department": "inquiry", "permission": "password_reset"}
    assert client.post("/auth/admin/managers/2/users/3/grants", json=grant, headers=h).status_code == 200
    assert client.patch("/auth/admin/users/2", json={"role": "operations", "department": "after_sales", "manager_overlay_enabled": True}, headers=h).status_code == 200
    with Session() as db:
        assert db.query(ManagerPermissionGrant).count() == 0
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="after_sales", permission="password_reset", granted_by_user_id=1)); db.commit()
    assert client.patch("/auth/admin/users/3", json={"role": "staff", "department": "after_sales"}, headers=headers(client)).status_code == 200
    with Session() as db:
        assert db.query(ManagerPermissionGrant).count() == 0


def test_disabling_manager_overlay_clears_all_manager_grants(manager_client):
    client, Session = manager_client
    assert login(client, "worker", "workerpass1").status_code == 200
    target_cookies = dict(client.cookies)
    with Session() as db:
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="password_reset", granted_by_user_id=1))
        db.commit()
    assert login(client, "manager", "managerpass1").status_code == 200
    manager_cookies = dict(client.cookies)
    assert login(client, "admin", "adminpass1").status_code == 200
    response = client.patch(
        "/auth/admin/users/2",
        json={"role": "operations", "department": "inquiry", "manager_overlay_enabled": False},
        headers=headers(client),
    )
    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 200
    with Session() as db:
        assert db.query(ManagerPermissionGrant).filter_by(manager_user_id=2).count() == 0
    client.cookies.clear()
    client.cookies.update(manager_cookies)
    assert client.get("/auth/me").status_code == 401
    client.cookies.clear()
    client.cookies.update(target_cookies)
    assert client.get("/auth/me").status_code == 401
    assert login(client, "manager", "managerpass1").status_code == 200
    denied = client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client))
    assert denied.status_code == 403


def test_non_overlay_base_role_keeps_existing_retry_scope(manager_client):
    client, Session = manager_client
    with Session() as db:
        operator = User(username="plain-operator", password_hash=hash_password("plainpass1"), role="operations", department="inquiry", is_active=True, must_change_password=False)
        db.add(operator)
        db.flush()
        account = ChannelAccount(owner_user_id=operator.id, channel_type="gmail", status="connected")
        db.add(account)
        db.flush()
        db.add(ChannelGrant(channel_account_id=account.id, channel_type="gmail", owner_user_id=operator.id))
        inquiry = Inquiry(customer_contact="base@example.invalid", normalized_customer_contact="base@example.invalid", contact_identity_state="certain", contact_identity_kind="email", customer_nickname="Base", raw_message="fixture", department="inquiry", source_channel_account_id=account.id, status="new", handling_status="pending")
        db.add(inquiry)
        db.flush()
        message = Message(channel_account_id=account.id, provider="fixture", external_message_id="base-retry", raw_content="fixture", direction="inbound", status="received", handling_status="pending", occurred_at=datetime.now(timezone.utc))
        db.add(message)
        db.flush()
        db.add(InquiryMessage(inquiry_id=inquiry.id, message_id=message.id, position=1, link_source="fixture"))
        db.add(MessageOverview(message_id=message.id, status="failed", failure_code="fixture"))
        db.commit()
        message_id = message.id
    assert login(client, "plain-operator", "plainpass1").status_code == 200
    response = client.post(f"/api/messages/{message_id}/overview/retry", headers=headers(client))
    assert response.status_code == 200


@pytest.mark.parametrize("change", [{"role": "sales", "department": "inquiry", "manager_overlay_enabled": True}, {"role": "operations", "department": "after_sales", "manager_overlay_enabled": True}])
def test_manager_role_or_department_change_revokes_manager_and_target_sessions(manager_client, change):
    client, Session = manager_client
    with Session() as db:
        db.add(ManagerPermissionGrant(manager_user_id=2, target_user_id=3, department="inquiry", permission="password_reset", granted_by_user_id=1))
        db.commit()
    assert login(client, "manager", "managerpass1").status_code == 200
    manager_session = dict(client.cookies)
    with TestClient(app, base_url="https://testserver") as target_client:
        assert login(target_client, "worker", "workerpass1").status_code == 200
        target_session = dict(target_client.cookies)
    assert login(client, "admin", "adminpass1").status_code == 200
    assert client.patch("/auth/admin/users/2", json=change, headers=headers(client)).status_code == 200
    client.cookies.clear(); client.cookies.update(manager_session)
    assert client.get("/auth/me").status_code == 401
    client.cookies.clear(); client.cookies.update(target_session)
    assert client.get("/auth/me").status_code == 401


def test_enabling_manager_overlay_on_existing_role_allows_only_new_explicit_grants_and_revokes_session(manager_client):
    client, Session = manager_client
    with Session() as db:
        manager = User(username="existing-operator", password_hash=hash_password("operatorpass1"), role="operations", department="inquiry", is_active=True, must_change_password=False)
        db.add(manager)
        db.commit()
        manager_id = manager.id
    assert login(client, "existing-operator", "operatorpass1").status_code == 200
    previous_session = dict(client.cookies)
    assert client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client)).status_code == 403
    assert login(client, "admin", "adminpass1").status_code == 200
    enabled = client.patch(f"/auth/admin/users/{manager_id}", json={"role": "operations", "department": "inquiry", "manager_overlay_enabled": True}, headers=headers(client))
    assert enabled.status_code == 200
    client.cookies.clear(); client.cookies.update(previous_session)
    assert client.get("/auth/me").status_code == 401
    assert login(client, "existing-operator", "operatorpass1").status_code == 200
    assert client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client)).status_code == 403
    with Session() as db:
        db.add(ManagerPermissionGrant(manager_user_id=manager_id, target_user_id=3, department="inquiry", permission="password_reset", granted_by_user_id=1))
        db.commit()
    assert client.post("/auth/manager/users/3/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client)).status_code == 200


def test_unassigned_manager_cannot_authorize_same_bucket_target(manager_client):
    client, Session = manager_client
    with Session() as db:
        manager = db.get(User, 2)
        manager.department = "unassigned"
        db.add(User(username="legacy-unassigned-target", password_hash=hash_password("targetpass1"), role="staff", department="unassigned", is_active=True, must_change_password=False))
        db.commit()
    assert login(client, "manager", "managerpass1").status_code == 200
    denied = client.post("/auth/manager/users/5/password-reset", json={"temporary_password": "resetpass1"}, headers=headers(client))
    assert denied.status_code == 403


def test_manager_cannot_self_delegate_adjust_grants_but_can_delegate_lesser_action_after_admin_bootstrap(manager_client):
    client, _ = manager_client
    assert login(client, "manager", "managerpass1").status_code == 200
    h = headers(client)
    assert client.post("/auth/manager/users/3/grants", json={"department": "inquiry", "permission": "adjust_grants"}, headers=h).status_code == 403
    assert login(client, "admin", "adminpass1").status_code == 200
    assert client.post("/auth/admin/managers/2/users/3/grants", json={"department": "inquiry", "permission": "adjust_grants"}, headers=headers(client)).status_code == 200
    assert login(client, "manager", "managerpass1").status_code == 200
    assert client.post("/auth/manager/users/3/grants", json={"department": "inquiry", "permission": "password_reset"}, headers=headers(client)).status_code == 200
