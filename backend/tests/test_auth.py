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
                User(username="admin", password_hash=hash_password("adminpass1"), role="admin", is_active=True, must_change_password=False),
                User(username="staff", password_hash=hash_password("staffpass1"), role="staff", is_active=True, must_change_password=False),
                User(username="first-login", password_hash=hash_password("firstpass1"), role="staff", is_active=True, must_change_password=True),
            ]
        )
        db.commit()

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="https://testserver") as client:
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
    assert response.json() == {"id": 2, "username": "staff", "role": "staff"}


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
    assert auth_client.get("/auth/me").status_code == 403
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
