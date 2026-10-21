import importlib

import pytest
from sqlalchemy import URL


@pytest.fixture
def isolated_database_module(monkeypatch):
    """Import the config module with fake settings; never opens a connection."""
    monkeypatch.setenv("POSTGRES_USER", "unit_test_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit_test_password")
    monkeypatch.setenv("POSTGRES_DB", "unit_test_db")
    monkeypatch.setenv("DB_HOST", "test-db-host")
    monkeypatch.setenv("DB_PORT", "5544")

    import app.database as database

    return importlib.reload(database)


def test_database_url_uses_configured_values(isolated_database_module):
    url = isolated_database_module.DATABASE_URL

    assert isinstance(url, URL)
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "unit_test_user"
    assert url.password == "unit_test_password"
    assert url.host == "test-db-host"
    assert url.port == 5544
    assert url.database == "unit_test_db"


def test_database_url_defaults_to_compose_db_and_postgres_port(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "unit_test_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit_test_password")
    monkeypatch.setenv("POSTGRES_DB", "unit_test_db")
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.delenv("DB_PORT", raising=False)

    import app.database as database

    module = importlib.reload(database)

    assert module.DATABASE_URL.host == "db"
    assert module.DATABASE_URL.port == 5432


def test_missing_required_database_setting_fails_without_connecting(monkeypatch):
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit_test_password")
    monkeypatch.setenv("POSTGRES_DB", "unit_test_db")

    import app.database as database

    with pytest.raises(RuntimeError, match="POSTGRES_USER is not set"):
        importlib.reload(database)


def test_get_db_closes_session_after_use(isolated_database_module, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(isolated_database_module, "SessionLocal", lambda: session)
    dependency = isolated_database_module.get_db()

    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)
    assert session.closed
