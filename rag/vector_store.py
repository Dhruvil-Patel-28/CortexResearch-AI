# from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain_community.vectorstores import FAISS

# embeddings = HuggingFaceEmbeddings()

# vector_store = FAISS.from_texts(
#     ["AI agents are autonomous systems that can plan and execute tasks."],
#     embeddings
# )

# def retrieve_docs(query):
#     docs = vector_store.similarity_search(query, k=2)
#     return "\n".join([d.page_content for d in docs])



# # rag/vector_store.py

import os
from langchain_community.document_loaders import PyPDFLoader,DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

DATA_PATH = "data"
INDEX_PATH = "faiss_index"

def load_documents():
    docs = []
    for file in os.listdir(DATA_PATH):
        if file.endswith(".pdf"):
            loader = PyPDFLoader(os.path.join(DATA_PATH, file))
            docs.extend(loader.load())
    return docs


def create_vector_store():
    docs = load_documents()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )
    chunks = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2"
    )

    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(INDEX_PATH)

    return vectorstore


def get_vector_store():
    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2"
    )

    if os.path.exists(INDEX_PATH):
        return FAISS.load_local(
                INDEX_PATH,
                embeddings,
                allow_dangerous_deserialization=True
            )
    else:
        return create_vector_store()


# GLOBAL retriever (used everywhere)
# vectorstore = get_vector_store()
# retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

retriever = None

def get_retriever():
    global retriever
    if retriever is None:
        vectorstore = get_vector_store()
        retriever = vectorstore.as_retriever()
    return retriever