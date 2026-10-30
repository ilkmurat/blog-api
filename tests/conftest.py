import os

# Isolated test database / collection, and an offline embedder (no model download).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://blog:blog@postgres:5432/blog_test")
os.environ["QDRANT_COLLECTION"] = "posts_test"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["HR_COLLECTION"] = "hr_chunks_test"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.hr import get_hr_store  # noqa: E402
from app.main import app  # noqa: E402
from app.vectors import get_vector_store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrate():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def anon():
    """Unauthenticated client on a clean database (the admin user is recreated on startup)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE hr_documents, post_likes, sessions, users, post_tags, posts, tags, categories "
                "RESTART IDENTITY CASCADE"
            )
        )
    for store in (get_vector_store(), get_hr_store()):
        if store.client.collection_exists(store.collection):
            store.client.delete_collection(store.collection)
    with TestClient(app) as c:
        yield c


def login(client, username="murat", password="murat") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def client(anon):
    """Client authenticated as the default admin."""
    with TestClient(app, headers=login(anon)) as c:
        yield c
