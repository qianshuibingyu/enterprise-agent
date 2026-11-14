import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.user import User


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("AUTH_ORIGIN", "https://testserver")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        db.add_all(
            [
                User(username="admin", password_hash=hash_password("adminpass1"), role="admin", department="administration", is_active=True, must_change_password=False),
                User(username="staff", password_hash=hash_password("staffpass1"), role="staff", department="inquiry", is_active=True, must_change_password=False),
                User(username="first-login", password_hash=hash_password("firstpass1"), role="staff", department="inquiry", is_active=True, must_change_password=True),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver") as client:
        client.testing_session = testing_session
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client, username, password):
    csrf = client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    assert csrf.status_code == 200
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf.json()["csrf_token"]},
    )


def test_hash_password_is_argon2id_and_unicode_is_supported():
    assert hash_password("中文abc1").startswith("$argon2id$")


def test_password_length_is_six_to_fifteen_unicode_characters():
    from app.auth import validate_password

    for invalid in ("短1", "abcdefghijklmnop"):
        with pytest.raises(ValueError):
            validate_password(invalid)
    validate_password("中文密码123")


def test_anonymous_request_cannot_read_me(auth_client):
    assert auth_client.get("/auth/me").status_code == 401


def test_csrf_bootstrap_allows_same_origin_browser_get_without_origin(auth_client):
    response = auth_client.get("/auth/csrf")
    assert response.status_code == 200
    assert response.json()["csrf_token"]
    assert any(cookie.startswith("ea_csrf=") for cookie in response.headers.get_list("set-cookie"))


def test_authenticated_csrf_refresh_remains_usable_for_state_change(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    refreshed = auth_client.get("/auth/csrf")
    assert refreshed.status_code == 200
    token = refreshed.json()["csrf_token"]
    logout = auth_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": token},
    )
    assert logout.status_code == 204


def test_authenticated_csrf_requests_reuse_a_valid_cookie_token(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    original = auth_client.cookies.get("ea_csrf")
    refreshed = auth_client.get("/auth/csrf", headers={"Origin": "https://testserver"})
    assert refreshed.status_code == 200
    assert refreshed.json()["csrf_token"] == original
    logout = auth_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": original},
    )
    assert logout.status_code == 204


