from langchain_core.tools import Tool
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent

from utils.llm import get_llm
from tools.web_search import web_search
from tools.summarizer import summarize
from tools.rag_tool import rag_tool
from rag.vector_store import retriever

system_prompt = """
You are an AI research assistant.

Your job is to answer user queries accurately using available tools.

Rules:
- Use the RAG tool when the query relates to stored documents or knowledge base.
- Use the Web Search tool when the query requires real-time or external information.
- Do not make up answers.
- If unsure, use tools instead of guessing.
- Always try to provide grounded and factual responses.
"""

llm = get_llm()

tools = [
    Tool(
        name="WebSearch",
        func=web_search,
        description="Use this to get real-time or external information from the internet."
    ),
    Tool(
        name="Retriever",
        func=rag_tool,
        description="Use this to retrieve relevant information from the internal knowledge base."
    ),
    Tool(
        name="Summarizer",
        func=summarize,
        description="Summarize research text. Input should be the text you want summarized."
    )
]

agent = create_agent(llm, tools=tools, system_prompt=system_prompt)

def run_agent(query: str):
    result = agent.invoke({
        "messages": [HumanMessage(content=query)]
    })

    messages = result["messages"]

    tools_used = []

    # Extract tool usage
    for msg in messages:
        # Tool messages usually have 'name'
        if hasattr(msg, "name") and msg.name:
            tools_used.append(msg.name)

    # Remove duplicates
    tools_used = list(set(tools_used))

    final_output = messages[-1].content

    return {
        "tools_used": tools_used,
        "result": final_output
    }


