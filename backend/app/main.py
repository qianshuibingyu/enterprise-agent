from fastapi import FastAPI

from app.auth_routes import router as auth_router

app = FastAPI(
    title="Enterprise Agent API",
    version="0.1.0",
)

app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
