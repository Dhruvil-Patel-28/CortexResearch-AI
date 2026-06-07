"""
FastAPI application — Async API layer for the multi-agent research pipeline.
Provides endpoints for research queries, health checks, and session management.
"""

import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.models import (
    ResearchRequest,
    ResearchResponse,
    ResearchReport,
    Citation,
    AgentStep,
    HealthResponse,
    SessionHistoryResponse,
)
from agents.research_agent import run_research
from utils.memory import session_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("=" * 60)
    logger.info("Autonomous AI Research Agent — API Starting")
    logger.info("=" * 60)

    # Pre-load expensive resources at startup (not on first request)
    import asyncio
    try:
        logger.info("Warming up: loading embedding model + FAISS index...")
        await asyncio.to_thread(_warmup_resources)
        logger.info("Warmup complete — ready to serve requests")
    except Exception as e:
        logger.warning(f"Warmup failed (will load on first request): {e}")

    yield
    logger.info("API shutting down")


def _warmup_resources():
    """Pre-load embedding model and vector store into cache."""
    from rag.vector_store import get_vector_store
    get_vector_store()


app = FastAPI(
    title="Autonomous AI Research Agent",
    description="Multi-agent research pipeline with RAG, web search, analysis, and structured report generation.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@app.post("/research", response_model=ResearchResponse)
async def research(request: ResearchRequest):
    """
    Execute a full multi-agent research pipeline.

    The pipeline follows: Supervisor → Researcher → Analyzer → Writer
    Returns a structured research report with citations and execution trace.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logger.info(f"Research request received: '{request.query[:100]}' | session={request.session_id}")

    try:
        # Run the blocking agent pipeline in a thread pool (async)
        result = await asyncio.to_thread(
            run_research,
            request.query,
            request.session_id,
        )

        # Build typed response from raw dict
        report_data = result.get("report", {})
        response = ResearchResponse(
            session_id=result["session_id"],
            report=ResearchReport(
                title=report_data.get("title", "Untitled Report"),
                summary=report_data.get("summary", ""),
                key_findings=report_data.get("key_findings", []),
                detailed_analysis=report_data.get("detailed_analysis", ""),
                recommendations=report_data.get("recommendations", []),
            ),
            citations=[
                Citation(
                    source_name=c.get("source_name", "Unknown"),
                    page_number=c.get("page_number"),
                    content_snippet=c.get("content_snippet", ""),
                    relevance_score=c.get("relevance_score"),
                )
                for c in result.get("citations", [])
            ],
            agent_steps=[
                AgentStep(
                    agent_name=s.get("agent_name", "Unknown"),
                    action=s.get("action", ""),
                    tools_used=s.get("tools_used", []),
                )
                for s in result.get("agent_steps", [])
            ],
            timestamp=datetime.now(),
        )

        logger.info(f"Research completed | session={result['session_id']} | citations={len(response.citations)}")
        return response

    except Exception as e:
        logger.error(f"Research request failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Research pipeline failed: {str(e)}",
        )


@app.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str):
    """Retrieve conversation history for a specific session."""
    history = session_manager.get_history(session_id)
    return SessionHistoryResponse(
        session_id=session_id,
        turns=history,
        total_turns=len(history),
    )