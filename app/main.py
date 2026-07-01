from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .routers import (
    auth,
    buckets,
    external,
    files,
    public,
    recurring,
    statuses,
    sync,
    todos,
    unsubscribe,
    watching,
)

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Todo", version="1.0.0")


@app.on_event("startup")
async def _startup() -> None:
    import asyncio

    from .scheduler import scheduler_loop

    init_db()
    asyncio.create_task(scheduler_loop())


app.include_router(auth.router)
app.include_router(buckets.router)
app.include_router(todos.router)
app.include_router(files.router)
app.include_router(sync.router)
app.include_router(public.router)
app.include_router(recurring.router)
app.include_router(statuses.router)
app.include_router(external.router)
app.include_router(unsubscribe.router)
app.include_router(watching.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# --- Service worker & manifest must be served from the root scope ---


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


# Static assets (css/js/icons).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- SPA + public share entry points ---


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login")
def login_page() -> FileResponse:
    # A dedicated, lightweight sign-in page the desktop (Electron) app points to,
    # instead of the full marketing landing at "/". Redirects into the app once a
    # session exists (see login.html).
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/t/{token}")
def share_page(token: str) -> FileResponse:
    # The share page reads the token from the URL client-side.
    return FileResponse(STATIC_DIR / "share.html")
