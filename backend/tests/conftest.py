import os

import pytest

# Importing app.database builds its SQLAlchemy URL at module import time.
# These are inert test-only values; tests override get_db with a disposable SQLite DB.
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password_not_used_for_network")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")


@pytest.fixture(autouse=True)
def test_auth_origin(request):
    # Keep tests independent from a developer's or compose's production .env.
    # Use an independent finalizer because some tests explicitly call
    # monkeypatch.undo() while exercising rollback behavior.
    previous = os.environ.get("AUTH_ORIGIN")
    os.environ["AUTH_ORIGIN"] = "https://testserver"

    def restore():
        if previous is None:
            os.environ.pop("AUTH_ORIGIN", None)
        else:
            os.environ["AUTH_ORIGIN"] = previous

    request.addfinalizer(restore)
