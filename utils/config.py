"""
Centralized configuration management.
Validates all environment variables at startup with Pydantic.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    anthropic_api_key: str = Field(..., description="Anthropic API key for Claude models")

    # LLM Configuration
    model_name: str = Field(default="claude-3-haiku-20240307", description="LLM model name")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="LLM temperature")

    # RAG Configuration
    data_path: str = Field(default="data", description="Path to document directory")
    index_path: str = Field(default="faiss_index", description="Path to FAISS index directory")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="HuggingFace embedding model")
    chunk_size: int = Field(default=1000, description="Text chunk size for splitting")
    chunk_overlap: int = Field(default=200, description="Text chunk overlap")
    retriever_k: int = Field(default=4, description="Number of documents to retrieve")
    relevance_score_threshold: float = Field(default=0.35, description="Minimum similarity score (0-1) to include a document")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="FastAPI host")
    api_port: int = Field(default=8000, description="FastAPI port")

    # Memory Configuration
    max_memory_turns: int = Field(default=10, description="Max conversation turns to store per session")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra env vars like GOOGLE_API_KEY


# Global settings instance — validates env vars on import
settings = Settings()
