import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserSession

SESSION_COOKIE = "ea_session"
CSRF_COOKIE = "ea_csrf"
SESSION_TTL = timedelta(hours=8)
password_hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=1)
DUMMY_PASSWORD_HASH = password_hasher.hash("dummy-credential-not-used-for-login")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password(password: str) -> None:
    if not 6 <= len(password) <= 15:
        raise ValueError("Password must be 6 to 15 Unicode characters")
    try:
        password.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Password contains invalid Unicode characters") from exc


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_session(user: User, db: Session, response: Response) -> str:
    raw_session = secrets.token_urlsafe(32)
    raw_csrf = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=digest(raw_session),
        csrf_token_hash=digest(raw_csrf),
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
    )
    db.add(session)
    db.flush()
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        raw_csrf,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )
    return raw_csrf


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或会话已失效")


def get_session_user(request: Request, db: Session) -> tuple[User, UserSession]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()

    session = db.scalar(select(UserSession).where(UserSession.token_hash == digest(token)))
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None:
        raise _unauthorized()
    expiry = session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= now:
        raise _unauthorized()

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user, session


def expected_origin() -> str:
    configured = os.environ.get("AUTH_ORIGIN")
    if not configured:
        raise HTTPException(status_code=503, detail="认证来源尚未配置")
    normalized = configured.rstrip("/")
    if not normalized.startswith("https://"):
        raise HTTPException(status_code=503, detail="AUTH_ORIGIN 必须使用 HTTPS")
    return normalized


def csrf_check(request: Request, session: UserSession) -> None:
    origin = request.headers.get("origin")
    expected = expected_origin()
    if origin is None or not hmac.compare_digest(origin.rstrip("/"), expected):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")

    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token:
        raise HTTPException(status_code=403, detail="CSRF 校验失败")
    if not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")
    if not hmac.compare_digest(digest(header_token), session.csrf_token_hash):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


def authenticated_pair(
    request: Request, db: Session = Depends(get_db)
) -> tuple[User, UserSession]:
    return get_session_user(request, db)


def require_csrf(
    request: Request,
    pair: Annotated[tuple[User, UserSession], Depends(authenticated_pair)],
) -> tuple[User, UserSession]:
    csrf_check(request, pair[1])
    user, _ = pair
    if user.must_change_password and request.url.path not in {"/auth/password", "/auth/logout"}:
        raise HTTPException(status_code=403, detail="首次登录必须修改密码")
    return pair


def current_user_and_session(
    request: Request, db: Session = Depends(get_db)
) -> tuple[User, UserSession]:
    return get_session_user(request, db)


def current_user_forced_change_allowed(
    pair: Annotated[tuple[User, UserSession], Depends(current_user_and_session)],
) -> User:
    user, _ = pair
    if not user.must_change_password:
        raise HTTPException(status_code=409, detail="当前账号不需要强制修改密码")
    return user


def current_user(
    pair: Annotated[tuple[User, UserSession], Depends(current_user_and_session)],
) -> User:
    user, _ = pair
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="首次登录必须修改密码")
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="没有权限访问")
    return user


def require_admin_csrf(
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
) -> tuple[User, UserSession]:
    user, _ = pair
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="没有权限访问")
    return pair
