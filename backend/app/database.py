import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


@lru_cache(maxsize=1)
def get_database_url() -> URL:
    """Read database configuration only when a database operation is requested."""
    return URL.create(
        drivername="postgresql+psycopg",
        username=_required_env("POSTGRES_USER"),
        password=_required_env("POSTGRES_PASSWORD"),
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=_required_env("POSTGRES_DB"),
    )


# Kept as a compatibility accessor for Alembic and existing callers. Importing
# this module does not evaluate it; callers should use get_database_url().
class _DatabaseUrlProxy:
    def __getattr__(self, name: str):
        return getattr(get_database_url(), name)

    def __str__(self) -> str:
        return str(get_database_url())


DATABASE_URL = _DatabaseUrlProxy()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


class _SessionLocalProxy:
    def __call__(self) -> Session:
        factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
        return factory()


SessionLocal = _SessionLocalProxy()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
