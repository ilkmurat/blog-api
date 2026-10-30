# Inkwell Blog API

Backend of the **Inkwell** blog platform: REST API, MCP server for AI clients, PostgreSQL storage and Qdrant vector
search (blog semantic search + HR document RAG).

Part of three repositories that run together:

| Repo | Role |
|---|---|
| [blog-app](https://github.com/ilkmurat/blog-app) | React frontend (blog, chat, admin panel), nginx, full-stack compose |
| **blog-api** (this) | FastAPI REST API, MCP server, PostgreSQL, Qdrant, embeddings |
| [blog-agent](https://github.com/ilkmurat/blog-agent) | LangChain chat agent on Ollama (qwen3), Langfuse tracing |

```
blog-app (nginx) ──/api──► blog-api ──► PostgreSQL 17      (posts, users, likes, HR document metadata)
                                    ├─► Qdrant 1.20         (posts: bge-small-en · hr_chunks: multilingual-e5-large)
blog-agent ──MCP /mcp/──────┘
```

## Tech stack
| Area | Technology |
|---|---|
| Language / runtime | Python 3.13 (Docker) |
| Web framework | FastAPI 0.16x, Pydantic v2, Uvicorn |
| Database | PostgreSQL 17, SQLAlchemy 2.1, Alembic migrations, psycopg 3 |
| Vector DB | Qdrant 1.20 (`qdrant-client` 1.20) |
| Embeddings | fastembed 0.9 (ONNX, CPU) — models below |
| PDF | pypdf (text extraction) |
| MCP | `mcp` Python SDK 1.x (Streamable HTTP, stateless) |
| Auth | scrypt password hashes, random bearer tokens (SHA-256 stored) |

## Embedding models (Hugging Face)
Downloaded once by fastembed into the `models` Docker volume (`/models`).

| Used for | Model | Hugging Face repo actually downloaded | Dim | Size |
|---|---|---|---|---|
| Blog post semantic search (English content) | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | [Qdrant/bge-small-en-v1.5-onnx-Q](https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q) (quantized ONNX) | 384 | ~0.07 GB |
| HR document RAG (Turkish + ~100 languages) | [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large) | [Qdrant/multilingual-e5-large-onnx](https://huggingface.co/Qdrant/multilingual-e5-large-onnx) (ONNX) | 1024 | ~2.2 GB |

multilingual-e5 requires prefixes: passages are embedded as `passage: …`, questions as `query: …` (`app/hr.py`).

## Database (PostgreSQL)
Schema is managed by Alembic (`alembic/versions/0001…0003`), applied automatically on container start.

| Table | Columns (main) | Notes |
|---|---|---|
| `posts` | id, slug (unique), title, excerpt, content (Markdown), author, category_id, published_at, created_at, updated_at, like_count | `like_count` = anonymous + member likes |
| `categories` | id, name, slug (unique) | created by admins or on demand when writing a post |
| `tags` | id, name, slug (unique) | |
| `post_tags` | post_id, tag_id | many-to-many |
| `users` | id, username (unique), email (unique), first_name, last_name, password_hash, is_admin, created_at | no format validation by design |
| `sessions` | token_hash (PK), user_id, created_at, expires_at | 30-day bearer tokens |
| `post_likes` | post_id, user_id (composite PK) | enforces one like per member per post |
| `hr_documents` | id, title, topic, filename, size_bytes, pages, chunk_count, status, error, uploaded_by_id, created_at | `status`: processing → ready / failed |

Connect with DBeaver or psql: `localhost:5432`, database `blog`, user `blog`, password `blog` (local development).
Tests use a separate database `blog_test`.

## Vector database (Qdrant)
| Collection | Content | Payload |
|---|---|---|
| `posts` | one vector per blog post (title, excerpt, category, tags, content) | `slug`; point id = post id |
| `hr_chunks` | one vector per HR passage (~1000 chars, overlapping) | `document_id`, `document`, `topic`, `page`, `chunk`, `text` |

Browse it in the built-in dashboard: **http://localhost:6333/dashboard** (collections, points, payloads, similarity
search, visualisation). DBeaver does not support Qdrant; use the dashboard or the REST API (`curl localhost:6333/collections`).

## REST API
Contract: [`contract/openapi.yaml`](contract/openapi.yaml) · interactive docs: http://localhost:8000/docs

| Method | Path | Access |
|---|---|---|
| GET | `/health` | public — Postgres + Qdrant status |
| GET | `/api/v1/posts?page&page_size&category&tag&q` | public |
| GET | `/api/v1/posts/search?q&limit` | public — semantic search |
| GET | `/api/v1/posts/{slug}` | public (`liked_by_me` with a member token) |
| POST | `/api/v1/posts/{slug}/like` | public — anonymous unlimited, members once |
| POST · PATCH · DELETE | `/api/v1/posts`, `/api/v1/posts/{slug}` | admin |
| GET · POST | `/api/v1/categories`, `/api/v1/tags` | list public · create admin |
| POST | `/api/v1/auth/register`, `/login`, `/logout` · GET `/api/v1/auth/me` | public / member |
| GET · POST | `/api/v1/users` | admin |
| GET · POST | `/api/v1/hr/documents` (multipart PDF upload, max 20 MB) | admin |
| GET · DELETE | `/api/v1/hr/documents/{document_id}` | admin |

## MCP server
`POST /mcp/` — Streamable HTTP, stateless, JSON. Tool contract: [`contract/mcp-tools.md`](contract/mcp-tools.md).
The caller is resolved from the `Authorization: Bearer` header on every call.

| Prefix | Tools | Who |
|---|---|---|
| – | `list_posts`, `top_liked_posts`, `search_posts`, `get_post`, `list_categories`, `list_tags`, `site_stats`, `user_stats` | everyone (aggregate user counts only) |
| `hr_` | `hr_search`, `hr_list_documents` | logged-in users |
| `admin_` | `admin_list_users` | admins |

## HR documents (RAG pipeline)
1. Admin uploads a text-based PDF (admin panel → **HR Documents**, or the API) with optional title and topic.
2. Background job: pypdf extracts text per page → paragraph-aware chunks of ~1000 chars with 150-char overlap →
   multilingual-e5-large embeddings → Qdrant `hr_chunks`; the row becomes `ready` (or `failed` with a reason,
   e.g. scanned PDFs without a text layer — no OCR).
3. Logged-in users ask in the chat; the agent calls `hr_search` and answers with document title and page.
4. Deleting a document removes its vectors.

## Run
Normally started with the whole stack from `../blog-app` (`docker compose up -d --build`). Standalone:

```bash
docker compose up -d --build                  # postgres + qdrant + api; migrations run on start
docker compose exec api python -m app.seed    # optional sample posts
docker compose exec api python -m app.reindex # rebuild the posts collection from Postgres
```
First start downloads both embedding models (~2.3 GB) into the `models` volume.

## Configuration (environment / `.env`, see `.env.example`)
| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://blog:blog@localhost:5432/blog` |
| `QDRANT_URL` | `http://localhost:6333` |
| `EMBEDDING_MODEL` / `HR_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` / `intfloat/multilingual-e5-large` |
| `EMBEDDING_PROVIDER` | `fastembed` (`hash` = offline test embedder) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `murat` / `murat` — **change before any public deployment** |
| `HR_MAX_UPLOAD_MB`, `HR_CHUNK_CHARS`, `HR_CHUNK_OVERLAP` | `20`, `1000`, `150` |
| `MCP_ALLOWED_HOSTS` | `localhost:*`, `127.0.0.1:*`, `api:*` (DNS-rebinding protection) |

## Ports and security
| Port | Service | Bound to |
|---|---|---|
| 8000 | API (+ `/mcp/`) | 127.0.0.1 — browsers use nginx on :3000 |
| 5432 | PostgreSQL | 127.0.0.1 |
| 6333 / 6334 | Qdrant HTTP / gRPC | 127.0.0.1 — **no auth and stores HR text: never publish** |

## Tests
```bash
docker compose exec api pytest -q        # 36 tests, real Postgres (blog_test) + Qdrant, offline embedder
postman collection run postman/blog-api.postman_collection.json   # contract checks against the running API
```

## Project layout
```
app/
  main.py          app, lifespan (Qdrant collections, admin user, HR model warm-up, MCP), routers
  config.py        settings from env
  db.py, models.py SQLAlchemy engine and models
  schemas.py       request/response models
  auth.py          auth dependencies (optional user / member / admin), admin bootstrap
  security.py      password + token hashing
  vectors.py       blog post vectors (Qdrant `posts`)
  hr.py            HR PDF extraction, chunking, multilingual-e5 store (Qdrant `hr_chunks`)
  mcp_server.py    MCP tools mounted at /mcp
  routers/         health, posts, categories/tags, auth/users, hr
  seed.py, reindex.py
alembic/           migrations
contract/          openapi.yaml, mcp-tools.md
postman/           Postman collection
tests/             pytest suite (tests/pdf.py builds PDF fixtures)
```
