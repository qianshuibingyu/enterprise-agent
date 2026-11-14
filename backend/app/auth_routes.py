import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.channel_cleanup import purge_channel_shell
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
    require_admin_csrf,
    require_csrf,
    validate_password,
    verify_password,
)
from app.database import get_db
from app.models.business import ChannelAccount, ChannelGrant, Inquiry, Message, OperationLog
from app.models.permissions import ManagerPermissionGrant, UserCapabilityGrant, UserChannelPreauthorization, UserDepartmentGrant
from app.models.user import User, UserSession

logger = logging.getLogger("enterprise_agent.authz")
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeBody(BaseModel):
    current_password: str | None = Field(default=None, min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class EmployeeCreateBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    full_name: str | None = Field(default=None, max_length=64)
    role: str = Field(min_length=1, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    manager_overlay_enabled: bool = False
    temporary_password: str = Field(min_length=6, max_length=15)


class EmployeePasswordResetBody(BaseModel):
    temporary_password: str = Field(min_length=6, max_length=15)


class EmployeeMappingBody(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    manager_overlay_enabled: bool | None = None
    full_name: str | None = Field(default=None, max_length=64)


class DepartmentGrantBody(BaseModel):
    department: str = Field(min_length=1, max_length=64)


class ChannelPreauthorizationBody(BaseModel):
    channel_type: str = Field(min_length=1, max_length=32)


class CapabilityGrantBody(BaseModel):
    capability: str = Field(min_length=1, max_length=64)


class ManagerPermissionGrantBody(BaseModel):
    department: str = Field(min_length=1, max_length=64)
    permission: str = Field(min_length=1, max_length=64)


def _clear_user_grants(db: Session, user_id: int) -> None:
    """Clear grants on deactivation or identity remapping; reactivation is deny-by-default."""
    db.query(UserDepartmentGrant).filter(UserDepartmentGrant.user_id == user_id).delete(synchronize_session=False)
    db.query(UserChannelPreauthorization).filter(UserChannelPreauthorization.user_id == user_id).delete(synchronize_session=False)
    db.query(UserCapabilityGrant).filter(UserCapabilityGrant.user_id == user_id).delete(synchronize_session=False)
    db.query(ManagerPermissionGrant).filter(
        (ManagerPermissionGrant.manager_user_id == user_id)
        | (ManagerPermissionGrant.target_user_id == user_id)
    ).delete(synchronize_session=False)


def _revoke_user_sessions(db: Session, user_id: int, *, keep_session_id: int | None = None) -> None:
    """作废该用户的会话。

    `keep_session_id` 用于管理员改自己的设置：不把当前这条会话一起作废，
    否则保存成功后立刻 401，界面上看起来像「改了但没生效」。
    """
    query = db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if keep_session_id is not None:
        query = query.filter(UserSession.id != keep_session_id)
    query.update({UserSession.revoked_at: datetime.now(timezone.utc)}, synchronize_session=False)


class ChannelOwnerTransferBody(BaseModel):
    account_ids: list[int] = Field(min_length=1, max_length=50)
    owner_user_id: int | None = Field(default=None, gt=0)
    owner_username: str | None = Field(default=None, min_length=1, max_length=64)


_OPERATING_ROLES = {"staff", "operations", "ops"}
_MANAGER_BASE_ROLES = _OPERATING_ROLES | {"sales", "engineering", "procurement", "production"}
_MANAGER_ACTIONS = {"password_reset", "deactivate", "reactivate", "adjust_grants", "retry"}


def _manager_grant(db: Session, manager: User, target: User, action: str) -> ManagerPermissionGrant | None:
    if (
        (manager.role not in _MANAGER_BASE_ROLES and manager.role != "manager")
        or not (manager.manager_overlay_enabled or manager.role == "manager")
        or not manager.is_active
        or not manager.department
        or manager.department.strip().casefold() == "unassigned"
        or target.role == "admin"
        or target.id == manager.id
        or (action != "reactivate" and not target.is_active)
        or target.department != manager.department
    ):
        return None
    return db.scalar(select(ManagerPermissionGrant).where(
        ManagerPermissionGrant.manager_user_id == manager.id,
        ManagerPermissionGrant.target_user_id == target.id,
        ManagerPermissionGrant.department == manager.department,
        ManagerPermissionGrant.permission == action,
    ))


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


def _lock_active_admins(db: Session) -> list[User]:
    return db.scalars(
        select(User)
        .where(User.role == "admin", User.is_active.is_(True))
        .order_by(User.id)
        .with_for_update()
    ).all()


def _require_active_employee(user: User) -> None:
    """冻结停用账号的授权设置。

    停用账号无法登录，再为它配置岗位、部门或渠道授权没有意义，管理员容易误以为
    已生效。需要调整时先启用账号，避免「已停用但仍可修改授权」这种自相矛盾的状态。
    """
    if not user.is_active:
        raise HTTPException(status_code=409, detail="员工已停用，请先启用账号再修改授权")


def _audit_admin_change(
    db: Session,
    admin: User,
    *,
    operation: str,
    object_type: str,
    object_id: int | None,
    detail: str | None = None,
) -> None:
    db.add(OperationLog(
        actor_user_id=admin.id,
        actor_name=admin.username,
        operation_name=operation,
        object_type=object_type,
        object_id=object_id,
        result="success",
        detail=detail,
    ))


@router.get("/csrf")
def csrf_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    # Same-origin browsers may omit Origin on a safe GET. The state-changing
    # login endpoint still performs the strict origin + double-submit checks.
    origin = request.headers.get("origin")
    if origin is not None:
        _check_origin(request)
    token = secrets.token_urlsafe(32)
    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == digest(session_token)))
        if session is not None and session.revoked_at is None:
            cookie_token = request.cookies.get(CSRF_COOKIE)
            if cookie_token and secrets.compare_digest(digest(cookie_token), session.csrf_token_hash):
                token = cookie_token
            else:
                session.csrf_token_hash = digest(token)
                db.commit()
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
def me(
    pair: Annotated[tuple[User, UserSession], Depends(authenticated_pair)],
) -> dict[str, str | int | bool | None]:
    user, _ = pair
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "department": user.department,
        "manager_overlay_enabled": user.manager_overlay_enabled or user.role == "manager",
        "must_change_password": user.must_change_password,
    }


