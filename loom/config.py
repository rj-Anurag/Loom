from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://loom:loom@localhost:5432/loom"
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "development"
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
