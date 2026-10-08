"""
Centralized configuration management.
Validates all environment variables at startup with Pydantic.
"""

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # API Keys
    anthropic_api_key: str = Field(..., description="Anthropic API key for Claude models")

    # LLM Configuration (tiered: smart for synthesis, fast for scoring/extraction)
    model_name: str = Field(default="claude-sonnet-5-5", description="Frontier model for research & report synthesis")
    model_fast: str = Field(default="claude-haiku-4-5-20251001", description="Cheap fast model for scoring & extraction")

    # Evals (Phase 3)
    evals_judge_model: str = Field(default="", description="Model for LLM-as-judge; empty = model_fast tier")
    evals_guardrail_min_precision: float = Field(default=0.9, description="CI gate: min scanner precision")
    evals_guardrail_min_recall: float = Field(default=0.9, description="CI gate: min scanner recall")

    # Langfuse observability (Phase 3) — tracing is fully no-op without keys
    langfuse_enabled: bool = Field(default=True, description="Master switch for Langfuse tracing")
    langfuse_public_key: str = Field(default="", description="Langfuse public key; empty = tracing disabled")
    langfuse_secret_key: str = Field(default="", description="Langfuse secret key")
    langfuse_host: str = Field(default="http://localhost:3000", description="Langfuse base URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Default LLM temperature")
    max_tokens_smart: int = Field(default=16384, description="Max output tokens for the smart tier (full-report JSON must fit)")
    max_tokens_fast: int = Field(default=2048, description="Max output tokens for the fast tier")

    # RAG Configuration
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="HuggingFace embedding model")
    rag_index_dir: str = Field(default="data/rag", description="Directory for the dense FAISS index")
    rag_rerank: bool = Field(default=True, description="Rerank fused retrieval candidates with a cross-encoder")
    rag_rerank_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2", description="Cross-encoder rerank model")

    # Optional retrieval/memory upgrades — all degrade gracefully when off.
    enable_graph_rag: bool = Field(default=False, description="Enable LightRAG knowledge-graph retrieval (requires lightrag-hku)")
    graph_working_dir: str = Field(default="data/graphrag", description="LightRAG storage directory")
    graph_llm_tier: str = Field(default="fast", description="LLM tier for GraphRAG entity extraction and answers")
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

    # System 1 / System 2 routing (fast calibrated decisions + chat-tier escalation)
    s1_enabled: bool = Field(default=True, description="Route fast decisions through the System 1 router")
    jev_api_key: str = Field(default="", description="Jev (TypeSafe AI) API key; empty skips Jev and uses the local fallback")
    jev_base_url: str = Field(default="https://api.typesafe.ai/v1", description="Jev API base URL")
    jev_model: str = Field(default="jev-latest", description="Jev model identifier")
    s1_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="S1 decisions below this confidence escalate to S2")
    s1_escalation_tier: str = Field(default="fast", description="Chat tier used for S2 escalation")

    # Guardrails (injection scanning, PII scrubbing, LLM I/O policy)
    guardrails_enabled: bool = Field(default=True, description="Master switch; false bypasses all guardrails")
    guardrails_pii_enabled: bool = Field(default=True, description="Scrub PII/secrets from scraped and generated text")
    guardrails_injection_enabled: bool = Field(default=True, description="Scan scraped and generated text for prompt injection")
    guardrails_llm_output: str = Field(default="monitor", description="LLMClient output check mode: monitor | enforce | off")
    guardrails_s1_borderline: bool = Field(default=True, description="S1 assist for borderline injection scans (0.3-0.7 risk)")

    # Scheduler & digests
    schedule_interval_minutes: int = Field(default=240, description="Minutes between ingest+score cycles")
    digest_hour: int = Field(default=8, description="Hour of day (local time) the daily digest is built")
    digest_min_score: float = Field(default=6.0, description="Minimum relevance (0-10) for digest inclusion")
    digest_max_items: int = Field(default=12, description="Max stories in one digest")
    digest_dir: str = Field(default="data/digests", description="Directory where digest markdown files are written")
    slack_webhook_url: str = Field(default="", description="Optional Slack webhook for digest delivery")
    # Email delivery — off until host, user, password and a recipient are all set.
    smtp_host: str = Field(default="", description="SMTP host, e.g. smtp.gmail.com; empty disables email delivery")
    smtp_port: int = Field(default=587, description="SMTP port: 587 upgrades with STARTTLS, 465 is implicit SSL")
    smtp_user: str = Field(default="", description="SMTP username (for Gmail, your full address)")
    smtp_password: str = Field(default="", description="SMTP password (for Gmail, a 16-char App Password)")
    digest_email_to: str = Field(default="", description="Comma-separated digest recipients")


# Global settings instance — validates env vars on import
settings = Settings()