@router.get("/admin-check")
def admin_check(user: Annotated[User, Depends(require_admin)]) -> dict[str, str]:
    logger.info("administrator authorization verification", extra={"actor_id": user.id})
    return {"status": "admin"}


@router.post("/admin/users", status_code=201)
def create_employee(
    body: EmployeeCreateBody,
    _admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, int | str | bool]:
    _admin, _ = _admin_pair
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="用户名不能为空")
    if body.department is not None and not body.department.strip():
        raise HTTPException(status_code=422, detail="部门名称不能为空")
    department = body.department.strip() if body.department else None
    legacy_manager_role = body.role == "manager"
    if legacy_manager_role:
        body.manager_overlay_enabled = True
    if body.role not in {"admin", "staff", "operations", "ops", "sales", "engineering", "procurement", "production", "manager"}:
        raise HTTPException(status_code=422, detail="角色无效")
    if department is None:
        raise HTTPException(status_code=422, detail="所有账号必须指定所属部门")
    role = "operations" if legacy_manager_role else body.role
    manager_overlay_enabled = body.manager_overlay_enabled
    if manager_overlay_enabled and role not in _MANAGER_BASE_ROLES:
        raise HTTPException(status_code=422, detail="该岗位不能启用经理叠加权限")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=username,
        full_name=(body.full_name or "").strip() or username,
        password_hash=hash_password(body.temporary_password),
        role=role,
        department=department,
        manager_overlay_enabled=manager_overlay_enabled,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    _audit_admin_change(db, _admin, operation="创建员工", object_type="user", object_id=user.id, detail=f"role={user.role}; department={user.department or ''}")
    db.commit()
    db.refresh(user)
    logger.info("administrator created employee", extra={"actor_id": _admin.id, "target_id": user.id})
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "manager_overlay_enabled": user.manager_overlay_enabled,
        "must_change_password": True,
    }


