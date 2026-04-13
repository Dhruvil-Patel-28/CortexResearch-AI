# 🤖 Autonomous AI Researcher

An autonomous AI research assistant that takes a user query, decides whether to search the web or retrieve from a local knowledge base, and returns a grounded, summarized answer — all through a multi-tool LangChain agent exposed via a FastAPI backend and a Streamlit UI.

---

## 📁 Project Structure

```
Autonomous-AI-Researcher/
├── agents/
│   └── research_agent.py    # LangChain agent with tool routing logic
├── api/
│   └── main.py              # FastAPI endpoint (/research)
├── rag/
│   └── vector_store.py      # FAISS vector store: load, embed, index, retrieve
├── tools/
│   ├── web_search.py        # DuckDuckGo search tool
│   ├── rag_tool.py          # RAG retrieval tool (wraps vector store)
│   └── summarizer.py        # LLM-based summarization tool
├── ui/
│   └── app.py               # Streamlit frontend
├── utils/
│   └── llm.py               # LLM factory (returns configured LLM instance)
├── data/                    # Place your PDF documents here
├── faiss_index/             # Auto-generated FAISS index (persisted on disk)
├── .gitignore
└── requirements.txt
```

---

## ✨ How It Works

1. **User submits a query** via the Streamlit UI.
2. The UI sends a POST request to the **FastAPI backend** (`/research`).
3. The backend calls `run_agent(query)` from `research_agent.py`.
4. The **LangChain agent** decides which tool(s) to use based on the query:
   - **WebSearch** — fetches real-time results from DuckDuckGo (top 5 results).
   - **Retriever** — performs semantic similarity search over local PDF documents using FAISS + `all-MiniLM-L6-v2` embeddings.
   - **Summarizer** — passes text to the LLM to produce a clean summary.
5. The agent returns the final answer along with a list of tools it used.
6. The result is displayed back in the Streamlit UI.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Agent Framework | LangChain, LangGraph |
| LLM | Google Gemini (`langchain-google-genai`) |
| Embeddings | `sentence-transformers` — `all-MiniLM-L6-v2` |
| Vector Store | FAISS (persisted locally in `faiss_index/`) |
| Web Search | DuckDuckGo Search (`duckduckgo-search`) |
| API Backend | FastAPI + Uvicorn |
| Frontend | Streamlit |
| Document Loader | LangChain `PyPDFLoader` |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- A Google Gemini API key

### 1. Clone the Repository

```bash
git clone https://github.com/Dhruvil-Patel-28/Autonomous-AI-Researcher.git
cd Autonomous-AI-Researcher
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_google_gemini_api_key
```

### 5. Add Documents to the Knowledge Base (Optional)

Drop any PDF files you want the agent to reference into the `data/` folder. The FAISS index will be built automatically on first run. If no PDFs are present, the agent will fall back to web search.

---

## ▶️ Running the Application

### Start the FastAPI Backend

```bash
uvicorn api.main:app --reload
```

API will be available at: `http://127.0.0.1:8000`

### Launch the Streamlit UI

In a separate terminal:

```bash
streamlit run ui/app.py
```

UI will be available at: `http://localhost:8501`

---

## 🔌 API Reference

### `POST /research`

Runs the research agent on the provided query.

**Query Parameter:**

| Parameter | Type | Description |
|---|---|---|
| `query` | `string` | The research topic or question |

**Example Request:**

```bash
curl -X POST "http://127.0.0.1:8000/research?query=What+is+quantum+computing"
```

**Example Response:**

```json
{
  "response": {
    "tools_used": ["WebSearch"],
    "result": "Quantum computing is a type of computation that..."
  }
}
```

---

## 🧠 Agent Tools

### `WebSearch`
Queries DuckDuckGo and returns the top 5 result snippets. Used for real-time or external information.

### `Retriever`
Performs semantic search over locally indexed PDF documents using FAISS. Chunks are split at 500 characters with 50-character overlap and embedded using `all-MiniLM-L6-v2`.

### `Summarizer`
Takes any research text as input and returns a concise LLM-generated summary.

---

## 🗂️ Vector Store Details

- PDFs placed in `data/` are loaded using `PyPDFLoader`.
- Text is split into 500-character chunks (50 overlap) using `RecursiveCharacterTextSplitter`.
- Chunks are embedded with HuggingFace's `all-MiniLM-L6-v2`.
- The FAISS index is saved to `faiss_index/` and reloaded on subsequent runs — no re-indexing needed unless documents change.

---

## 📦 Core Dependencies

```
langchain / langchain-community / langchain-core
langchain-google-genai
langgraph
faiss-cpu
sentence-transformers
duckduckgo-search
fastapi + uvicorn
streamlit
python-dotenv
```

> Full list in [`requirements.txt`](./requirements.txt)

---

## 👤 Author

**Dhruvil Patel**  
[GitHub](https://github.com/Dhruvil-Patel-28)
