from datetime import datetime, timezone
import os
from typing import Annotated, Protocol
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.gmail_credentials import GmailCredentialError, encrypt_refresh_token
from app.outlook_credentials import OutlookCredentialError, encrypt_refresh_token as encrypt_outlook_refresh_token
from app.outlook_oauth import OutlookOAuthClient, OutlookOAuthProviderError
from app.gmail_oauth import (
    GmailOAuthClient,
    GmailOAuthConfigurationError,
    gmail_authorization_storage_configured,
    issue_gmail_state,
)
from app.models.business import ChannelAccount
from app.models.user import User, UserSession
from app.google_gmail_client import GmailWatchHttpClient, GoogleOAuthHttpClient
from app.oauth_state import OAuthStateStore
from app.outlook_mcp import OutlookMcpClient, OutlookMcpConfigurationError, require_outlook_mcp

router = APIRouter(prefix="/api/integrations", tags=["provider-authorization"])
_oauth_states = OAuthStateStore()


def _outlook_frontend_redirect(result: str, message: str | None = None) -> RedirectResponse:
    origin = os.environ.get("AUTH_ORIGIN", "").rstrip("/") or "/"
    params = {"outlook": result}
    if message:
        params["message"] = message
    return RedirectResponse(
        url=f"{origin}/?{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _watch_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        milliseconds = int(value)
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def get_gmail_oauth_client() -> GmailOAuthClient:
    try:
        return GoogleOAuthHttpClient()
    except GmailOAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail OAuth client is not configured",
        ) from exc


def get_outlook_mcp_client() -> OutlookMcpClient:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Outlook MCP client is not used; use Microsoft Graph OAuth",
    )


def get_outlook_oauth_client() -> OutlookOAuthClient:
    try:
        return OutlookOAuthClient()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Outlook OAuth client is not configured") from exc


def _scoped_account(db: Session, user: User, account_id: int, channel_type: str) -> ChannelAccount:
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == account_id,
            ChannelAccount.channel_type == channel_type,
            ChannelAccount.id.in_(scoped_channel_account_ids(user)),
        )
    )
    if account is None:
        raise HTTPException(status_code=403, detail="没有权限访问")
    return account


@router.post("/gmail/authorize/start")
def gmail_authorize_start(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    client: GmailOAuthClient = Depends(get_gmail_oauth_client),
) -> dict[str, int | str]:
    user, _ = pair
    account = _scoped_account(db, user, account_id, "gmail")
    try:
        state = issue_gmail_state(_oauth_states, channel_account_id=account.id)
    except GmailOAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Gmail OAuth client is not configured") from exc
    return {"channel_account_id": account.id, "authorization_url": client.authorization_url(state=state)}


@router.get("/gmail/authorize/callback")
def gmail_authorize_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    user: Annotated[User, Depends(current_user)] = None,
    db: Session = Depends(get_db),
    client: GmailOAuthClient = Depends(get_gmail_oauth_client),
) -> dict[str, int | str]:
    # Validate state before configuration checks so malformed/replayed browser
    # callbacks are rejected consistently without consuming a valid state.
    pending = _oauth_states.validate_any(state)
    if pending is None:
        raise HTTPException(status_code=400, detail="OAuth state 无效或已过期")
    if not gmail_authorization_storage_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail 授权凭据安全存储尚未配置",
        )
    # The one-time state, not a browser-supplied account_id, is the account
    # binding. This avoids allowing the callback query to retarget an account.
    consumed = _oauth_states.consume_any(state)
    if consumed is None:
        raise HTTPException(status_code=400, detail="OAuth state 无效或已过期")
    account = _scoped_account(db, user, consumed.channel_account_id, "gmail")
    try:
        authorization = client.exchange_code(code=code, state=state)
        if not authorization.refresh_token:
            raise GmailCredentialError("Google OAuth did not return a refresh token")
        topic_name = os.environ.get("GMAIL_PUBSUB_TOPIC", "")
        if not topic_name:
            raise GmailOAuthConfigurationError("Gmail Pub/Sub topic is not configured")
        watch = GmailWatchHttpClient(access_token=authorization.access_token)
        watch_result = watch.start_watch(topic_name=topic_name)
        # Persist the account binding only after OAuth, scope, and Watch all
        # succeed; a failed Watch must not leave a half-connected account.
        account.gmail_credential_ciphertext = encrypt_refresh_token(authorization.refresh_token)
        account.credential_reference = "db-encrypted:gmail-refresh-token"
        account.gmail_watch_history_id = watch_result.history_id
        account.gmail_watch_expiration = _watch_expiration(watch_result.expiration)
    except GmailOAuthConfigurationError as exc:
        account.status = "system_error"
        db.commit()
        raise HTTPException(status_code=502, detail="Gmail OAuth 授权失败") from exc
    except (GmailCredentialError, GmailOAuthConfigurationError) as exc:
        account.status = "system_error"
        db.commit()
        raise HTTPException(status_code=503, detail="Gmail OAuth 凭据或 Watch 无法完成") from exc
    account.external_account_id = authorization.external_account_id
    account.status = "connected_pending_inbound"
    db.commit()
    return {"channel_account_id": account.id, "status": account.status}


@router.post("/outlook/authorize/start")
def outlook_authorize_start(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    client: OutlookOAuthClient = Depends(get_outlook_oauth_client),
) -> dict[str, int | str]:
    user, _ = pair
    account = _scoped_account(db, user, account_id, "outlook")
    state = _oauth_states.issue(channel_account_id=account.id).value
    return {"channel_account_id": account.id, "authorization_url": client.authorization_url(state=state)}


@router.get("/outlook/authorize/callback")
def outlook_authorize_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    user: Annotated[User, Depends(current_user)] = None,
    db: Session = Depends(get_db),
    client: OutlookOAuthClient = Depends(get_outlook_oauth_client),
) -> RedirectResponse:
    pending = _oauth_states.validate_any(state)
    if pending is None:
        return _outlook_frontend_redirect("error", "Outlook 授权状态无效或已过期。")
    consumed = _oauth_states.consume_any(state)
    if consumed is None:
        return _outlook_frontend_redirect("error", "Outlook 授权状态无效或已过期。")
    account = _scoped_account(db, user, consumed.channel_account_id, "outlook")
    try:
        authorization = client.exchange_code(code=code)
        if not authorization.refresh_token:
            raise OutlookCredentialError("Microsoft OAuth did not return a refresh token")
        account.outlook_credential_ciphertext = encrypt_outlook_refresh_token(authorization.refresh_token)
        account.credential_reference = "db-encrypted:outlook-refresh-token"
        account.external_account_id = authorization.external_account_id
        account.status = "connected_pending_inbound"
        db.commit()
    except OutlookCredentialError as exc:
        account.status = "system_error"
        db.commit()
        return _outlook_frontend_redirect("error", "Outlook 授权凭据无法安全保存。")
    except OutlookOAuthProviderError as exc:
        account.status = "system_error"
        db.commit()
        return _outlook_frontend_redirect("error", "Outlook 授权失败，请检查 Microsoft 应用配置。")
    except Exception as exc:
        account.status = "system_error"
        db.commit()
        return _outlook_frontend_redirect("error", "Outlook 授权失败，请稍后重试。")
    return _outlook_frontend_redirect("connected")
