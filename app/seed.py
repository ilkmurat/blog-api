"""Load sample posts: python -m app.seed"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

SAMPLE_POSTS = [
    {
        "title": "Getting Started with React in 2026",
        "category": "Web Development",
        "tags": ["react", "javascript", "beginners"],
        "excerpt": "A practical introduction to building your first React app with Vite and TypeScript.",
        "content": "React is one of the most popular ways to build user interfaces. Components are just functions that return JSX.",
        "published_at": "2026-10-20",
    },
    {
        "title": "7 TypeScript Tips for Cleaner Code",
        "category": "Web Development",
        "tags": ["typescript", "javascript", "best-practices"],
        "excerpt": "Small TypeScript habits that make a big difference in large codebases.",
        "content": "Prefer unknown over any, use satisfies, and model states with discriminated unions.",
        "published_at": "2026-10-12",
    },
    {
        "title": "Modern Layouts with CSS Grid",
        "category": "Design",
        "tags": ["css", "layout", "responsive"],
        "excerpt": "Build responsive layouts without media-query soup using CSS Grid.",
        "content": "CSS Grid lets you describe page layouts in two dimensions with rows and columns.",
        "published_at": "2026-09-28",
    },
    {
        "title": "Deep Work Habits for Developers",
        "category": "Productivity",
        "tags": ["focus", "habits", "career"],
        "excerpt": "Protect your focus time and ship more meaningful work.",
        "content": "Block long focus sessions, turn off notifications and keep a parking lot for distracting thoughts.",
        "published_at": "2026-08-30",
    },
    {
        "title": "Deploying a Vite App to GitHub Pages",
        "category": "DevOps",
        "tags": ["github", "deployment", "vite"],
        "excerpt": "Ship your static site for free with GitHub Actions and GitHub Pages.",
        "content": "Set the Vite base path, build in a GitHub Actions workflow and deploy the dist folder to Pages.",
        "published_at": "2026-08-10",
    },
]

if __name__ == "__main__":
    settings = get_settings()
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": settings.admin_username, "password": settings.admin_password}
        )
        client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        for post in SAMPLE_POSTS:
            body = {**post, "author": "Murat İlk"}
            body["published_at"] = datetime.fromisoformat(post["published_at"]).replace(tzinfo=timezone.utc).isoformat()
            r = client.post("/api/v1/posts", json=body)
            print(r.status_code, post["title"], "" if r.status_code == 201 else r.json())
