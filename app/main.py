import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ensure_admin
from app.config import get_settings
from app.db import SessionLocal
from app.routers import auth, health, posts, terms
from app.vectors import get_vector_store

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_vector_store().ensure_collection()
    with SessionLocal() as db:
        ensure_admin(db)
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
