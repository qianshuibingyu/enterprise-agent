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
def isolate_background_overview_jobs(monkeypatch):
    """Keep background overview jobs out of the isolated test database.

    ``schedule_message_overview`` intentionally opens its own process-local
    session (``SessionLocal``) after the response, so it does not see the
    ``get_db`` override used by the request. Without this seam an ingest test
    would try to reach the configured PostgreSQL/LLM host and block until the
    TCP connect times out. Tests that exercise overview generation call
    ``ensure_message_overview`` directly.
    """
    from app import business_routes, external_routes, gmail_routes, outlook_routes, whatsapp_ingress

    for module in (business_routes, external_routes, gmail_routes, outlook_routes, whatsapp_ingress):
        if hasattr(module, "schedule_message_overview"):
            monkeypatch.setattr(module, "schedule_message_overview", lambda *args, **kwargs: None)


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
