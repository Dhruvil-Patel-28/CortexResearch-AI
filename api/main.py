"""
FastAPI application — Async API layer for the multi-agent research pipeline.
Provides endpoints for research queries, health checks, and session management.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.research_agent import run_research
from api.models import (
    AgentStep,
    Citation,
    HealthResponse,
    ResearchReport,
    ResearchRequest,
    ResearchResponse,
    SessionHistoryResponse,
)
from api.routes import digests as digests_routes
from api.routes import research as research_routes
from api.routes import search as search_routes
from api.routes import watch as watch_routes
from reports.markdown import render_markdown
from schemas.report import ResearchReportV2
from utils.config import settings
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
    except Exception as e:  # noqa: BLE001 — warmup is best-effort
        logger.warning("Warmup failed (will load on first request): %s", e)

    yield
    logger.info("API shutting down")


def _warmup_resources():
    """Pre-load the hybrid retriever (embedding model + index refresh)."""
    from rag.retriever import get_retriever

    get_retriever().ensure_index()


app = FastAPI(
    title="Autonomous AI Research Agent",
    description="Multi-agent research pipeline with RAG, web search, analysis, and structured report generation.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware for the Next.js frontend (origins from settings, no wildcard+credentials mix)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Topic Watch (market pulse) routes
app.include_router(watch_routes.router)

# Deep-research routes (jobs + SSE streaming + report library)
app.include_router(research_routes.router)

# Digest routes (history, preview, manual run, delta briefs)
app.include_router(digests_routes.router)

# Library search (hybrid retrieval over items + reports; optional GraphRAG/memory)
app.include_router(search_routes.router)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    from utils.config import settings as _settings
    from utils.system1 import get_router

    router = get_router()
    backend = "off"
    if _settings.s1_enabled:
        if router.has_jev and not router.breaker.skipped:
            backend = "jev"
        elif router.has_fallback:
            backend = "local"
    return HealthResponse(
        s1={
            "enabled": _settings.s1_enabled,
            "backend": backend,
            "healthy": router.breaker.healthy,
        }
    )


@app.post("/research", response_model=ResearchResponse)
async def research(request: ResearchRequest):
    """
    Execute the deep-research pipeline synchronously.

    Pipeline: Planner → Researcher → Writer → Verifier → Reviser.
    For live streaming use `POST /research/start` + `GET /research/jobs/{id}/stream`.
    The response keeps the legacy report shape for compatibility; the full
    Report-Schema-v2 payload is available from `/research/reports/{brief_id}`.
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

        # Build typed response from the schema-v2 report
        report_data = result.get("report", {})
        try:
            report_v2 = ResearchReportV2.model_validate(report_data)
            detailed = render_markdown(report_v2)
        except Exception:  # noqa: BLE001 — legacy clients must never see a 500
            report_v2 = None
            detailed = report_data.get("technical_explainer", "")

        response = ResearchResponse(
            session_id=result["session_id"],
            report=ResearchReport(
                title=report_data.get("title", "Untitled Report"),
                summary=report_data.get("executive_summary", ""),
                key_findings=report_data.get("tldr", []),
                detailed_analysis=detailed,
                recommendations=report_data.get("what_to_watch_next", []),
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
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(
            f"Research completed | session={result['session_id']} | "
            f"citations={len(response.citations)} | cost=${result.get('cost_usd', 0):.4f}"
        )
        return response

    except Exception as e:
        logger.exception("Research request failed")
        raise HTTPException(
            status_code=500,
            detail=f"Research pipeline failed: {e!s}",
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