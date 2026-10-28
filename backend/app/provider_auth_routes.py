from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_csrf
from app.authorization import scoped_channel_account_ids
from app.database import get_db
from app.gmail_oauth import GmailOAuthClient, GmailOAuthConfigurationError, issue_gmail_state
from app.models.business import ChannelAccount
from app.models.user import User, UserSession
from app.google_gmail_client import GoogleOAuthHttpClient
from app.oauth_state import OAuthStateStore
from app.outlook_mcp import OutlookMcpClient, require_outlook_mcp

router = APIRouter(prefix="/api/integrations", tags=["provider-authorization"])
_oauth_states = OAuthStateStore()


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
        detail="Outlook MCP client is not configured",
    )


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
    account_id: int,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    user: Annotated[User, Depends(current_user)] = None,
    db: Session = Depends(get_db),
    client: GmailOAuthClient = Depends(get_gmail_oauth_client),
) -> dict[str, int | str]:
    account = _scoped_account(db, user, account_id, "gmail")
    consumed = _oauth_states.consume(state, channel_account_id=account.id)
    if consumed is None:
        raise HTTPException(status_code=400, detail="OAuth state 无效或已过期")
    authorization = client.exchange_code(code=code, state=state)
    account.external_account_id = authorization.external_account_id
    account.status = "connected"
    db.commit()
    return {"channel_account_id": account.id, "status": account.status}


@router.post("/outlook/authorize/start")
def outlook_authorize_start(
    account_id: int,
    pair: Annotated[tuple[User, UserSession], Depends(require_csrf)],
    db: Session = Depends(get_db),
    client: OutlookMcpClient = Depends(get_outlook_mcp_client),
) -> dict[str, int | str]:
    user, _ = pair
    require_outlook_mcp()
    account = _scoped_account(db, user, account_id, "outlook")
    state = _oauth_states.issue(channel_account_id=account.id).value
    return {"channel_account_id": account.id, "authorization_url": client.authorization_url(state=state)}
