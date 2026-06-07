"""
Streamlit UI for the Autonomous AI Research Agent.
Professional interface with chat history, structured report display,
citation tracking, and agent execution trace visibility.
"""

# ```
    # User Query
    #    ↓
    # 🧠 Supervisor
    #    ↓
    # 🔍 Researcher
    #    ↓
    # 🧠 Supervisor
    #    ↓
    # 📊 Analyzer
    #    ↓
    # 🧠 Supervisor
    #    ↓
    # ✍️ Writer
    #    ↓
    # 📋 Report
    # ```

import streamlit as st
import requests
import uuid
import json

# --- Page Configuration ---
st.set_page_config(
    page_title="AI Research Agent",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Main header */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
    }
    .main-header h1 {
        font-size: 2rem;
        margin: 0;
        font-weight: 700;
    }
    .main-header p {
        opacity: 0.9;
        margin-top: 0.5rem;
        font-size: 1rem;
    }
    
    /* Report card */
    .report-card {
        background: #f8f9fa;
        border-left: 4px solid #667eea;
        padding: 1.5rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0;
    }
    
    /* Citation card */
    .citation-card {
        background: #fff3cd;
        border-left: 3px solid #ffc107;
        padding: 0.8rem 1rem;
        border-radius: 0 6px 6px 0;
        margin: 0.5rem 0;
        font-size: 0.9rem;
    }
    
    /* Agent step */
    .agent-step {
        background: #e8f5e9;
        border-left: 3px solid #4caf50;
        padding: 0.6rem 1rem;
        border-radius: 0 6px 6px 0;
        margin: 0.3rem 0;
        font-size: 0.85rem;
    }
    
    /* Metric cards */
    .metric-row {
        display: flex;
        gap: 1rem;
        margin: 1rem 0;
    }
    .metric-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem;
        flex: 1;
        text-align: center;
    }
    .metric-card .value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #667eea;
    }
    .metric-card .label {
        font-size: 0.8rem;
        color: #888;
        text-transform: uppercase;
    }
</style>
""", unsafe_allow_html=True)

# --- API Configuration ---
API_BASE_URL = "http://127.0.0.1:8000"

# --- Session State Initialization ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False

# --- Sidebar ---
with st.sidebar:
    st.markdown("### ⚙️ Session Management")
    st.text_input(
        "Session ID",
        value=st.session_state.session_id,
        disabled=True,
        key="session_display",
    )
    
    if st.button("🔄 New Session", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.chat_history = []
        st.rerun()
    
    st.divider()
    
    st.markdown("### 📊 Session Stats")
    st.metric("Total Queries", len(st.session_state.chat_history))
    
    total_citations = sum(
        len(item.get("citations", []))
        for item in st.session_state.chat_history
        if item.get("role") == "assistant"
    )
    st.metric("Sources Cited", total_citations)
    
    st.divider()
    
    st.markdown("### 🏗️ Architecture")
    st.markdown("""
    
    ```
    User Query
     
    🔍 Researcher
       ↓
    📊 Analyzer
       ↓
    ✍️ Writer
       ↓
    📋 Report
    ```
    """)

# --- Main Content ---
st.markdown("""
<div class="main-header">
    <h1>🔬 Autonomous AI Research Agent</h1>
    <p>Multi-agent pipeline: Supervisor → Researcher → Analyzer → Writer</p>