@router.get("/admin/users")
def list_employees(
    _admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    users = db.scalars(select(User).order_by(User.id)).all()
    user_ids = [user.id for user in users]
    manager_grants = db.scalars(
        select(ManagerPermissionGrant).where(ManagerPermissionGrant.manager_user_id.in_(user_ids))
    ).all() if user_ids else []
    manager_grants_by_user: dict[int, list[dict[str, object]]] = {}
    for grant in manager_grants:
        manager_grants_by_user.setdefault(grant.manager_user_id, []).append({
            "target_user_id": grant.target_user_id,
            "department": grant.department,
            "permission": grant.permission,
        })
    department_grants = db.scalars(
        select(UserDepartmentGrant).where(UserDepartmentGrant.user_id.in_(user_ids))
    ).all() if user_ids else []
    channel_grants = db.scalars(
        select(UserChannelPreauthorization).where(UserChannelPreauthorization.user_id.in_(user_ids))
    ).all() if user_ids else []
    capability_grants = db.scalars(
        select(UserCapabilityGrant).where(UserCapabilityGrant.user_id.in_(user_ids))
    ).all() if user_ids else []
    departments_by_user: dict[int, list[str]] = {}
    channels_by_user: dict[int, list[str]] = {}
    capabilities_by_user: dict[int, list[str]] = {}
    for grant in department_grants:
        departments_by_user.setdefault(grant.user_id, []).append(grant.department)
    for grant in channel_grants:
        channels_by_user.setdefault(grant.user_id, []).append(grant.channel_type)
    for grant in capability_grants:
        capabilities_by_user.setdefault(grant.user_id, []).append(grant.capability)
    return [
        {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "department": user.department,
            "manager_overlay_enabled": user.manager_overlay_enabled or user.role == "manager",
            "manager_grants": manager_grants_by_user.get(user.id, []),
            "is_active": user.is_active,
            "must_change_password": user.must_change_password,
            "department_grants": sorted(departments_by_user.get(user.id, [])),
            "channel_preauthorizations": sorted(channels_by_user.get(user.id, [])),
            "capability_grants": sorted(capabilities_by_user.get(user.id, [])),
        }
        for user in users
    ]


@router.patch("/admin/users/{user_id}")
def map_employee(
    user_id: int,
    body: EmployeeMappingBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    admin, admin_session = admin_pair
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _require_active_employee(user)
    if body.role not in {"admin", "staff", "operations", "ops", "sales", "engineering", "procurement", "production", "manager"}:
        raise HTTPException(status_code=422, detail="角色无效")
    if body.department is not None and not body.department.strip():
        raise HTTPException(status_code=422, detail="部门名称不能为空")
    department = body.department.strip() if body.department else None
    if department is None:
        raise HTTPException(status_code=422, detail="所有账号必须指定所属部门")
    if user.role == "admin" and user.is_active and body.role != "admin":
        if len(_lock_active_admins(db)) <= 1:
            raise HTTPException(status_code=409, detail="不能调整最后一个有效管理员")
    # 只改姓名（纠正错别字）不动授权：姓名不参与任何鉴权，没必要清授权、踢会话。
    legacy_manager_role = body.role == "manager"
    manager_overlay_enabled = user.manager_overlay_enabled or user.role == "manager" or legacy_manager_role
    if body.manager_overlay_enabled is not None:
        manager_overlay_enabled = body.manager_overlay_enabled
    mapped_role = "operations" if legacy_manager_role else body.role
    if manager_overlay_enabled and mapped_role not in _MANAGER_BASE_ROLES:
        raise HTTPException(status_code=422, detail="该岗位不能启用经理叠加权限")
    identity_changed = user.role != mapped_role or user.department != department
    authorization_changed = identity_changed or manager_overlay_enabled != user.manager_overlay_enabled
    if body.full_name is not None:
        full_name = body.full_name.strip()
        if not full_name:
            raise HTTPException(status_code=422, detail="员工姓名不能为空")
        user.full_name = full_name
    previous_manager_overlay = user.manager_overlay_enabled or user.role == "manager"
    manager_grant_targets = (
        db.scalars(
            select(ManagerPermissionGrant.target_user_id).where(
                ManagerPermissionGrant.manager_user_id == user.id
            )
        ).all()
        if identity_changed or previous_manager_overlay != manager_overlay_enabled
        else []
    )
    user.role = mapped_role
    user.department = department
    user.manager_overlay_enabled = manager_overlay_enabled
    if identity_changed:
        _clear_user_grants(db, user.id)
    elif previous_manager_overlay != manager_overlay_enabled:
        # Overlay changes never preserve stale manager authority.
        db.query(ManagerPermissionGrant).filter(
            ManagerPermissionGrant.manager_user_id == user.id
        ).delete(synchronize_session=False)
    if authorization_changed:
        _revoke_user_sessions(
            db,
            user.id,
            keep_session_id=admin_session.id if user.id == admin.id else None,
        )
        for target_id in manager_grant_targets:
            _revoke_user_sessions(db, target_id)
    _audit_admin_change(
        db,
        admin,
        operation="调整员工资料、角色与部门",
        object_type="user",
        object_id=user.id,
        detail=f"full_name={user.full_name}; role={user.role}; department={user.department or ''}",
    )
    db.commit()
    logger.info("administrator mapped employee", extra={"actor_id": admin.id, "target_id": user.id})
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "department": user.department,
        "manager_overlay_enabled": user.manager_overlay_enabled,
    }


@router.post("/admin/users/{user_id}/department-grants")
def grant_department(
    user_id: int,
    body: DepartmentGrantBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    admin, _ = admin_pair
    department = body.department.strip()
    if not department:
        raise HTTPException(status_code=422, detail="部门名称不能为空")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _require_active_employee(user)
    if db.scalar(select(UserDepartmentGrant.id).where(UserDepartmentGrant.user_id == user_id, UserDepartmentGrant.department == department)) is None:
        db.add(UserDepartmentGrant(user_id=user_id, department=department, granted_by_user_id=admin.id))
        _audit_admin_change(db, admin, operation="授予部门访问", object_type="user", object_id=user_id, detail=department)
        db.commit()
    return {"status": "granted", "department": body.department}


@router.delete("/admin/users/{user_id}/department-grants/{department}")
def revoke_department(
    user_id: int,
    department: str,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _require_active_employee(user)
    grant = db.scalar(select(UserDepartmentGrant).where(UserDepartmentGrant.user_id == user_id, UserDepartmentGrant.department == department))
    if grant is None:
        raise HTTPException(status_code=404, detail="部门授权不存在")
    db.delete(grant)
    _audit_admin_change(db, admin, operation="撤销部门访问", object_type="user", object_id=user_id, detail=department)
    db.commit()
    return {"status": "revoked"}


@router.post("/admin/users/{user_id}/channel-preauthorizations")
def grant_channel_preauthorization(
    user_id: int,
    body: ChannelPreauthorizationBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    if body.channel_type not in {"gmail", "outlook", "whatsapp"}:
        raise HTTPException(status_code=422, detail="渠道类型无效")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _require_active_employee(user)
    if user.role not in {"staff", "operations", "ops"}:
        raise HTTPException(status_code=409, detail="仅运营岗位可获渠道预授权")
    if db.scalar(select(UserChannelPreauthorization.id).where(UserChannelPreauthorization.user_id == user_id, UserChannelPreauthorization.channel_type == body.channel_type)) is None:
        db.add(UserChannelPreauthorization(user_id=user_id, channel_type=body.channel_type, granted_by_user_id=admin.id))
        _audit_admin_change(db, admin, operation="授予渠道预授权", object_type="user", object_id=user_id, detail=body.channel_type)
        db.commit()
    return {"status": "granted", "channel_type": body.channel_type}


@router.delete("/admin/users/{user_id}/channel-preauthorizations/{channel_type}")
def revoke_channel_preauthorization(
    user_id: int,
    channel_type: str,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    if channel_type not in {"gmail", "outlook", "whatsapp"}:
        raise HTTPException(status_code=422, detail="渠道类型无效")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _require_active_employee(user)
    grant = db.scalar(select(UserChannelPreauthorization).where(UserChannelPreauthorization.user_id == user_id, UserChannelPreauthorization.channel_type == channel_type))
    if grant is None:
        raise HTTPException(status_code=404, detail="渠道预授权不存在")
    db.delete(grant)
    _audit_admin_change(db, admin, operation="撤销渠道预授权", object_type="user", object_id=user_id, detail=channel_type)
    db.commit()
    return {"status": "revoked"}


@router.post("/admin/users/{user_id}/capability-grants")
def grant_capability(
    user_id: int,
    body: CapabilityGrantBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    # No individual capability has a confirmed Stage 1 enforcement point yet.
    raise HTTPException(status_code=422, detail="当前阶段未开放个人授权项")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if db.scalar(select(UserCapabilityGrant.id).where(UserCapabilityGrant.user_id == user_id, UserCapabilityGrant.capability == body.capability)) is None:
        db.add(UserCapabilityGrant(user_id=user_id, capability=body.capability, granted_by_user_id=admin.id))
        _audit_admin_change(db, admin, operation="授予个人授权", object_type="user", object_id=user_id, detail=body.capability)
        db.commit()
    return {"status": "granted", "capability": body.capability}


@router.delete("/admin/users/{user_id}/capability-grants/{capability}")
def revoke_capability(
    user_id: int,
    capability: str,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    raise HTTPException(status_code=422, detail="当前阶段未开放个人授权项")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    grant = db.scalar(select(UserCapabilityGrant).where(UserCapabilityGrant.user_id == user_id, UserCapabilityGrant.capability == capability))
    if grant is None:
        raise HTTPException(status_code=404, detail="个人授权不存在")
    db.delete(grant)
    _audit_admin_change(db, admin, operation="撤销个人授权", object_type="user", object_id=user_id, detail=capability)
    db.commit()
    return {"status": "revoked"}


@router.get("/admin/channel-accounts")
def list_admin_channel_accounts(
    _admin: Annotated[User, Depends(require_admin)],
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    accounts = db.scalars(select(ChannelAccount).order_by(ChannelAccount.id)).all()
    return [
        {
            "id": account.id,
            "owner_user_id": account.owner_user_id,
            "channel_type": account.channel_type,
            "external_account_id": account.external_account_id,
            "status": account.status,
            "history_access_revoked": account.history_access_revoked_at is not None,
        }
        for account in accounts
    ]


@router.post("/admin/channel-accounts/{account_id}/history-access")
def regrant_channel_history(
    account_id: int,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    admin, _ = admin_pair
    account = db.get(ChannelAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="渠道账号不存在")
    # Revoking a channel writes BOTH status="revoked" and this timestamp.
    # Clearing only the timestamp leaves the account filtered out of every
    # scope query, so the operator still sees "尚未创建" and account creation
    # keeps returning 403. Reset the shell so it can be authorized again.
    account.history_access_revoked_at = None
    if account.status == "revoked":
        account.status = "not_ready"
    _audit_admin_change(
        db,
        admin,
        operation="重新授权渠道历史访问",
        object_type="channel_account",
        object_id=account.id,
        detail=f"channel_type={account.channel_type}",
    )
    db.commit()
    logger.info("administrator regranted channel history access", extra={"actor_id": admin.id, "account_id": account.id})
    return {
        "status": "granted",
        "channel_account_id": account.id,
        "channel_type": account.channel_type,
        "account_status": account.status,
    }


def _resolve_transfer_target(db: Session, body: ChannelOwnerTransferBody) -> User:
    if (body.owner_user_id is None) == (body.owner_username is None):
        raise HTTPException(status_code=422, detail="请提供 owner_user_id 或 owner_username 其中之一")
    if body.owner_user_id is not None:
        target = db.get(User, body.owner_user_id)
    else:
        target = db.scalar(select(User).where(User.username == body.owner_username))
    if target is None:
        raise HTTPException(status_code=404, detail="接收员工不存在")
    if not target.is_active:
        raise HTTPException(status_code=409, detail="接收员工已停用，不能接收渠道账号")
    if target.role not in _OPERATING_ROLES:
        raise HTTPException(
            status_code=409,
            detail="渠道账号只能转给在岗的运营岗位员工（staff / operations / ops）；管理员与运营同时持有同一渠道会造成消息处理冲突",
        )
    return target


def _rebind_channel_owner(db: Session, account: ChannelAccount, target_id: int) -> None:
    """Rebuild the composite-FK grant around the new owner.

    channel_grants references (id, channel_type, owner_user_id). Updating only
    channel_accounts.owner_user_id would either violate that FK on PostgreSQL
    or leave an orphaned grant that silently hides every message from the new
    owner. Delete-first / insert-after keeps both sides consistent in one
    transaction and guarantees exactly one owner per account.
    """
    db.execute(delete(ChannelGrant).where(ChannelGrant.channel_account_id == account.id))
    db.execute(
        update(ChannelAccount)
        .where(ChannelAccount.id == account.id)
        .values(owner_user_id=target_id)
    )
    db.execute(
        insert(ChannelGrant).values(
            channel_account_id=account.id,
            channel_type=account.channel_type,
            owner_user_id=target_id,
        )
    )


def _retire_stale_shell(db: Session, shell: ChannelAccount, destination_account_id: int) -> tuple[int, bool]:
    """Retire an unused same-channel shell and keep its history reachable.

    Operators who click "开始授权" and then "撤销本地连接" leave a revoked
    shell behind. That dead shell used to block every later transfer and made
    the account picker return 403 forever. Retire it (never delete it) and
    re-point non-duplicated messages at the account that is being transferred.
    """
    existing_keys = set(db.execute(
        select(Message.provider, Message.external_message_id)
        .where(Message.channel_account_id == destination_account_id)
    ).all())
    moved = 0
    for message in db.scalars(select(Message).where(Message.channel_account_id == shell.id)).all():
        key = (message.provider, message.external_message_id)
        if key in existing_keys:
            continue
        message.channel_account_id = destination_account_id
        existing_keys.add(key)
        moved += 1
    db.execute(
        update(Inquiry)
        .where(Inquiry.source_channel_account_id == shell.id)
        .values(source_channel_account_id=destination_account_id)
    )
    # Empty shells are deleted outright ("撤销就是清理干净"). Shells that still
    # hold duplicated messages or inquiries are archived, never destroyed.
    deleted = purge_channel_shell(db, shell)
    if not deleted:
        db.execute(delete(ChannelGrant).where(ChannelGrant.channel_account_id == shell.id))
        shell.status = "revoked"
    return moved, deleted


@router.post("/admin/channel-accounts/transfer-owner")
def transfer_channel_accounts_owner(
    body: ChannelOwnerTransferBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Move channel accounts (and all their history) to an operating employee.

    Legacy accounts were often created while logged in as the administrator.
    After admins were restricted to read-only inquiries, those accounts became
    invisible to the operators who actually handle messages. Ownership is the
    single source of truth for message scope, so transfer it explicitly instead
    of telling the operator to reconnect and lose the collected history.
    """
    admin, _ = admin_pair
    target = _resolve_transfer_target(db, body)
    account_ids = list(dict.fromkeys(body.account_ids))
    accounts = {
        account.id: account
        for account in db.scalars(
            select(ChannelAccount)
            .where(ChannelAccount.id.in_(account_ids))
            .order_by(ChannelAccount.id)
        ).all()
    }
    missing = [str(account_id) for account_id in account_ids if account_id not in accounts]
    if missing:
        raise HTTPException(status_code=404, detail=f"渠道账号不存在：{', '.join(missing)}")
    account_channel_types = {aid: account.channel_type for aid, account in accounts.items()}

    transferred: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    retired_shells: list[dict[str, object]] = []
    preauthorizations_granted: list[str] = []
    for account_id in account_ids:
        # A "select all" batch can include stale shells that an earlier account
        # in this same batch just cleaned up. Count at the DB level (the ORM
        # identity map may still hold the deleted object) and skip it safely.
        still_present = db.scalar(
            select(func.count()).select_from(ChannelAccount)
            .where(ChannelAccount.id == account_id)
        ) or 0
        if not still_present:
            skipped.append({
                "id": account_id,
                "channel_type": account_channel_types[account_id],
                "reason": "该旧账号已在本次转移中清理",
            })
            continue
        account = accounts[account_id]
        if account.owner_user_id == target.id:
            skipped.append({
                "id": account.id,
                "channel_type": account.channel_type,
                "reason": f"该账号已归属 {target.username}",
            })
            continue
        same_channel = db.scalars(
            select(ChannelAccount)
            .where(
                ChannelAccount.owner_user_id == target.id,
                ChannelAccount.channel_type == account.channel_type,
                ChannelAccount.id != account.id,
            )
            .order_by(ChannelAccount.id)
        ).all()
        live_conflict = next((
            item for item in same_channel
            if item.status in {"connected", "connected_pending_inbound", "verified_inbound"}
            and item.history_access_revoked_at is None
        ), None)
        if live_conflict is not None:
            skipped.append({
                "id": account.id,
                "channel_type": account.channel_type,
                "reason": f"{target.username} 已有正在使用的同类型渠道账号 #{live_conflict.id}，为避免消息冲突未转移",
            })
            continue
        for shell in same_channel:
            shell_id, shell_channel = shell.id, shell.channel_type
            moved, deleted = _retire_stale_shell(db, shell, account.id)
            retired_shells.append({
                "id": shell_id,
                "channel_type": shell_channel,
                "history_messages_moved": moved,
                "deleted": deleted,
            })
        previous_owner_user_id = account.owner_user_id
        _rebind_channel_owner(db, account, target.id)
        if db.scalar(select(UserChannelPreauthorization.id).where(
            UserChannelPreauthorization.user_id == target.id,
            UserChannelPreauthorization.channel_type == account.channel_type,
        )) is None:
            db.add(UserChannelPreauthorization(
                user_id=target.id,
                channel_type=account.channel_type,
                granted_by_user_id=admin.id,
            ))
            preauthorizations_granted.append(account.channel_type)
        _audit_admin_change(
            db,
            admin,
            operation="转移渠道账号归属",
            object_type="channel_account",
            object_id=account.id,
            detail=(
                f"channel_type={account.channel_type}; "
                f"from_user_id={previous_owner_user_id}; to_user_id={target.id}"
            ),
        )
        transferred.append({
            "id": account.id,
            "channel_type": account.channel_type,
            "previous_owner_user_id": previous_owner_user_id,
        })
    db.commit()
    logger.info(
        "administrator transferred channel account ownership",
        extra={"actor_id": admin.id, "target_id": target.id, "transferred": len(transferred)},
    )
    return {
        "status": "ok",
        "owner_user_id": target.id,
        "owner_username": target.username,
        "transferred": transferred,
        "skipped": skipped,
        "retired_shells": retired_shells,
        "preauthorizations_granted": preauthorizations_granted,
    }


@router.post("/manager/users/{user_id}/password-reset")
def manager_reset_password(user_id: int, body: EmployeePasswordResetBody, pair: Annotated[tuple[User, UserSession], Depends(require_csrf)], db: Session = Depends(get_db)) -> dict[str, str]:
    manager, _ = pair
    user = db.get(User, user_id)
    if user is None or user.role == "admin" or _manager_grant(db, manager, user, "password_reset") is None:
        raise HTTPException(status_code=403, detail="未获授权的员工操作")
    user.password_hash = hash_password(body.temporary_password)
    user.must_change_password = True
    _revoke_user_sessions(db, user.id)
    db.commit()
    return {"status": "password_reset"}


@router.post("/manager/users/{user_id}/deactivate")
def manager_deactivate(user_id: int, pair: Annotated[tuple[User, UserSession], Depends(require_csrf)], db: Session = Depends(get_db)) -> dict[str, str]:
    manager, _ = pair; user = db.get(User, user_id)
    if user is None or user.role == "admin" or _manager_grant(db, manager, user, "deactivate") is None: raise HTTPException(status_code=403, detail="未获授权的员工操作")
    user.is_active = False
    _clear_user_grants(db, user.id)
    _revoke_user_sessions(db, user.id)
    _audit_admin_change(db, manager, operation="经理停用员工", object_type="user", object_id=user.id)
    db.commit()
    return {"status": "deactivated"}


@router.post("/manager/users/{user_id}/reactivate")
def manager_reactivate(user_id: int, pair: Annotated[tuple[User, UserSession], Depends(require_csrf)], db: Session = Depends(get_db)) -> dict[str, str]:
    manager, _ = pair; user = db.get(User, user_id)
    if user is None or user.role == "admin" or _manager_grant(db, manager, user, "reactivate") is None: raise HTTPException(status_code=403, detail="未获授权的员工操作")
    user.is_active = True
    _audit_admin_change(db, manager, operation="经理启用员工", object_type="user", object_id=user.id)
    db.commit()
    return {"status": "reactivated"}


@router.post("/admin/managers/{manager_id}/users/{user_id}/grants")
def admin_grant_manager_permission(
    manager_id: int,
    user_id: int,
    body: ManagerPermissionGrantBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    manager = db.get(User, manager_id)
    target = db.get(User, user_id)
    if manager is None or not manager.is_active or not manager.department or not (manager.manager_overlay_enabled or manager.role == "manager") or (manager.role not in _MANAGER_BASE_ROLES and manager.role != "manager"):
        raise HTTPException(status_code=409, detail="目标经理无效或已停用")
    if target is None or not target.is_active or target.role == "admin" or not target.department or target.id == manager.id:
        raise HTTPException(status_code=409, detail="目标员工无效、已停用或不是普通员工")
    if manager.id == target.id or not manager.department or target.department != manager.department:
        raise HTTPException(status_code=403, detail="经理与目标员工必须属于同一部门")
    if body.department != manager.department or body.permission not in _MANAGER_ACTIONS:
        raise HTTPException(status_code=422, detail="授权范围或权限无效")
    exists_grant = db.scalar(select(ManagerPermissionGrant.id).where(
        ManagerPermissionGrant.manager_user_id == manager.id,
        ManagerPermissionGrant.target_user_id == target.id,
        ManagerPermissionGrant.department == body.department,
        ManagerPermissionGrant.permission == body.permission,
    ))
    if exists_grant is None:
        db.add(ManagerPermissionGrant(
            manager_user_id=manager.id, target_user_id=target.id,
            department=body.department, permission=body.permission,
            granted_by_user_id=admin.id,
        ))
        _revoke_user_sessions(db, manager.id)
        _revoke_user_sessions(db, target.id)
        _audit_admin_change(db, admin, operation="授予经理员工权限", object_type="manager_permission_grant", object_id=manager.id,
                            detail=f"target_user_id={target.id}; department={body.department}; permission={body.permission}")
        db.commit()
    return {"status": "granted"}


@router.delete("/admin/managers/{manager_id}/users/{user_id}/grants/{permission}")
def admin_revoke_manager_permission(
    manager_id: int,
    user_id: int,
    permission: str,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    manager = db.get(User, manager_id)
    target = db.get(User, user_id)
    if manager is None or not manager.is_active or not manager.department or not (manager.manager_overlay_enabled or manager.role == "manager") or (manager.role not in _MANAGER_BASE_ROLES and manager.role != "manager") or target is None or target.role == "admin" or not target.department:
        raise HTTPException(status_code=409, detail="授权对象无效")
    if not manager.department or target.department != manager.department or permission not in _MANAGER_ACTIONS:
        raise HTTPException(status_code=422, detail="授权范围或权限无效")
    grant = db.scalar(select(ManagerPermissionGrant).where(
        ManagerPermissionGrant.manager_user_id == manager.id,
        ManagerPermissionGrant.target_user_id == target.id,
        ManagerPermissionGrant.department == manager.department,
        ManagerPermissionGrant.permission == permission,
    ))
    if grant is None:
        raise HTTPException(status_code=404, detail="授权不存在")
    db.delete(grant)
    _revoke_user_sessions(db, target.id)
    # Revoking any manager permission can invalidate the manager's authority;
    # the contract requires existing manager sessions to be dropped.
    _revoke_user_sessions(db, manager.id)
    _audit_admin_change(db, admin, operation="撤销经理员工权限", object_type="manager_permission_grant", object_id=manager.id,
                        detail=f"target_user_id={target.id}; department={manager.department}; permission={permission}")
    db.commit()
    return {"status": "revoked"}


@router.post("/manager/users/{user_id}/grants")
def manager_grant(user_id: int, body: ManagerPermissionGrantBody, pair: Annotated[tuple[User, UserSession], Depends(require_csrf)], db: Session = Depends(get_db)) -> dict[str, str]:
    manager, _ = pair; target = db.get(User, user_id)
    if target is None or not manager.department or target.department != manager.department or body.department != manager.department or target.id == manager.id or body.permission not in (_MANAGER_ACTIONS - {"adjust_grants"}) or _manager_grant(db, manager, target, "adjust_grants") is None: raise HTTPException(status_code=403, detail="未获授权的授权操作")
    if db.scalar(select(ManagerPermissionGrant.id).where(ManagerPermissionGrant.manager_user_id == manager.id, ManagerPermissionGrant.target_user_id == target.id, ManagerPermissionGrant.department == body.department, ManagerPermissionGrant.permission == body.permission)) is None:
        db.add(ManagerPermissionGrant(manager_user_id=manager.id, target_user_id=target.id, department=body.department, permission=body.permission, granted_by_user_id=manager.id))
        _revoke_user_sessions(db, target.id)
        db.commit()
    return {"status": "granted"}


@router.delete("/manager/users/{user_id}/grants/{permission}")
def manager_revoke(user_id: int, permission: str, pair: Annotated[tuple[User, UserSession], Depends(require_csrf)], db: Session = Depends(get_db)) -> dict[str, str]:
    manager, _ = pair; target = db.get(User, user_id)
    if target is None or not manager.department or target.department != manager.department or target.id == manager.id or permission == "adjust_grants" or permission not in (_MANAGER_ACTIONS - {"adjust_grants"}) or _manager_grant(db, manager, target, "adjust_grants") is None: raise HTTPException(status_code=403, detail="未获授权的授权操作")
    grant = db.scalar(select(ManagerPermissionGrant).where(ManagerPermissionGrant.manager_user_id == manager.id, ManagerPermissionGrant.target_user_id == target.id, ManagerPermissionGrant.department == manager.department, ManagerPermissionGrant.permission == permission))
    if grant is None: raise HTTPException(status_code=404, detail="授权不存在")
    db.delete(grant); _revoke_user_sessions(db, target.id); _revoke_user_sessions(db, manager.id); db.commit(); return {"status": "revoked"}


@router.post("/admin/users/{user_id}/password-reset")
def reset_employee_password(
    user_id: int,
    body: EmployeePasswordResetBody,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=409, detail="员工已停用，请先启用账号再重置密码")
    if user.role == "admin" and user.is_active and len(_lock_active_admins(db)) <= 1:
        raise HTTPException(status_code=409, detail="不能锁定最后一个有效管理员")
    user.password_hash = hash_password(body.temporary_password)
    user.must_change_password = True
    now = datetime.now(timezone.utc)
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({UserSession.revoked_at: now}, synchronize_session=False)
    _audit_admin_change(db, admin, operation="重置员工密码", object_type="user", object_id=user.id)
    db.commit()
    logger.info("administrator reset employee password", extra={"actor_id": admin.id, "target_id": user.id})
    return {"status": "password_reset"}


@router.post("/admin/users/{user_id}/deactivate")
def deactivate_employee(
    user_id: int,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin, _ = admin_pair
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and user.is_active and len(_lock_active_admins(db)) <= 1:
        raise HTTPException(status_code=409, detail="不能停用最后一个有效管理员")
    user.is_active = False
    _clear_user_grants(db, user.id)
    now = datetime.now(timezone.utc)
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({UserSession.revoked_at: now}, synchronize_session=False)
    _audit_admin_change(db, admin, operation="停用员工", object_type="user", object_id=user.id)
    db.commit()
    logger.info("administrator deactivated employee", extra={"actor_id": admin.id, "target_id": user.id})
    return {"status": "deactivated"}


@router.post("/admin/users/{user_id}/reactivate")
def reactivate_employee(
    user_id: int,
    admin_pair: Annotated[tuple[User, UserSession], Depends(require_admin_csrf)],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """恢复账号；停用时授权已清除，恢复后需管理员重新授予。"""
    admin, _ = admin_pair
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.is_active:
        return {"status": "active"}
    user.is_active = True
    _audit_admin_change(db, admin, operation="启用员工", object_type="user", object_id=user.id)
    db.commit()
    logger.info("administrator reactivated employee", extra={"actor_id": admin.id, "target_id": user.id})
    return {"status": "reactivated"}


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

