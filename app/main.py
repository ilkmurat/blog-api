import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ensure_admin
from app.config import get_settings
from app.db import SessionLocal
from app.hr import get_hr_store
from app.mcp_server import mcp_endpoint
from app.routers import auth, health, hr, posts, terms
from app.vectors import get_vector_store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _warm_hr_store() -> None:
    # Load (and on first run download) the multilingual model without blocking startup.
    try:
        get_hr_store().ensure_collection()
        log.info("HR embedding model ready")
    except Exception:
        log.exception("HR store warm-up failed; it will be retried on first use")


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_vector_store().ensure_collection()
    with SessionLocal() as db:
        ensure_admin(db)
    threading.Thread(target=_warm_hr_store, daemon=True).start()
    async with mcp_endpoint.lifespan():
        yield


app = FastAPI(title="Inkwell Blog API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(posts.router)
app.include_router(terms.router)
app.include_router(auth.router)
app.include_router(hr.router)
app.mount("/mcp", mcp_endpoint)