</div>
""", unsafe_allow_html=True)

# --- Chat History Display ---
for item in st.session_state.chat_history:
    if item["role"] == "user":
        with st.chat_message("user"):
            st.markdown(item["content"])
    else:
        with st.chat_message("assistant", avatar="🔬"):
            data = item.get("data", {})
            report = data.get("report", {})
            
            # Report Title & Summary
            st.markdown(f"### 📋 {report.get('title', 'Research Report')}")
            st.markdown(report.get("summary", ""))
            
            # Key Findings
            findings = report.get("key_findings", [])
            if findings:
                st.markdown("#### 🎯 Key Findings")
                for finding in findings:
                    st.markdown(f"- {finding}")
            
            # Detailed Analysis (expandable)
            detailed = report.get("detailed_analysis", "")
            if detailed:
                with st.expander("📖 Detailed Analysis", expanded=False):
                    st.markdown(detailed)
            
            # Recommendations
            recs = report.get("recommendations", [])
            if recs:
                with st.expander("💡 Recommendations", expanded=False):
                    for rec in recs:
                        st.markdown(f"- {rec}")
            
            # Citations
            citations = data.get("citations", [])
            if citations:
                with st.expander(f"📚 Sources & Citations ({len(citations)})", expanded=False):
                    for i, cit in enumerate(citations, 1):
                        page_info = f" | Page {cit['page_number']}" if cit.get("page_number") else ""
                        st.markdown(
                            f'<div class="citation-card">'
                            f'<strong>[{i}]</strong> {cit["source_name"]}{page_info}<br>'
                            f'<em>{cit.get("content_snippet", "")[:150]}...</em>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
            
            # Agent Execution Trace
            steps = data.get("agent_steps", [])
            if steps:
                with st.expander(f"🔧 Agent Execution Trace ({len(steps)} steps)", expanded=False):
                    for step in steps:
                        tools = ", ".join(step.get("tools_used", [])) if step.get("tools_used") else "None"
                        st.markdown(
                            f'<div style="background-color:#1e1e1e; color:white; padding:12px; border-radius:10px; margin-bottom:10px; border:1px solid #333;">'
                            f'<strong>{step["agent_name"]}</strong>: {step["action"]}'
                            f'<br>Tools: {tools}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        

# --- Query Input ---
query = st.chat_input("Enter your research question...")

if query:
    # Add user message to history
    st.session_state.chat_history.append({"role": "user", "content": query})
    
    with st.chat_message("user"):
        st.markdown(query)
    
    # Call API with animated progress
    with st.chat_message("assistant", avatar="🔬"):
        try:
            import threading
            import time

            # Pipeline stages shown to the user while the request is in progress
            stages = [
                ("🔍 Researcher", "Searching knowledge base & web in parallel..."),
                ("📊 Analyzer", "Synthesizing findings & detecting patterns..."),
                ("✍️  Writer", "Composing the structured research report..."),
            ]

            # Run the API call in a background thread
            result_container = {"response": None, "error": None}
            current_session_id = st.session_state.session_id

            def _call_api():
                try:
                    result_container["response"] = requests.post(
                        f"{API_BASE_URL}/research",
                        json={
                            "query": query,
                            "session_id": current_session_id,
                        },
                        timeout=120,
                    )
                except Exception as e:
                    result_container["error"] = e

            api_thread = threading.Thread(target=_call_api)
            api_thread.start()

            # Animate through pipeline stages while waiting
            progress_bar = st.progress(0, text="Starting research pipeline...")
            status_placeholder = st.empty()

            stage_idx = 0
            elapsed = 0.0
            step_interval = 0.3  # update every 300ms

            while api_thread.is_alive():
                # Cycle through stages based on elapsed time
                if elapsed < 3.0:
                    stage_idx = 0
                elif elapsed < 5.5:
                    stage_idx = 1
                else:
                    stage_idx = 2

                icon, desc = stages[stage_idx]
                progress_pct = min(0.95, (stage_idx + 1) / len(stages) * 0.9)
                progress_bar.progress(progress_pct, text=f"**{icon}** — {desc}")

                time.sleep(step_interval)
                elapsed += step_interval

            # Done — show completion
            progress_bar.progress(1.0, text="✅ Research complete!")
            time.sleep(0.4)
            progress_bar.empty()
            status_placeholder.empty()

            # Check for errors from the thread
            if result_container["error"] is not None:
                raise result_container["error"]

            response = result_container["response"]

            if response.status_code == 200:
                data = response.json()
                report = data.get("report", {})
                
                # Display report
                st.markdown(f"### 📋 {report.get('title', 'Research Report')}")
                st.markdown(report.get("summary", ""))
                
                findings = report.get("key_findings", [])
                if findings:
                    st.markdown("#### 🎯 Key Findings")
                    for finding in findings:
                        st.markdown(f"- {finding}")
                
                detailed = report.get("detailed_analysis", "")
                if detailed:
                    with st.expander("📖 Detailed Analysis", expanded=False):
                        st.markdown(detailed)
                
                recs = report.get("recommendations", [])
                if recs:
                    with st.expander("💡 Recommendations", expanded=False):
                        for rec in recs:
                            st.markdown(f"- {rec}")
                
                citations = data.get("citations", [])
                if citations:
                    with st.expander(f"📚 Sources & Citations ({len(citations)})", expanded=False):
                        for i, cit in enumerate(citations, 1):
                            page_info = f" | Page {cit['page_number']}" if cit.get("page_number") else ""
                            st.markdown(
                                f'<div class="citation-card">'
                                f'<strong>[{i}]</strong> {cit["source_name"]}{page_info}<br>'
                                f'<em>{cit.get("content_snippet", "")[:150]}...</em>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                
                steps = data.get("agent_steps", [])
                if steps:
                    with st.expander(f"🔧 Agent Execution Trace ({len(steps)} steps)", expanded=False):
                        for step in steps:
                            tools = ", ".join(step.get("tools_used", [])) if step.get("tools_used") else "None"
                            st.markdown(
                                f'<div class="agent-step">'
                                f'<strong>{step["agent_name"]}</strong>: {step["action"]}'
                                f'<br>Tools: {tools}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                
                # Store in session
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": report.get("summary", ""),
                    "data": data,
                    "citations": citations,
                })
                
                # Metrics bar
                cols = st.columns(3)
                with cols[0]:
                    st.metric("📚 Sources", len(citations))
                with cols[1]:
                    st.metric("🔧 Agent Steps", len(steps))
                with cols[2]:
                    st.metric("🎯 Key Findings", len(findings))

            else:
                st.error(f"❌ API returned error {response.status_code}: {response.text}")
                
        except requests.exceptions.ConnectionError:
            st.error(
                "❌ Cannot connect to the API server. "
                "Make sure the FastAPI server is running:\n\n"
                "```bash\nuvicorn api.main:app --reload\n```"
            )
        except requests.exceptions.Timeout:
            st.warning("⏳ The research is taking longer than expected. Please try again.")
        except Exception as e:
            st.error(f"❌ An unexpected error occurred: {str(e)}")