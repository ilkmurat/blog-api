from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import Health
from app.vectors import VectorStore, get_vector_store

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(db: Session = Depends(get_db), vectors: VectorStore = Depends(get_vector_store)):
    try:
        db.execute(text("SELECT 1"))
        postgres = "ok"
    except Exception:
        postgres = "error"
    qdrant = "ok" if vectors.healthy() else "error"
    body = Health(status="ok" if postgres == qdrant == "ok" else "degraded", postgres=postgres, qdrant=qdrant)
    return JSONResponse(body.model_dump(), status_code=200 if body.status == "ok" else 503)
