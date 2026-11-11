from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth_routes import router as auth_router
from app.business_routes import router as business_router
from app.channel_routes import router as channel_router
from app.gmail_routes import router as gmail_router
from app.external_routes import router as external_router
from app.provider_auth_routes import router as provider_auth_router
from app.whatsapp_routes import router as whatsapp_router
from app.whatsapp_ingress import router as whatsapp_ingress_router
from app.outlook_routes import router as outlook_router

app = FastAPI(
    title="Enterprise Agent API",
    version="0.1.0",
)

class RedactGmailCallbackAccessLog:
    """Remove callback query from the ASGI scope before server access logging."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_redacted(message):
            if message["type"] == "http.response.start":
                scope["query_string"] = b""
            await send(message)

        if scope["type"] == "http" and scope["path"] == "/api/integrations/gmail/authorize/callback":
            try:
                await self.app(scope, receive, send_redacted)
            finally:
                scope["query_string"] = b""
        else:
            await self.app(scope, receive, send)


app.add_middleware(RedactGmailCallbackAccessLog)

app.include_router(auth_router)
app.include_router(business_router)
app.include_router(channel_router)
app.include_router(gmail_router)
app.include_router(external_router)
app.include_router(provider_auth_router)
app.include_router(whatsapp_router)
app.include_router(whatsapp_ingress_router)
app.include_router(outlook_router)


@app.exception_handler(RuntimeError)
async def handle_runtime_error(_request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
