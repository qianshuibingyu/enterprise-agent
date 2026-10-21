import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    CSRF_COOKIE,
    DUMMY_PASSWORD_HASH,
    SESSION_COOKIE,
    authenticated_pair,
    current_user,
    digest,
    expected_origin,
    hash_password,
    issue_session,
    require_admin,
    require_csrf,
    validate_password,
    verify_password,
)
from app.database import get_db
from app.models.user import User, UserSession

logger = logging.getLogger("enterprise_agent.authz")
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeBody(BaseModel):
    current_password: str | None = Field(default=None, min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") != expected_origin():
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


def _check_login_csrf(request: Request) -> None:
    _check_origin(request)
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


@router.get("/csrf")
def csrf_token(request: Request, response: Response) -> dict[str, str]:
    _check_origin(request)
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=8 * 60 * 60,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    _check_login_csrf(request)
    user = db.scalar(select(User).where(User.username == body.username))
    valid = verify_password(user.password_hash, body.password) if user is not None else verify_password(DUMMY_PASSWORD_HASH, body.password)
    if not valid or user is None or not user.is_active:
        logger.warning("authentication failed")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    csrf_value = issue_session(user, db, response)
    db.commit()
    return {"status": "ok", "must_change_password": user.must_change_password, "csrf_token": csrf_value}


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> Response:
    _, session = pair
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="lax")
    response.status_code = 204
    return response


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]) -> dict[str, str | int]:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/admin-check")
def admin_check(user: Annotated[User, Depends(require_admin)]) -> dict[str, str]:
    logger.info("administrator authorization verification", extra={"actor_id": user.id})
    return {"status": "admin"}


@router.patch("/password")
def change_password(
    body: PasswordChangeBody,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
) -> Response:
    user, session = pair
    if not user.must_change_password and (
        body.current_password is None or not verify_password(user.password_hash, body.current_password)
    ):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="密码长度必须为 6–15 个字符") from exc

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    response = Response(status_code=200, content='{"status":"password_changed"}', media_type="application/json")
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="lax")
    return response

