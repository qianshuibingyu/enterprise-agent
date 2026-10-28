import argparse
import getpass
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth import hash_password, validate_password
from app.database import SessionLocal
from app.models.user import User, UserSession


def reset_password(username: str, password: str, confirmation: str) -> None:
    if password != confirmation:
        raise ValueError("Passwords do not match")
    try:
        validate_password(password)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            raise LookupError("User not found")
        user.password_hash = hash_password(password)
        user.must_change_password = False
        sessions = db.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        revoked_at = datetime.now(timezone.utc)
        for session in sessions:
            session.revoked_at = revoked_at
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset an existing user's password")
    parser.add_argument("--username", required=True, help="Existing username to reset")
    args = parser.parse_args()

    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    try:
        reset_password(args.username, password, confirmation)
    except (LookupError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Password reset successfully; existing sessions were revoked.")


if __name__ == "__main__":
    main()
