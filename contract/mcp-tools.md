# Inkwell Blog MCP server

Endpoint: `POST /mcp/` (Streamable HTTP, stateless, JSON responses). MCP protocol via the `mcp` 1.x SDK.

**Auth.** Optional `Authorization: Bearer <token>` (same tokens as the REST API). The server resolves the caller
from the token on every tool call; clients cannot assert identity any other way. A missing or invalid token means
an anonymous caller. Tools prefixed with `admin_` fail with an error unless the caller is an admin.

**Data exposure.** Public tools return only published blog content and aggregate numbers. Personal data
(usernames, names, emails, per-user activity) is only returned by `admin_` tools.

All tools are read-only. Post URLs are site-relative (`/post/<slug>`).

| Tool | Arguments | Returns | Access |
|---|---|---|---|
| `list_posts` | `category?` (name or slug), `tag?` (name or slug), `limit=10` (1–50) | `{total, posts[]}`; if the category/tag doesn't exist: `note` + available names | public |
| `top_liked_posts` | `limit=5` (1–50), `category?` | posts ordered by `like_count` desc | public |
| `search_posts` | `query`, `limit=5` (1–20) | posts ranked by semantic similarity (Qdrant), with `score` | public |
| `get_post` | `slug` | full post incl. Markdown `content` (truncated to 4000 chars) | public |
| `list_categories` | – | `[{name, slug, post_count}]` | public |
| `list_tags` | – | `[{name, slug, post_count}]` | public |
| `site_stats` | – | `{posts, categories, tags, total_likes, users, latest_post}` | public |
| `user_stats` | `days=7` (1–3650) | `{total_users, new_signups, users_logged_in, period_days}` — counts only | public |
| `admin_list_users` | `limit=20` (1–200), `days?` (only users who signed up in the last N days) | users with `username, first_name, last_name, email, is_admin, created_at, likes_given, last_login` | admin |

Post objects: `{title, slug, url, category, tags[], author, published_at, like_count, excerpt}`.
