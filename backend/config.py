"""
Central configuration for the AI Journalist application.
All settings are loaded from environment variables via Pydantic BaseSettings.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "AI Journalist"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-4-6"
    claude_max_tokens: int = 8192
    claude_temperature: float = 0.3

    # ── Tavily ────────────────────────────────────────────────────────────────
    tavily_api_key: str = Field(..., env="TAVILY_API_KEY")
    tavily_max_results: int = 10
    tavily_search_depth: str = "advanced"  # "basic" | "advanced"

    # ── NewsAPI ───────────────────────────────────────────────────────────────
    news_api_key: str = Field(..., env="NEWS_API_KEY")
    news_api_base_url: str = "https://newsapi.org/v2"
    news_api_page_size: int = 20

    # ── Alpha Vantage ─────────────────────────────────────────────────────────
    alpha_vantage_api_key: str = Field(..., env="ALPHA_VANTAGE_API_KEY")
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(..., env="DATABASE_URL")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # ── AWS / S3 ──────────────────────────────────────────────────────────────
    aws_access_key_id: Optional[str] = Field(None, env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(None, env="AWS_SECRET_ACCESS_KEY")
    aws_region: str = "us-east-1"
    s3_bucket_scripts: str = "ai-journalist-scripts"
    s3_bucket_assets: str = "ai-journalist-assets"

    # ── Playwright ────────────────────────────────────────────────────────────
    playwright_headless: bool = True
    playwright_timeout_ms: int = 30_000
    playwright_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    # ── Agent / Graph ─────────────────────────────────────────────────────────
    max_research_iterations: int = 3
    max_refinement_cycles: int = 2
    target_script_duration_min: int = 10
    target_script_duration_max: int = 15
    min_sources_required: int = 5
    quality_score_threshold: float = 0.75

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

    @field_validator("claude_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("Temperature must be between 0.0 and 1.0")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()


settings = get_settings()
