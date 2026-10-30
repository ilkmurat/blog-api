def make_post(client, **overrides):
    body = {
        "title": "Hello World",
        "content": "Learning React components and hooks step by step.",
        "category": "Web Development",
        "tags": ["react", "javascript"],
        **overrides,
    }
    r = client.post("/api/v1/posts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "postgres": "ok", "qdrant": "ok"}


def test_create_and_get_post(client):
    post = make_post(client, tags=["React", "react", "JavaScript"])
    assert post["slug"] == "hello-world"
    assert post["category"] == {"name": "Web Development", "slug": "web-development"}
    assert sorted(t["slug"] for t in post["tags"]) == ["javascript", "react"]  # deduplicated by slug
    assert post["excerpt"].startswith("Learning React")
    assert post["reading_time"] == 1

    r = client.get("/api/v1/posts/hello-world")
    assert r.status_code == 200
    assert r.json()["content"] == post["content"]


def test_get_missing_post_returns_404(client):
    r = client.get("/api/v1/posts/nope")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_duplicate_slug_conflicts(client):
    make_post(client)
    r = client.post("/api/v1/posts", json={"title": "Hello World", "content": "x", "category": "Misc"})
    assert r.status_code == 409


def test_validation_error(client):
    r = client.post("/api/v1/posts", json={"title": "", "content": "x", "category": "Misc"})
    assert r.status_code == 422
    r = client.post("/api/v1/posts", json={"title": "Ok", "slug": "Bad Slug", "content": "x", "category": "Misc"})
    assert r.status_code == 422


def test_list_filters_and_pagination(client):
    make_post(client, title="React Basics", published_at="2026-01-01T00:00:00Z")
    make_post(client, title="CSS Grid", content="Layouts with grid", category="Design", tags=["css"],
              published_at="2026-02-01T00:00:00Z")
    make_post(client, title="Focus", content="Deep work", category="Productivity", tags=["habits"],
              published_at="2026-03-01T00:00:00Z")

    r = client.get("/api/v1/posts", params={"page_size": 2}).json()
    assert r["total"] == 3 and r["pages"] == 2
    assert [p["slug"] for p in r["items"]] == ["focus", "css-grid"]  # newest first
    assert "content" not in r["items"][0]

    assert [p["slug"] for p in client.get("/api/v1/posts", params={"category": "design"}).json()["items"]] == ["css-grid"]
    assert [p["slug"] for p in client.get("/api/v1/posts", params={"tag": "react"}).json()["items"]] == ["react-basics"]
    assert [p["slug"] for p in client.get("/api/v1/posts", params={"q": "deep"}).json()["items"]] == ["focus"]


def test_update_post(client):
    make_post(client)
    make_post(client, title="Other")
    r = client.patch("/api/v1/posts/hello-world", json={"title": "New Title", "category": "Design", "tags": ["css"]})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "New Title" and body["slug"] == "hello-world"  # slug stays stable
    assert body["category"]["slug"] == "design"
    assert [t["slug"] for t in body["tags"]] == ["css"]

    assert client.patch("/api/v1/posts/hello-world", json={"slug": "other"}).status_code == 409
    assert client.patch("/api/v1/posts/missing", json={"title": "x"}).status_code == 404


def test_delete_post(client):
    make_post(client)
    assert client.delete("/api/v1/posts/hello-world").status_code == 204
    assert client.get("/api/v1/posts/hello-world").status_code == 404
    assert client.delete("/api/v1/posts/hello-world").status_code == 404
    assert client.get("/api/v1/posts/search", params={"q": "react hooks"}).json()["items"] == []


def test_categories_and_tags_counts(client):
    make_post(client, title="A")
    make_post(client, title="B", tags=["react"])
    make_post(client, title="C", category="Design", tags=["css"])

    cats = client.get("/api/v1/categories").json()
    assert cats == [
        {"name": "Web Development", "slug": "web-development", "post_count": 2},
        {"name": "Design", "slug": "design", "post_count": 1},
    ]
    tags = {t["slug"]: t["post_count"] for t in client.get("/api/v1/tags").json()}
    assert tags == {"react": 2, "javascript": 1, "css": 1}


def test_semantic_search_ranks_relevant_post_first(client):
    make_post(client, title="React Hooks Guide", content="useState and useEffect hooks in React")
    make_post(client, title="Postgres Indexing", content="btree indexes speed up database queries",
              category="Databases", tags=["postgres"])

    r = client.get("/api/v1/posts/search", params={"q": "database indexes", "limit": 2})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["post"]["slug"] == "postgres-indexing"
    assert items[0]["score"] > items[1]["score"]

    # Updates are re-indexed
    client.patch("/api/v1/posts/react-hooks-guide", json={"content": "database indexes and query planning"})
    top = client.get("/api/v1/posts/search", params={"q": "query planning", "limit": 1}).json()["items"][0]
    assert top["post"]["slug"] == "react-hooks-guide"


def test_search_requires_query(client):
    assert client.get("/api/v1/posts/search").status_code == 422