def test_login_sets_secure_session_and_csrf_cookies(auth_client):
    response = login(auth_client, "staff", "staffpass1")
    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("ea_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("ea_csrf="))
    assert "httponly" in session_cookie.lower() and "secure" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "secure" in csrf_cookie.lower() and "httponly" not in csrf_cookie.lower()


def test_me_returns_minimal_current_identity(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    response = auth_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == {"id": 2, "username": "staff", "role": "staff", "department": "inquiry", "manager_overlay_enabled": False, "must_change_password": False}


def test_admin_check_allows_admin_and_denies_staff_uniformly(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    denied = auth_client.get("/auth/admin-check")
    assert denied.status_code == 403
    assert denied.json()["detail"] == "没有权限访问"

    token = auth_client.cookies.get("ea_csrf")
    auth_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": token})
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    allowed = auth_client.get("/auth/admin-check")
    assert allowed.status_code == 200
    assert allowed.json() == {"status": "admin"}


def test_unknown_user_and_wrong_password_have_same_response(auth_client):
    unknown = login(auth_client, "missing", "wrongpass")
    wrong = login(auth_client, "staff", "wrongpass")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_login_requires_csrf_token_and_trusted_origin(auth_client):
    no_token = auth_client.post(
        "/auth/login",
        json={"username": "staff", "password": "staffpass1"},
        headers={"Origin": "https://testserver"},
    )
    assert no_token.status_code == 403
    csrf = auth_client.get("/auth/csrf", headers={"Origin": "https://testserver"}).json()["csrf_token"]
    wrong_origin = auth_client.post(
        "/auth/login",
        json={"username": "staff", "password": "staffpass1"},
        headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf},
    )
    assert wrong_origin.status_code == 403


def test_first_login_requires_password_change_then_reauthenticates(auth_client):
    response = login(auth_client, "first-login", "firstpass1")
    assert response.status_code == 200 and response.json()["must_change_password"] is True
    identity = auth_client.get("/auth/me")
    assert identity.status_code == 200
    assert identity.json()["must_change_password"] is True
    assert auth_client.get("/auth/admin-check").status_code == 403
    token = auth_client.cookies.get("ea_csrf")
    changed = auth_client.patch(
        "/auth/password",
        json={"new_password": "newpass123"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": token},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "password_changed"
    assert auth_client.get("/auth/me").status_code == 401
    assert login(auth_client, "first-login", "newpass123").json()["must_change_password"] is False


def test_logout_revokes_server_session(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    token = auth_client.cookies.get("ea_csrf")
    result = auth_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": token},
    )
    assert result.status_code == 204
    assert auth_client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "role,department",
    [
        ("admin", "inquiry"),
        ("staff", "inquiry"),
        ("operations", "inquiry"),
        ("ops", "inquiry"),
        ("sales", "inquiry"),
        ("engineering", "inquiry"),
        ("procurement", "inquiry"),
        ("production", "inquiry"),
        ("manager", "inquiry"),
    ],
)
def test_admin_can_create_every_supported_role_with_forced_password_change(auth_client, role, department):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    temporary_password = "temp-role-123"
    username = f"fixture-{role}"
    response = auth_client.post(
        "/auth/admin/users",
        json={
            "username": username,
            "role": role,
            "department": department,
            "manager_overlay_enabled": role == "operations",
            "temporary_password": temporary_password,
        },
        headers={"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")},
    )

    assert response.status_code == 201
    expected_role = "operations" if role == "manager" else role
    assert response.json()["role"] == expected_role
    assert response.json()["manager_overlay_enabled"] is (role in {"operations", "manager"})
    if role == "manager":
        assert response.json()["role"] == "operations"
    assert response.json()["must_change_password"] is True
    assert temporary_password not in response.text
    assert "password_hash" not in response.text

    created_login = login(auth_client, username, temporary_password)
    assert created_login.status_code == 200
    assert created_login.json()["must_change_password"] is True
    assert auth_client.get("/auth/me").json()["must_change_password"] is True


@pytest.mark.parametrize("role", ["admin", "staff", "operations", "ops", "sales", "engineering", "procurement", "production", "manager"])
@pytest.mark.parametrize("department", [None, "   "])
def test_admin_cannot_create_any_account_without_a_department(auth_client, role, department):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    response = auth_client.post(
        "/auth/admin/users",
        json={
            "username": f"missing-dept-{role}",
            "role": role,
            "department": department,
            "temporary_password": "temp-role-123",
        },
        headers={"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("department", [None, "   "])
def test_admin_cannot_remap_account_without_a_department(auth_client, department):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    response = auth_client.patch(
        "/auth/admin/users/2",
        json={"role": "staff", "department": department},
        headers={"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")},
    )
    assert response.status_code == 422


def test_identity_remapping_revokes_employee_session_and_clears_all_identity_grants(auth_client):
    from app.models.permissions import UserCapabilityGrant, UserDepartmentGrant, UserChannelPreauthorization

    assert login(auth_client, "admin", "adminpass1").status_code == 200
    headers = {"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")}
    created = auth_client.post("/auth/admin/users", json={"username": "mapped-employee", "role": "operations", "department": "inquiry", "temporary_password": "temp-role-123"}, headers=headers)
    assert created.status_code == 201
    employee_id = created.json()["id"]
    with TestClient(app, base_url="https://testserver") as employee_client:
        assert login(employee_client, "mapped-employee", "temp-role-123").status_code == 200
        old_session = dict(employee_client.cookies)
    with auth_client.testing_session() as db:
        db.add(UserDepartmentGrant(user_id=employee_id, department="after_sales", granted_by_user_id=1))
        db.add(UserChannelPreauthorization(user_id=employee_id, channel_type="gmail", granted_by_user_id=1))
        db.add(UserCapabilityGrant(user_id=employee_id, capability="message_retry", granted_by_user_id=1))
        db.commit()
    assert auth_client.patch(f"/auth/admin/users/{employee_id}", json={"role": "sales", "department": "after_sales"}, headers=headers).status_code == 200
    with TestClient(app, base_url="https://testserver") as employee_client:
        employee_client.cookies.update(old_session)
        assert employee_client.get("/auth/me").status_code == 401
    with auth_client.testing_session() as db:
        assert db.query(UserDepartmentGrant).filter_by(user_id=employee_id).count() == 0
        assert db.query(UserChannelPreauthorization).filter_by(user_id=employee_id).count() == 0
        assert db.query(UserCapabilityGrant).filter_by(user_id=employee_id).count() == 0


def test_manager_overlay_is_rejected_for_non_base_roles(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    response = auth_client.post(
        "/auth/admin/users",
        json={"username": "invalid-overlay", "role": "admin", "department": "administration", "manager_overlay_enabled": True, "temporary_password": "temp-role-123"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")},
    )
    assert response.status_code == 422


def test_admin_can_create_sales_employee_with_forced_password_change(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    temporary_password = "temp-sales-1"

    response = auth_client.post(
        "/auth/admin/users",
        json={
            "username": "fixture-sales",
            "role": "sales",
            "department": "inquiry",
            "temporary_password": temporary_password,
        },
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": 4,
        "username": "fixture-sales",
        "full_name": "fixture-sales",
        "role": "sales",
        "manager_overlay_enabled": False,
        "must_change_password": True,
    }
    assert temporary_password not in response.text
    assert "password_hash" not in response.text

    created_login = login(auth_client, "fixture-sales", temporary_password)
    assert created_login.status_code == 200
    assert created_login.json()["must_change_password"] is True
    assert auth_client.get("/auth/me").json()["must_change_password"] is True

    csrf = auth_client.cookies.get("ea_csrf")
    blocked_business_write = auth_client.post(
        "/auth/admin/users",
        json={
            "username": "should-not-be-created",
            "role": "sales",
            "department": "inquiry",
            "temporary_password": "another-temp-1",
        },
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert blocked_business_write.status_code == 403
    assert blocked_business_write.json()["detail"] == "首次登录必须修改密码"

    changed = auth_client.patch(
        "/auth/password",
        json={"new_password": "new-sales-123"},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    assert changed.json() == {"status": "password_changed"}
    assert auth_client.get("/auth/me").status_code == 401
    assert login(auth_client, "fixture-sales", temporary_password).status_code == 401
    changed_login = login(auth_client, "fixture-sales", "new-sales-123")
    assert changed_login.status_code == 200
    assert changed_login.json()["must_change_password"] is False


def test_first_login_user_can_log_out_without_changing_password(auth_client):
    assert login(auth_client, "first-login", "firstpass1").json()["must_change_password"] is True
    csrf = auth_client.cookies.get("ea_csrf")
    response = auth_client.post(
        "/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 204
    assert auth_client.get("/auth/me").status_code == 401


def test_non_admin_cannot_create_employee(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    response = auth_client.post(
        "/auth/admin/users",
        json={
            "username": "forbidden-employee",
            "role": "sales",
            "department": "inquiry",
            "temporary_password": "fixture-temp-1",
        },
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "没有权限访问"


def test_admin_can_grant_and_revoke_channel_preauthorization(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    granted = auth_client.post(
        "/auth/admin/users/2/channel-preauthorizations",
        json={"channel_type": "outlook"},
        headers=headers,
    )
    assert granted.status_code == 200
    assert granted.json() == {"status": "granted", "channel_type": "outlook"}
    repeated_grant = auth_client.post(
        "/auth/admin/users/2/channel-preauthorizations",
        json={"channel_type": "outlook"},
        headers=headers,
    )
    assert repeated_grant.status_code == 200
    employees = auth_client.get("/auth/admin/users")
    staff = next(employee for employee in employees.json() if employee["username"] == "staff")
    assert staff["channel_preauthorizations"] == ["outlook"]

    revoked = auth_client.delete(
        "/auth/admin/users/2/channel-preauthorizations/outlook",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"status": "revoked"}
    employees = auth_client.get("/auth/admin/users")
    staff = next(employee for employee in employees.json() if employee["username"] == "staff")
    assert staff["channel_preauthorizations"] == []

    repeated_revoke = auth_client.delete(
        "/auth/admin/users/2/channel-preauthorizations/outlook",
        headers=headers,
    )
    assert repeated_revoke.status_code == 404


def test_non_operating_user_cannot_receive_channel_preauthorization(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    created = auth_client.post(
        "/auth/admin/users",
        json={
            "username": "fixture-non-operator",
            "role": "sales",
            "department": "inquiry",
            "temporary_password": "fixture-temp-1",
        },
        headers=headers,
    )
    assert created.status_code == 201
    response = auth_client.post(
        f"/auth/admin/users/{created.json()['id']}/channel-preauthorizations",
        json={"channel_type": "gmail"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "仅运营岗位可获渠道预授权"


def test_admin_channel_preauthorization_does_not_revoke_existing_owned_account(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    granted = auth_client.post(
        "/auth/admin/users/2/channel-preauthorizations",
        json={"channel_type": "gmail"},
        headers=headers,
    )
    assert granted.status_code == 200
    auth_client.post("/auth/logout", headers=headers)

    assert login(auth_client, "staff", "staffpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    account = auth_client.post(
        "/api/channels/gmail/accounts",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert account.status_code == 200
    account_id = account.json()["id"]

    auth_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    revoked = auth_client.delete(
        "/auth/admin/users/2/channel-preauthorizations/gmail",
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )
    assert revoked.status_code == 200
    auth_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})

    assert login(auth_client, "staff", "staffpass1").status_code == 200
    assert auth_client.get("/api/channels/accounts").json()[0]["id"] == account_id
    assert auth_client.post(
        "/api/channels/gmail/accounts",
        headers={"Origin": "https://testserver", "X-CSRF-Token": auth_client.cookies.get("ea_csrf")},
    ).status_code == 403
    csrf = auth_client.cookies.get("ea_csrf")
    auth_client.post("/auth/logout", headers={"Origin": "https://testserver", "X-CSRF-Token": csrf})
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    accounts = auth_client.get("/auth/admin/channel-accounts")
    assert accounts.status_code == 200
    assert any(item["id"] == account_id and item["status"] == "not_ready" for item in accounts.json())



def test_employee_creation_rejects_duplicate_username_and_invalid_role(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    body = {
        "username": "fixture-sales",
        "role": "sales",
        "department": "inquiry",
        "temporary_password": "fixture-temp-1",
    }

    created = auth_client.post("/auth/admin/users", json=body, headers=headers)
    assert created.status_code == 201
    duplicate = auth_client.post("/auth/admin/users", json=body, headers=headers)
    assert duplicate.status_code == 409

    invalid_role = auth_client.post(
        "/auth/admin/users",
        json={**body, "username": "fixture-invalid", "role": "unknown-role"},
        headers=headers,
    )
    assert invalid_role.status_code == 422


def test_failed_employee_creation_commit_does_not_leave_user(auth_client, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")

    def fail_before_commit(_session):
        raise RuntimeError("simulated isolated transaction failure")

    event.listen(Session, "before_commit", fail_before_commit)
    try:
        response = auth_client.post(
            "/auth/admin/users",
            json={
                "username": "fixture-rollback",
                "role": "sales",
                "department": "inquiry",
                "temporary_password": "fixture-temp-1",
            },
            headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
        )
    finally:
        event.remove(Session, "before_commit", fail_before_commit)

    assert response.status_code == 500
    assert response.json()["detail"] == "simulated isolated transaction failure"

    employees = auth_client.get("/auth/admin/users")
    assert employees.status_code == 200
    assert all(employee["username"] != "fixture-rollback" for employee in employees.json())


def test_admin_employee_name_is_stored_listed_and_editable(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    created = auth_client.post(
        "/auth/admin/users",
        json={
            "full_name": "张三",
            "username": "zhang.san",
            "role": "sales",
            "department": "inquiry",
            "temporary_password": "temppass1",
        },
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["full_name"] == "张三"
    employee_id = created.json()["id"]

    employees = auth_client.get("/auth/admin/users").json()
    record = next(item for item in employees if item["username"] == "zhang.san")
    assert record["full_name"] == "张三"

    renamed = auth_client.patch(
        f"/auth/admin/users/{employee_id}",
        json={"role": "sales", "department": "inquiry", "full_name": " 张三丰 "},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["full_name"] == "张三丰"

    blank = auth_client.patch(
        f"/auth/admin/users/{employee_id}",
        json={"role": "sales", "department": "inquiry", "full_name": "   "},
        headers=headers,
    )
    assert blank.status_code == 422
    assert blank.json()["detail"] == "员工姓名不能为空"


def test_deactivated_employee_settings_are_frozen_until_reactivated(auth_client):
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    created = auth_client.post(
        "/auth/admin/users",
        json={
            "full_name": "李四",
            "username": "li.si",
            "role": "operations",
            "department": "业务部",
            "temporary_password": "temppass2",
        },
        headers=headers,
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]

    assert auth_client.post(f"/auth/admin/users/{employee_id}/deactivate", headers=headers).status_code == 200
    frozen = "员工已停用，请先启用账号再修改授权"

    # 停用后不能再改岗位/部门、部门授权、渠道预授权，也不能重置密码。
    role_change = auth_client.patch(
        f"/auth/admin/users/{employee_id}",
        json={"role": "sales", "department": "inquiry"},
        headers=headers,
    )
    assert role_change.status_code == 409
    assert role_change.json()["detail"] == frozen

    department_grant = auth_client.post(
        f"/auth/admin/users/{employee_id}/department-grants",
        json={"department": "工程部"},
        headers=headers,
    )
    assert department_grant.status_code == 409
    assert department_grant.json()["detail"] == frozen

    department_revoke = auth_client.delete(
        f"/auth/admin/users/{employee_id}/department-grants/业务部",
        headers=headers,
    )
    assert department_revoke.status_code == 409

    channel_grant = auth_client.post(
        f"/auth/admin/users/{employee_id}/channel-preauthorizations",
        json={"channel_type": "outlook"},
        headers=headers,
    )
    assert channel_grant.status_code == 409

    channel_revoke = auth_client.delete(
        f"/auth/admin/users/{employee_id}/channel-preauthorizations/outlook",
        headers=headers,
    )
    assert channel_revoke.status_code == 409

    password_reset = auth_client.post(
        f"/auth/admin/users/{employee_id}/password-reset",
        json={"temporary_password": "newtemp12"},
        headers=headers,
    )
    assert password_reset.status_code == 409

    # 启用后恢复可配置，重复启用是幂等的。
    reactivated = auth_client.post(f"/auth/admin/users/{employee_id}/reactivate", headers=headers)
    assert reactivated.status_code == 200
    assert reactivated.json() == {"status": "reactivated"}
    assert auth_client.post(f"/auth/admin/users/{employee_id}/reactivate", headers=headers).json() == {"status": "active"}

    after = auth_client.patch(
        f"/auth/admin/users/{employee_id}",
        json={"role": "sales", "department": "inquiry"},
        headers=headers,
    )
    assert after.status_code == 200
    assert after.json()["role"] == "sales"
    employees = auth_client.get("/auth/admin/users").json()
    record = next(item for item in employees if item["username"] == "li.si")
    assert record["is_active"] is True


def test_admin_deactivation_revokes_existing_session_until_fresh_login(auth_client):
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    employee_cookies = dict(auth_client.cookies)

    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    admin_headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    employee = next(item for item in auth_client.get("/auth/admin/users").json() if item["username"] == "staff")
    employee_id = employee["id"]
    assert auth_client.post(f"/auth/admin/users/{employee_id}/deactivate", headers=admin_headers).status_code == 200

    auth_client.cookies.clear()
    auth_client.cookies.update(employee_cookies)
    assert auth_client.get("/auth/me").status_code == 401
    assert login(auth_client, "staff", "staffpass1").status_code == 401

    auth_client.cookies.clear()
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    admin_headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    assert auth_client.post(f"/auth/admin/users/{employee_id}/reactivate", headers=admin_headers).status_code == 200

    auth_client.cookies.clear()
    auth_client.cookies.update(employee_cookies)
    assert auth_client.get("/auth/me").status_code == 401
    assert login(auth_client, "staff", "staffpass1").status_code == 200
    assert auth_client.get("/auth/me").json()["username"] == "staff"


def test_admin_can_rename_self_and_stays_logged_in(auth_client):
    """管理员改自己的姓名（纠正错别字）不应该把自己踢下线。

    旧实现里 PATCH 员工会作废目标的全部会话，目标就是自己时保存成功后
    列表刷新立刻 401，界面上看起来像「名字改不了」。
    """
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    me = next(item for item in auth_client.get("/auth/admin/users").json() if item["username"] == "admin")

    renamed = auth_client.patch(
        f"/auth/admin/users/{me['id']}",
        json={"role": "admin", "department": "inquiry", "full_name": "管理员甲"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["full_name"] == "管理员甲"

    # 会话仍然有效，而且改完立刻能在列表里读到新姓名。
    after = auth_client.get("/auth/admin/users")
    assert after.status_code == 200
    assert next(item for item in after.json() if item["username"] == "admin")["full_name"] == "管理员甲"


def test_renaming_employee_keeps_grants_and_session(auth_client):
    """只改姓名不动授权：不能顺手清掉渠道预授权、部门授权或把人踢下线。"""
    assert login(auth_client, "admin", "adminpass1").status_code == 200
    csrf = auth_client.cookies.get("ea_csrf")
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}

    created = auth_client.post(
        "/auth/admin/users",
        json={
            "full_name": "王五",
            "username": "wang.wu",
            "role": "operations",
            "department": "运营部",
            "temporary_password": "temppass3",
        },
        headers=headers,
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]
    assert auth_client.post(
        f"/auth/admin/users/{employee_id}/department-grants",
        json={"department": "工程部"},
        headers=headers,
    ).status_code == 200
    assert auth_client.post(
        f"/auth/admin/users/{employee_id}/channel-preauthorizations",
        json={"channel_type": "outlook"},
        headers=headers,
    ).status_code == 200

    with TestClient(app, base_url="https://testserver") as employee_client:
        assert login(employee_client, "wang.wu", "temppass3").status_code == 200

        renamed = auth_client.patch(
            f"/auth/admin/users/{employee_id}",
            json={"role": "operations", "department": "运营部", "full_name": "王五（运营）"},
            headers=headers,
        )
        assert renamed.status_code == 200
        record = next(item for item in auth_client.get("/auth/admin/users").json() if item["id"] == employee_id)
        assert record["full_name"] == "王五（运营）"
        assert record["department_grants"] == ["工程部"]
        assert record["channel_preauthorizations"] == ["outlook"]
        # 只改姓名不撤会话，员工不需要重新登录。
        assert employee_client.get("/auth/me").status_code == 200

        # 真正的角色变更才清授权并撤会话。
        remapped = auth_client.patch(
            f"/auth/admin/users/{employee_id}",
            json={"role": "sales", "department": "运营部"},
            headers=headers,
        )
        assert remapped.status_code == 200
        record = next(item for item in auth_client.get("/auth/admin/users").json() if item["id"] == employee_id)
        assert record["channel_preauthorizations"] == []
        assert employee_client.get("/auth/me").status_code == 401
