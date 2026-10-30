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
| GET | `/api/v1/categories` | Categories with post counts |
| GET | `/api/v1/tags` | Tags with post counts |

Postgres is the source of truth. Posts are indexed in Qdrant on create/update and removed on delete;
if Qdrant was unavailable during a write, rebuild the index with `docker compose exec api python -m app.reindex`.

## Testing
```bash
docker compose exec api pytest -q                                   # unit/integration tests (isolated blog_test DB)
postman collection run postman/blog-api.postman_collection.json     # contract checks against the running API
```

## Project layout
```
app/
  main.py          FastAPI app, CORS, startup (ensures Qdrant collection)
  config.py        Settings from env / .env (see .env.example)
  models.py        SQLAlchemy models
  schemas.py       Request/response models
  vectors.py       Qdrant store + embedders
  routers/         health, posts, categories/tags
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
