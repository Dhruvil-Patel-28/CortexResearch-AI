"""
Centralized configuration management.
Validates all environment variables at startup with Pydantic.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # API Keys
    anthropic_api_key: str = Field(..., description="Anthropic API key for Claude models")

    # LLM Configuration (tiered: smart for synthesis, fast for scoring/extraction)
    model_name: str = Field(default="claude-sonnet-5-5", description="Frontier model for research & report synthesis")
    model_fast: str = Field(default="claude-haiku-4-5-20251001", description="Cheap fast model for scoring & extraction")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Default LLM temperature")
    max_tokens_smart: int = Field(default=8192, description="Max output tokens for the smart tier")
    max_tokens_fast: int = Field(default=2048, description="Max output tokens for the fast tier")

    # RAG Configuration
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="HuggingFace embedding model")
    rag_index_dir: str = Field(default="data/rag", description="Directory for the dense FAISS index")
    rag_rerank: bool = Field(default=True, description="Rerank fused retrieval candidates with a cross-encoder")
    rag_rerank_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2", description="Cross-encoder rerank model")

    # Optional retrieval/memory upgrades — all degrade gracefully when off.
    enable_graph_rag: bool = Field(default=False, description="Enable LightRAG knowledge-graph retrieval (requires lightrag-hku)")
    graph_working_dir: str = Field(default="data/graphrag", description="LightRAG storage directory")
    enable_supermemory: bool = Field(default=False, description="Enable the local Supermemory memory service")
    supermemory_url: str = Field(default="", description="Base URL of the local Supermemory service")
    supermemory_api_key: str = Field(default="", description="Optional API key for Supermemory")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="FastAPI host")
    api_port: int = Field(default=8000, description="FastAPI port")
    cors_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", description="Comma-separated allowed CORS origins")

    # Memory Configuration
    max_memory_turns: int = Field(default=10, description="Max conversation turns to store per session")

    # --- Topic Watch (market pulse) ---
    db_path: str = Field(default="data/cortex.db", description="SQLite database path")
    profile_path: str = Field(default="watch/profile.yaml", description="Interest profile YAML path")
    feeds_path: str = Field(default="watch/feeds.yaml", description="RSS/blog feed list YAML path")
    watch_sources: str = Field(default="hackernews,arxiv,rss,reddit,github,producthunt", description="Enabled source adapters")
    hn_min_score: int = Field(default=60, description="Minimum HN points to keep a story")
    hn_max_items: int = Field(default=35, description="Max HN stories to fetch per run")
    arxiv_max_results: int = Field(default=25, description="Max arXiv papers per run")
    arxiv_categories: str = Field(default="cs.AI,cs.LG,cs.CL,cs.SE", description="arXiv categories used when no keywords are given")
    reddit_subreddits: str = Field(default="MachineLearning,LocalLLaMA,LLMDevs,startups", description="Subreddits to watch")
    reddit_limit: int = Field(default=15, description="Posts per subreddit")
    github_min_stars: int = Field(default=40, description="Minimum stars for GitHub trending search")
    github_days: int = Field(default=7, description="Only repos created within N days")
    rss_max_per_feed: int = Field(default=8, description="Max entries per RSS feed")

    # Ranking / scoring
    prefilter_k: int = Field(default=80, description="Candidates kept after prefilter, before LLM scoring")
    llm_score_k: int = Field(default=25, description="Max items scored by the LLM per run")
    min_display_score: float = Field(default=5.0, description="Minimum LLM relevance (0-10) shown in the UI")

    # Scheduler & digests
    schedule_interval_minutes: int = Field(default=240, description="Minutes between ingest+score cycles")
    digest_hour: int = Field(default=8, description="Hour of day (local time) the daily digest is built")
    digest_min_score: float = Field(default=6.0, description="Minimum relevance (0-10) for digest inclusion")
    digest_max_items: int = Field(default=12, description="Max stories in one digest")
    digest_dir: str = Field(default="data/digests", description="Directory where digest markdown files are written")
    slack_webhook_url: str = Field(default="", description="Optional Slack webhook for digest delivery")


# Global settings instance — validates env vars on import
settings = Settings()
