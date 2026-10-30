import json

from tests.conftest import login
from tests.test_api import make_post
from tests.test_auth_likes import MEMBER

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params=None, token_headers=None):
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={**MCP_HEADERS, **(token_headers or {})},
    )
    assert r.status_code == 200, r.text
    return r.json()


def call(client, tool, args=None, token_headers=None):
    result = rpc(client, "tools/call", {"name": tool, "arguments": args or {}}, token_headers)["result"]
    text = result["content"][0]["text"] if result["content"] else "null"
    return result.get("isError", False), (text if result.get("isError") else json.loads(text))


def seed(client, anon):
    make_post(client, title="React Hooks", content="useState and useEffect", published_at="2026-01-01T00:00:00Z")
    make_post(client, title="Postgres Indexes", content="btree index speeds up database queries",
              category="Databases", tags=["postgres"], published_at="2026-02-01T00:00:00Z")
    for _ in range(3):
        anon.post("/api/v1/posts/postgres-indexes/like")
    anon.post("/api/v1/posts/react-hooks/like")


def test_lists_all_tools(anon):
    tools = {t["name"] for t in rpc(anon, "tools/list")["result"]["tools"]}
    assert tools == {
        "list_posts", "top_liked_posts", "search_posts", "get_post", "list_categories",
        "list_tags", "site_stats", "user_stats", "admin_list_users", "hr_search", "hr_list_documents",
    }


def test_list_posts_by_category_name_or_slug(client, anon):
    seed(client, anon)
    for value in ("Databases", "databases"):
        err, body = call(anon, "list_posts", {"category": value})
        assert not err and body["total"] == 1 and body["posts"][0]["url"] == "/post/postgres-indexes"
    err, body = call(anon, "list_posts", {"category": "Cooking"})
    assert body["total"] == 0 and "Databases" in body["available"]


def test_top_liked_and_stats(client, anon):
    seed(client, anon)
    _, top = call(anon, "top_liked_posts", {"limit": 2})
    assert [(p["slug"], p["like_count"]) for p in top["posts"]] == [("postgres-indexes", 3), ("react-hooks", 1)]
    _, stats = call(anon, "site_stats")
    assert stats["posts"] == 2 and stats["total_likes"] == 4 and stats["users"] == 1


def test_search_and_get_post(client, anon):
    seed(client, anon)
    _, found = call(anon, "search_posts", {"query": "database index"})
    assert found["posts"][0]["slug"] == "postgres-indexes"
    _, post = call(anon, "get_post", {"slug": "react-hooks"})
    assert post["content"] == "useState and useEffect"
    err, msg = call(anon, "get_post", {"slug": "nope"})
    assert err and "nope" in msg


def test_user_stats_are_counts_only(anon):
    anon.post("/api/v1/auth/register", json=MEMBER)
    login(anon, "ayse", "x")
    _, stats = call(anon, "user_stats", {"days": 7})
    assert stats == {"total_users": 2, "new_signups": 2, "users_logged_in": 1, "period_days": 7}


def test_admin_tool_requires_admin_token(anon):
    anon.post("/api/v1/auth/register", json=MEMBER)
    member = login(anon, "ayse", "x")
    for headers in (None, member, {"Authorization": "Bearer bogus"}):
        err, msg = call(anon, "admin_list_users", {}, headers)
        assert err and "admin" in msg

    err, body = call(anon, "admin_list_users", {}, login(anon))
    assert not err
    ayse = next(u for u in body["users"] if u["username"] == "ayse")
    assert ayse["email"] == "ayse@example.com" and ayse["last_login"] is not None
    assert "password_hash" not in ayse
