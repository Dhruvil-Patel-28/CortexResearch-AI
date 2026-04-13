# 🔬 Autonomous AI Research Agent

A **multi-agent AI research pipeline** that autonomously gathers, analyzes, and synthesizes information into structured research reports. Built with LangChain, LangGraph, and FastAPI.

## 🏗️ Architecture

```
User Query
    ↓
┌───────────────────────┐
│   🧠 Supervisor       │  ← Orchestrates the pipeline
│   (Planner Agent)     │     Decides which agent acts next
└───────────┬───────────┘
            ↓
┌───────────────────────┐
│   🔍 Researcher       │  ← Gathers information
│   Tools:              │     - Web Search (DuckDuckGo)
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

## ✨ Features

- **Multi-Agent Orchestration** — Supervisor pattern using LangGraph `StateGraph` with conditional routing
- **RAG Pipeline** — PDF document ingestion → chunking → FAISS vector indexing → semantic retrieval with page-level citations
- **Web Search Integration** — Real-time DuckDuckGo search with source attribution
- **Conversation Memory** — Session-based memory for multi-turn research conversations
- **Structured Output** — JSON research reports with title, summary, key findings, analysis, and recommendations
- **Citation Tracking** — Source document names, page numbers, and content snippets attached to every report
- **Async API** — FastAPI with async endpoints and typed Pydantic request/response models
- **Professional UI** — Streamlit chat interface with expandable report sections and execution trace

## 📁 Project Structure

```
AI_AUTONOMOUS_OPERATOR/
├── agents/
│   ├── state.py              # Shared state definition (TypedDict)
│   ├── supervisor.py         # Planner/router agent
│   ├── researcher.py         # Information gathering agent
│   ├── analyzer.py           # Analysis & synthesis agent
│   ├── writer.py             # Report generation agent
│   └── research_agent.py     # LangGraph orchestrator
├── api/
│   ├── main.py               # FastAPI app (async endpoints)
│   └── models.py             # Pydantic request/response models
├── tools/
│   ├── web_search.py         # DuckDuckGo search with sources
│   ├── rag_tool.py           # RAG retrieval with citations
│   └── summarizer.py         # Structured summarizer
├── rag/
│   └── vector_store.py       # FAISS vector store management
├── utils/
│   ├── llm.py                # LLM factory (Anthropic Claude)
│   ├── config.py             # Centralized configuration
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
cd AI_AUTONOMOUS_OPERATOR
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
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
| Vector Store | FAISS |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| API | FastAPI (async) |
| UI | Streamlit |
| Web Search | DuckDuckGo |
| Configuration | Pydantic Settings |

## 👤 Author

**Dhruvil Patel**  
[GitHub](https://github.com/Dhruvil-Patel-28)