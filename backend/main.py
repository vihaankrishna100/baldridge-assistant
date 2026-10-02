import os
import threading

import audit
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from rag.index import index
from repo import get_repo
from routes import admin, auth, chat, documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = get_repo()
    # On a serverless platform the lifespan runs on every cold start, and the
    # DDL is the same every time. It is idempotent, so running it is safe, but
    # it is latency nobody needs once the schema exists — set SKIP_BOOTSTRAP=1
    # in production and run it from the deploy step instead.
    if os.getenv("SKIP_BOOTSTRAP", "").strip() not in ("1", "true", "yes"):
        store.bootstrap()
    print(f"[startup] store: {type(store).__name__}")

    # Built off the request path. Signing in and loading the UI need nothing
    # from the index, so blocking startup on it just made every cold start's
    # first login wait for the whole corpus. Anything that does need it calls
    # index.wait_ready() and blocks only itself.
    if hasattr(store, "search_chunks"):
        # Postgres keeps the index in the database, so "warming" is two COUNT
        # queries. Doing it inline avoids a thread per cold start and removes
        # the window where a question arrives before the index reports ready.
        print(f"[startup] retrieval: postgres — {index.rebuild(store)} chunks")
    else:
        def _warm():
            count = index.rebuild(store)
            print(f"[startup] retrieval index ready — {count} chunks")

        threading.Thread(target=_warm, name="index-warm", daemon=True).start()
    if not settings.anthropic_api_key:
        print("[startup] WARNING: ANTHROPIC_API_KEY is not set; /chat/ask will fail")
    if not (settings.org_phone or settings.org_email):
        print(
            "[startup] WARNING: ORG_PHONE / ORG_EMAIL are blank — the fallback "
            "message will tell staff to ask a supervisor instead of giving a number"
        )
    yield

    # Drain queued audit writes before the container goes away.
    audit.flush()
    if hasattr(store, "search_chunks"):
        from repo.postgres_repo import close_pool

        close_pool()


app = FastAPI(
    title=f"{settings.org_name} Internal Assistant",
    version="1.0.0",
    lifespan=lifespan,
    # Interactive docs are off by default: the schema describes every admin
    # endpoint of a system holding private documents.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Device-Id"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Nothing here should ever be indexed or cached by an intermediary.
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never surface tracebacks: they can echo document text or file paths.
    print(f"[error] {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. Please try again or contact an administrator."},
    )


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok", "org": settings.org_name, "index": index.stats()}
