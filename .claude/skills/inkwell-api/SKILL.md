---
name: inkwell-api
description: Work on the Inkwell blog-api (FastAPI + PostgreSQL + Qdrant + MCP). Use when adding or changing REST endpoints, database tables/migrations, MCP tools, embeddings/RAG (blog search or HR documents), auth rules, or when running/debugging the API and its tests.
---

# Inkwell blog-api

FastAPI service owning all Inkwell data. Consumers: `blog-app` (REST via nginx `/api/`) and `blog-agent`
(MCP at `/mcp/`). Read `README.md` for the full map (tables, collections, endpoints, ports).

## Run and verify
The stack runs from `../blog-app`: `cd ../blog-app && docker compose up -d --build api`. Code is baked into the
image, so **rebuild after every change** (`up -d --build api`), then:

```bash
cd ../blog-app
docker compose exec -T api pytest -q -p no:warnings      # must stay green
curl -s localhost:8000/health                             # {"status":"ok","postgres":"ok","qdrant":"ok"}
postman collection run ../blog-api/postman/blog-api.postman_collection.json   # live contract checks
```
Tests use database `blog_test`, Qdrant collections `posts_test` / `hr_chunks_test` and the offline `hash`
embedder (set in `tests/conftest.py`); fixtures `anon` (clean DB, anonymous) and `client` (admin). `tests/pdf.py`
creates PDFs. The Postman run leaves a test member/category/tag in the real DB — clean up afterwards.

## Rules
- **Contract first.** Change `contract/openapi.yaml` (REST) or `contract/mcp-tools.md` (MCP) before code, then
  check the running app against it (compare `/openapi.json` paths, methods, status codes and query params with
  the contract; the contract file inside the container is stale until rebuilt).
- **Schema changes = new Alembic revision** in `alembic/versions/000N_*.py` (hand-written, `down_revision` chained).
  Never edit an applied migration. Models live in `app/models.py`.
- **Auth:** use dependencies from `app/auth.py` — `current_user_optional`, `require_user`, `require_admin`.
  Writes (posts, categories, tags, users, HR documents) are admin-only; a present-but-invalid token is 401.
- **MCP tools** (`app/mcp_server.py`): read-only, return dicts, run DB work via `_run(...)` (thread).
  Name prefix = access: none → public (never personal data), `hr_` → logged-in (`_require_login`),
  `admin_` → admin (`_caller(ctx).is_admin`). Enforce in the tool; the agent's hiding by prefix is only a second layer.
  Update `tests/test_mcp.py::test_lists_all_tools` when adding tools.
- **Two embedding spaces:** posts use `app/vectors.py` (bge-small-en, 384d); HR uses `app/hr.py`
  (multilingual-e5-large, 1024d, `passage:`/`query:` prefixes). Never mix vectors between collections; changing a
  model means recreating its collection and re-indexing (`python -m app.reindex` for posts, re-upload for HR).
- Postgres is the source of truth; Qdrant failures on post writes are logged, not fatal.
- Keep ports bound to `127.0.0.1` in `docker-compose.yml` — Qdrant has no auth and stores HR text.

## Gotchas
- MCP SDK must stay `mcp>=1.24,<2`: `langchain-mcp-adapters` (agent) needs 1.x; 2.x renamed FastMCP.
- `MCPEndpoint` creates a new `StreamableHTTPSessionManager` per app lifespan (a manager can only run once; tests
  start the app many times). New Host names calling MCP must be added to `MCP_ALLOWED_HOSTS`.
- The HR model (~2.2 GB) is loaded lazily behind a lock and warmed in a thread at startup; first start downloads it.
- In zsh scripts never name a variable `path` (it is tied to `PATH`).
