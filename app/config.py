from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    """Fly.io / Railway hand you postgres:// or postgresql://; asyncpg needs
    the +asyncpg driver suffix explicitly. Rewrite it so deploy platforms
    don't need special-case config."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    companies_house_api_key: str
    anthropic_api_key: str
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    @property
    def normalized_database_url(self) -> str:
        return normalize_db_url(self.database_url)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Cached settings instance — avoids re-reading .env on every call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings