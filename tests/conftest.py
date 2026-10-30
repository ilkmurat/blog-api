import os

# Isolated test database / collection, and an offline embedder (no model download).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://blog:blog@postgres:5432/blog_test")
os.environ["QDRANT_COLLECTION"] = "posts_test"
os.environ["EMBEDDING_PROVIDER"] = "hash"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.vectors import get_vector_store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def client():
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE post_tags, posts, tags, categories RESTART IDENTITY CASCADE"))
    store = get_vector_store()
    if store.client.collection_exists(store.collection):
        store.client.delete_collection(store.collection)
    with TestClient(app) as c:
        yield c
