# 🔬 CortexResearch AI — Autonomous Multi-Agent Research Pipeline

A **multi-agent AI research pipeline** that autonomously gathers, analyzes, and synthesizes information into structured research reports. Built with LangChain, LangGraph, and FastAPI.

## 🏗️ Architecture

The system supports two execution modes:

### Active: Static Pipeline (Optimized)
```
User Query
    ↓
┌───────────────────────┐
│   🔍 Researcher       │  ← Gathers information
│   Tools (parallel):   │     - Web Search (DuckDuckGo)
│   - WebSearch         │     - Knowledge Base (FAISS + RAG)
│   - RAG Retriever     │
└───────────┬───────────┘
            ↓
┌───────────────────────┐
│   📊 Analyzer         │  ← Synthesizes findings
│   - Key findings      │     - Pattern detection
│   - Gap analysis      │     - Contradiction flagging
│   - Confidence ratings│
└───────────┬───────────┘
            ↓
┌───────────────────────┐
│   ✍️ Writer            │  ← Generates final report
│   - Structured JSON   │     - Title, Summary, Findings
│   - Citations         │     - Analysis, Recommendations
└───────────┬───────────┘
            ↓
    📋 Structured Research Report
```

### Alternative: Dynamic Supervisor Mode (available, commented out)
```
User Query → Supervisor → Researcher → Supervisor → Analyzer → Supervisor → Writer → FINISH
```
The supervisor-based approach uses an LLM to dynamically route between agents. It's more flexible but has higher cost and latency. Can be re-enabled in `research_agent.py` for complex queries.

## ✨ Features

- **Multi-Agent Orchestration** — LangGraph `StateGraph` with static pipeline (Researcher → Analyzer → Writer) and optional dynamic supervisor routing
- **RAG Pipeline** — PDF document ingestion → chunking → FAISS vector indexing → semantic retrieval with relevance-score filtering and page-level citations
- **Web Search Integration** — Real-time DuckDuckGo search via [`ddgs`](https://github.com/deedy5/duckduckgo_search) with source attribution
- **Parallel Tool Execution** — RAG search and web search run concurrently via `ThreadPoolExecutor` for faster information gathering
- **Performance Optimized** — Singleton caching for embedding models, FAISS index, and LLM instances; server-startup warmup to eliminate cold-start latency
- **Conversation Memory** — Session-based memory for multi-turn research conversations
- **Structured Output** — JSON research reports with title, summary, key findings, analysis, and recommendations
- **Citation Tracking** — Source document names, page numbers, relevance scores, and content snippets attached to every report
- **Async API** — FastAPI with async endpoints and typed Pydantic request/response models
- **Professional UI** — Streamlit chat interface with expandable report sections and execution trace

## ⚡ Performance

Optimized pipeline with singleton caching and parallel execution:

| Stage | Description | Time |
|-------|-------------|------|
| Startup warmup | Embedding model + FAISS index load (one-time) | ~11s |
| RAG + Web Search | Run in parallel via ThreadPoolExecutor | ~4s |
| LLM calls (×3) | Researcher → Analyzer → Writer | ~3s |
| **Total per request** | **After startup warmup** | **~7s** |

Key optimizations:
- **Embedding model cached** as module-level singleton (avoids ~9s reload per request)
- **FAISS index cached** after first load (avoids ~6s reload per request)
- **LLM instances cached** by temperature parameter
- **RAG + Web search parallelized** (saves ~5s vs sequential execution)
- **Server-startup warmup** pre-loads all heavy resources before first request

## 📁 Project Structure

```
CortexResearch-AI/
├── agents/
│   ├── state.py              # Shared state definition (TypedDict)
│   ├── supervisor.py         # Planner/router agent (optional, commented out)
│   ├── researcher.py         # Information gathering agent (parallel tools)
│   ├── analyzer.py           # Analysis & synthesis agent
│   ├── writer.py             # Report generation agent
│   └── research_agent.py     # LangGraph pipeline orchestrator
├── api/
│   ├── main.py               # FastAPI app (async endpoints + warmup)
│   └── models.py             # Pydantic request/response models
├── tools/
│   ├── web_search.py         # DuckDuckGo search via ddgs
│   ├── rag_tool.py           # RAG retrieval with relevance filtering
│   └── summarizer.py         # Structured summarizer
├── rag/
│   └── vector_store.py       # FAISS vector store (singleton cached)
├── utils/
│   ├── llm.py                # LLM factory with instance caching
│   ├── config.py             # Centralized configuration (Pydantic Settings)
│   └── memory.py             # Session memory manager
├── ui/
│   └── app.py                # Streamlit chat UI
├── data/                     # PDF documents for RAG
├── faiss_index/              # Persisted FAISS index
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
└── README.md
```

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone <your-repo-url>
cd CortexResearch-AI
python -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### 3. Add Documents (Optional)

Place PDF files in the `data/` directory. The system will automatically ingest and index them on first run.

### 4. Start the API Server

```bash
uvicorn api.main:app --reload
```

### 5. Start the UI

```bash
streamlit run ui/app.py
```

Open http://localhost:8501 in your browser and start researching!

## 🔧 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/research` | Execute research pipeline |
| `GET` | `/sessions/{id}/history` | Get conversation history |

### Example Request

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest advances in fraud detection using ML?", "session_id": "my-session-1"}'
```

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | Anthropic Claude (via LangChain) |
| Agent Framework | LangGraph StateGraph |
| Vector Store | FAISS (singleton cached) |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| API | FastAPI (async) |
| UI | Streamlit |
| Web Search | DuckDuckGo (`ddgs`) |
| Configuration | Pydantic Settings |

## 👤 Author

**Dhruvil Patel**  
[GitHub](https://github.com/Dhruvil-Patel-28)