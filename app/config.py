from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://blog:blog@localhost:5432/blog"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "posts"
    # "fastembed" for real embeddings, "hash" for a lightweight offline embedder (tests)
    embedding_provider: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Admin account created on startup if missing. Override in production!
    admin_username: str = "murat"
    admin_password: str = "murat"
    session_days: int = 30
    # Host headers accepted by the MCP endpoint (DNS-rebinding protection)
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "api:*", "testserver"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
