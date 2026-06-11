"""
Central configuration — ALL environment variables go here.

pydantic-settings reads from your .env file automatically.
Never use os.environ directly in other files — always import `settings` from here.

This is the equivalent of @ConfigurationProperties in Spring Boot.
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str
    DB_PASSWORD: str

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str

    # ── Security ──────────────────────────────────────────────────────────
    SECRET_KEY: str

    # ── GitHub OAuth ──────────────────────────────────────────────────────
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str

    # ── Gemini ────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str

    # ── App ───────────────────────────────────────────────────────────────
    BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ENVIRONMENT: str = "development"
    SHOW_SQL_TO_CLIENT: bool = False

    @model_validator(mode="after")
    def apply_environment_defaults(self) -> "Settings":
        if "SHOW_SQL_TO_CLIENT" not in self.model_fields_set:
            object.__setattr__(self, "SHOW_SQL_TO_CLIENT", self.ENVIRONMENT == "development")
        return self

    # Tell pydantic-settings to read from .env file or ../.env
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")


# Single instance — import this everywhere:
# from app.core.config import settings
settings = Settings()  # type: ignore
