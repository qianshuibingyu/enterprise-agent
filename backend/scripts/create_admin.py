import getpass
import sys
from pathlib import Path

# Allow direct execution from the container as ``python scripts/create_admin.py``.
# The script's directory is otherwise placed on sys.path instead of /app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.auth import hash_password, validate_password
from app.database import SessionLocal
from app.models.user import User


def main() -> None:
    username = input("Initial administrator username: ").strip()
    if not username or len(username) > 64:
        raise SystemExit("Username must contain 1–64 characters")

    password = getpass.getpass("Initial administrator password: ")
    try:
        validate_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")

    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.role == "admin").limit(1)) is not None:
            raise SystemExit("An administrator already exists; refusing bootstrap")
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            raise SystemExit("Username already exists")
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
                must_change_password=True,
            )
        )
        db.commit()

    print("Initial administrator created. Password change is required at first login.")


if __name__ == "__main__":
    main()
