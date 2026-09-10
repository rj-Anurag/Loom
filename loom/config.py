from pydantic_settings import BaseSettings


def _as_asyncpg_url(url: str) -> str:
    """Return a SQLAlchemy asyncpg URL from a standard Postgres URL."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://loom:loom@localhost:5432/loom"
    database_connect_timeout_seconds: float = 5.0
    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = 2.0
    redis_socket_timeout_seconds: float = 5.0
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "development"
    bootstrap_token: str = ""
    """Operator secret required by first-run setup outside development."""
    allow_legacy_uuid_tokens: bool = False
    """Temporary migration switch for pre-opaque-key agent credentials."""
    allow_agent_key_enrollment: bool = False
    """Compatibility switch; public production clients enroll through user sessions."""
    public_signups_enabled: bool = True
    email_password_auth_enabled: bool = True
    """Development/migration fallback. Disable for the public Google-only UX."""
    google_oauth_enabled: bool = False
    google_cli_client_id: str = ""
    google_cli_client_secret: str = ""
    google_extension_client_id: str = ""
    google_web_client_id: str = ""
    user_session_ttl_days: int = 30
    agent_key_ttl_days: int = 90
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 300
    embedding_provider: str = "stub"
    groq_api_key: str = ""
    summarization_interval_minutes: int = 15
    summarization_window_minutes: int = 10
    """Time window in minutes for grouping unsummarized units."""
    summarization_max_units_per_group: int = 50
    """Maximum number of units per summarization group (oldest first)."""
    summarization_min_units: int = 5
    """Minimum number of units required to trigger summarization of a group."""
    summarization_provider: str = "stub"
    """LLM provider for summarization: ``"stub"`` or ``"groq"``."""
    otel_endpoint: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def async_database_url(self) -> str:
        return _as_asyncpg_url(self.database_url)


settings = Settings()
