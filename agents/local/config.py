"""Local agent configuration — driven by environment variables and ``loom.config.settings``."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from loom.config import settings as loom_settings


@dataclass
class AgentConfig:
    """Configuration for the local Loom agent.

    Precedence: explicit constructor arg > env var > ``loom.config.settings``.
    """

    loom_api_url: str = field(
        default_factory=lambda: os.getenv("LOOM_API_URL", "http://localhost:8000")
    )
    loom_api_key: str = field(
        default_factory=lambda: os.getenv("LOOM_API_KEY", "")
    )
    groq_api_key: str = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY") or loom_settings.groq_api_key
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LOOM_LLM_MODEL", "llama-3.3-70b-versatile")
    )
    default_project_id: str = field(
        default_factory=lambda: os.getenv("LOOM_PROJECT_ID", "")
    )
    read_budget: int = 4096


config = AgentConfig()
