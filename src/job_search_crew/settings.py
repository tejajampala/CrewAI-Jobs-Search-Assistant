from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    max_jobs: int = int(os.getenv("MAX_JOBS", "5"))
    use_website_search: bool = os.getenv("USE_WEBSITE_SEARCH", "false").lower() == "true"


def get_settings() -> Settings:
    return Settings()
