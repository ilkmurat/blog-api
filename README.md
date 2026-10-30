# Inkwell Blog API

Python backend for the Inkwell blog: **FastAPI** + **PostgreSQL** (posts, categories, tags) + **Qdrant** (semantic search over post embeddings).

## Stack
| Part | Tech |
|---|---|
| API | FastAPI, Pydantic v2 |
| Database | PostgreSQL 17, SQLAlchemy 2, Alembic migrations |
| Vector DB | Qdrant 1.20, embeddings via fastembed (`BAAI/bge-small-en-v1.5`, runs locally on CPU) |
| Runtime | Docker Compose, Python 3.13 |

## Quick start
```bash
docker compose up -d --build          # postgres + qdrant + api (runs migrations on start)
docker compose exec api python -m app.seed   # optional sample posts
open http://localhost:8000/docs       # interactive Swagger UI
```
The first start downloads the embedding model (~130 MB) into the `models` volume.

## Endpoints
The contract lives in [`contract/openapi.yaml`](contract/openapi.yaml).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Postgres + Qdrant status (503 when degraded) |
| GET | `/api/v1/posts` | List posts — `page`, `page_size`, `category`, `tag`, `q` |
| POST | `/api/v1/posts` | Create (category/tags by name, created on demand) |
| GET | `/api/v1/posts/search?q=` | Semantic search (Qdrant) |
| GET/PATCH/DELETE | `/api/v1/posts/{slug}` | Read, partial update, delete |
| POST | `/api/v1/posts/{slug}/like` | Like — anonymous: unlimited, members: once per post |
| GET / POST | `/api/v1/categories` | Categories with post counts / create (admin) |
| GET / POST | `/api/v1/tags` | Tags with post counts / create (admin) |
| POST | `/api/v1/auth/register` | Sign up (username + email unique, no other validation) |
| POST | `/api/v1/auth/login`, `/api/v1/auth/logout` | Bearer-token sessions |
| GET | `/api/v1/auth/me` | Current user |
| GET / POST | `/api/v1/users` | List / create users (admin) |

## MCP server
`POST /mcp/` (Streamable HTTP, stateless) exposes read-only tools for AI clients such as
[blog-agent](https://github.com/ilkmurat/blog-agent): posts by category/tag, most liked, semantic search, stats and
user counts; `admin_list_users` requires an admin bearer token. Tool contract: [`contract/mcp-tools.md`](contract/mcp-tools.md).

Creating, editing and deleting posts, categories, tags and users requires an **admin** token.

## Auth
- Passwords are hashed with scrypt; tokens are random and stored as SHA-256 hashes in `sessions` (30-day expiry).
- An admin account is created on startup if missing: **`murat` / `murat`** by default.
  Override with `ADMIN_USERNAME` / `ADMIN_PASSWORD` before deploying anywhere public.

## Database tables
`posts` (incl. `like_count`), `categories`, `tags`, `post_tags`, `users`, `sessions`, `post_likes`
(composite primary key `(post_id, user_id)` enforces one like per member per post).

Postgres is the source of truth. Posts are indexed in Qdrant on create/update and removed on delete;
if Qdrant was unavailable during a write, rebuild the index with `docker compose exec api python -m app.reindex`.

## Testing
```bash
docker compose exec api pytest -q                                   # unit/integration tests (isolated blog_test DB)
postman collection run postman/blog-api.postman_collection.json     # contract checks against the running API
# note: the Postman run leaves a test member, category and tag behind in the target database
```

## Project layout
```
app/
  main.py          FastAPI app, CORS, startup (ensures Qdrant collection)
  config.py        Settings from env / .env (see .env.example)
  models.py        SQLAlchemy models
  schemas.py       Request/response models
  vectors.py       Qdrant store + embedders
  auth.py          auth dependencies (optional user / member / admin), admin bootstrap
  security.py      password + token hashing
  mcp_server.py    MCP tools mounted at /mcp
  routers/         health, posts, categories/tags, auth/users
  seed.py, reindex.py
alembic/           Migrations
contract/          OpenAPI contract
postman/           Postman collection
tests/             pytest suite
```

## Migrations
```bash
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic upgrade head
```
