"""Rebuild the Qdrant index from Postgres: python -m app.reindex"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Post
from app.vectors import get_vector_store

if __name__ == "__main__":
    store = get_vector_store()
    store.ensure_collection()
    with SessionLocal() as db:
        posts = db.scalars(select(Post)).all()
        for post in posts:
            store.upsert(post)
    print(f"Indexed {len(posts)} posts")
