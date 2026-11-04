import importlib
import os

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
    url = isolated_database_module.get_database_url()

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

    assert module.get_database_url().host == "db"
    assert module.get_database_url().port == 5432


def test_missing_required_database_setting_fails_when_url_is_requested(monkeypatch):
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "unit_test_password")
    monkeypatch.setenv("POSTGRES_DB", "unit_test_db")

    import app.database as database

    module = importlib.reload(database)
    with pytest.raises(RuntimeError, match="POSTGRES_USER is not set"):
        module.get_database_url()


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


def test_load_project_env_preserves_exported_values_and_parses_quotes(monkeypatch, tmp_path):
    import app.environment as environment

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Comment\n"
        "POSTGRES_USER=file_user\n"
        'POSTGRES_PASSWORD="file password"\n'
        "export POSTGRES_DB=file_db\n"
        "NOT-AN-ENV=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POSTGRES_USER", "exported_user")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    environment.load_project_env(env_file)

    assert os.environ["POSTGRES_USER"] == "exported_user"
    assert os.environ["POSTGRES_PASSWORD"] == "file password"
    assert os.environ["POSTGRES_DB"] == "file_db"
