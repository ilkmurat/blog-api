from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import login
from tests.test_api import make_post

MEMBER = {"username": "ayse", "email": "ayse@example.com", "first_name": "Ayşe", "last_name": "Yılmaz", "password": "x"}


def member_client(anon, **overrides) -> TestClient:
    r = anon.post("/api/v1/auth/register", json={**MEMBER, **overrides})
    assert r.status_code == 201, r.text
    return TestClient(app, headers={"Authorization": f"Bearer {r.json()['token']}"})


def test_register_returns_token_and_user(anon):
    r = anon.post("/api/v1/auth/register", json=MEMBER)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["username"] == "ayse" and body["user"]["is_admin"] is False
    assert "password" not in body["user"] and "password_hash" not in body["user"]
    me = anon.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json()["email"] == "ayse@example.com"


def test_register_has_no_format_validation(anon):
    r = anon.post("/api/v1/auth/register", json={**MEMBER, "email": "not-an-email", "password": "1"})
    assert r.status_code == 201


def test_username_and_email_unique(anon):
    anon.post("/api/v1/auth/register", json=MEMBER)
    r = anon.post("/api/v1/auth/register", json={**MEMBER, "email": "other@example.com"})
    assert r.status_code == 409 and "Username" in r.json()["detail"]
    r = anon.post("/api/v1/auth/register", json={**MEMBER, "username": "other"})
    assert r.status_code == 409 and "Email" in r.json()["detail"]


def test_login_logout(anon):
    anon.post("/api/v1/auth/register", json=MEMBER)
    assert anon.post("/api/v1/auth/login", json={"username": "ayse", "password": "wrong"}).status_code == 401
    headers = login(anon, "ayse", "x")
    assert anon.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert anon.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert anon.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_default_admin_exists(anon):
    me = anon.get("/api/v1/auth/me", headers=login(anon, "murat", "murat")).json()
    assert me["is_admin"] is True


def test_writes_require_admin(anon):
    member = member_client(anon)
    body = {"title": "T", "content": "c", "category": "C"}
    for c, expected in ((anon, 401), (member, 403)):
        assert c.post("/api/v1/posts", json=body).status_code == expected
        assert c.post("/api/v1/categories", json={"name": "X"}).status_code == expected
        assert c.post("/api/v1/tags", json={"name": "x"}).status_code == expected
        assert c.get("/api/v1/users").status_code == expected
        assert c.post("/api/v1/users", json=MEMBER).status_code == expected
    assert anon.get("/api/v1/auth/me", headers={"Authorization": "Bearer bogus"}).status_code == 401


def test_admin_creates_categories_tags_and_users(client):
    r = client.post("/api/v1/categories", json={"name": "Yapay Zeka"})
    assert r.status_code == 201 and r.json() == {"name": "Yapay Zeka", "slug": "yapay-zeka", "post_count": 0}
    assert client.post("/api/v1/categories", json={"name": "yapay zeka"}).status_code == 409
    assert client.post("/api/v1/tags", json={"name": "LLM"}).status_code == 201
    assert {"name": "Yapay Zeka", "slug": "yapay-zeka", "post_count": 0} in client.get("/api/v1/categories").json()

    r = client.post("/api/v1/users", json={**MEMBER, "is_admin": True})
    assert r.status_code == 201 and r.json()["is_admin"] is True
    assert client.post("/api/v1/users", json=MEMBER).status_code == 409
    assert {u["username"] for u in client.get("/api/v1/users").json()} == {"murat", "ayse"}

    post = make_post(client, category="Yapay Zeka", tags=["LLM"])
    assert post["category"]["slug"] == "yapay-zeka" and post["tags"][0]["slug"] == "llm"


def test_anonymous_likes_are_unlimited(client, anon):
    make_post(client)
    counts = [anon.post("/api/v1/posts/hello-world/like").json() for _ in range(3)]
    assert [c["like_count"] for c in counts] == [1, 2, 3]
    assert counts[-1]["liked_by_me"] is False
    assert anon.get("/api/v1/posts/hello-world").json()["like_count"] == 3


def test_member_likes_once(client, anon):
    make_post(client)
    member = member_client(anon)
    assert member.get("/api/v1/posts/hello-world").json()["liked_by_me"] is False
    first = member.post("/api/v1/posts/hello-world/like").json()
    second = member.post("/api/v1/posts/hello-world/like").json()
    assert first == second == {"like_count": 1, "liked_by_me": True}
    assert member.get("/api/v1/posts/hello-world").json()["liked_by_me"] is True

    other = member_client(anon, username="mehmet", email="mehmet@example.com")
    assert other.post("/api/v1/posts/hello-world/like").json()["like_count"] == 2
    anon.post("/api/v1/posts/hello-world/like")
    listed = anon.get("/api/v1/posts").json()["items"][0]
    assert listed["like_count"] == 3


def test_like_missing_post(anon):
    assert anon.post("/api/v1/posts/nope/like").status_code == 404
