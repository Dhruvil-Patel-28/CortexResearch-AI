# tools/rag_tool.py

# from rag.vector_store import retriever

# def rag_tool(query: str) -> str:
#     docs = retriever.invoke(query)

#     context = ""
#     for i, doc in enumerate(docs):
#         context += f"\nSource {i+1}:\n{doc.page_content}\n"

#     return context

from rag.vector_store import get_retriever

def rag_tool(query: str):
    retriever = get_retriever()
    docs = retriever.invoke(query)
    result = "\n\n".join([doc.page_content for doc in docs])

    return {
        "tool": "rag_tool",
        "output": result
    }