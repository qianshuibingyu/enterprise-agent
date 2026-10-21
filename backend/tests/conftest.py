import os

# Importing app.database builds its SQLAlchemy URL at module import time.
# These are inert test-only values; tests override get_db with a disposable SQLite DB.
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password_not_used_for_network")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("AUTH_ORIGIN", "https://testserver")
