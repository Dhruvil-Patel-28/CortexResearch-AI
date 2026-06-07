"""
Vector store module for document ingestion and retrieval.
Handles PDF loading, chunking, embedding, and FAISS index management.

Performance: Embedding model and FAISS index are cached as singletons
to avoid re-loading on every query (~15s savings per request).
"""

import os
import logging
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from utils.config import settings

logger = logging.getLogger(__name__)

# ─── Module-level singleton caches ───
_embeddings = None
_vectorstore = None
_retriever = None


def get_embeddings():
    """Get or create the cached embedding model (loaded once)."""
    global _embeddings
    if _embeddings is None:
        logger.info(f"Loading embedding model: {settings.embedding_model} (one-time)")
        _embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
    return _embeddings


def load_documents():
    """Load all PDF documents from the data directory."""
    docs = []
    data_path = settings.data_path

    if not os.path.exists(data_path):
        logger.warning(f"Data directory not found: {data_path}")
        return docs

    pdf_files = [f for f in os.listdir(data_path) if f.endswith(".pdf")]
    logger.info(f"Found {len(pdf_files)} PDF files in {data_path}")

    for file in pdf_files:
        filepath = os.path.join(data_path, file)
        try:
            loader = PyPDFLoader(filepath)
            loaded = loader.load()
            # Ensure each document has source metadata
            for doc in loaded:
                doc.metadata["source_file"] = file
            docs.extend(loaded)
            logger.info(f"Loaded {len(loaded)} pages from {file}")
        except Exception as e:
            logger.error(f"Failed to load {file}: {e}")

    return docs


def create_vector_store():
    """Create a new FAISS vector store from documents in the data directory."""
    docs = load_documents()
    embeddings = get_embeddings()

    if not docs:
        logger.warning("No documents loaded — creating empty vector store")
        vectorstore = FAISS.from_texts(
            ["No documents have been loaded yet."],
            embeddings,
            metadatas=[{"source_file": "placeholder", "page": 0}]
        )
        vectorstore.save_local(settings.index_path)
        return vectorstore

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(docs)
    logger.info(f"Split {len(docs)} documents into {len(chunks)} chunks")

    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(settings.index_path)
    logger.info(f"Vector store saved to {settings.index_path}")

    return vectorstore


def get_vector_store():
    """Load existing FAISS index or create a new one (cached after first call)."""
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    embeddings = get_embeddings()

    if os.path.exists(settings.index_path):
        logger.info(f"Loading existing FAISS index from {settings.index_path}")
        _vectorstore = FAISS.load_local(
            settings.index_path,
            embeddings,
            allow_dangerous_deserialization=True,
        )
    else:
        logger.info("No existing index found — creating new vector store")
        _vectorstore = create_vector_store()

    return _vectorstore


def search_with_relevance(query: str, k: int = None, score_threshold: float = None):
    """
    Search the vector store and filter results by relevance score.
    
    Only returns documents whose similarity score meets the threshold,
    preventing irrelevant content from being cited.
    
    Args:
        query: The search query.
        k: Number of candidates to retrieve before filtering (default from settings).
        score_threshold: Minimum similarity score (0-1) to include a result (default from settings).
    
    Returns:
        List of (Document, score) tuples that pass the relevance threshold.
    """
    k = k or settings.retriever_k
    score_threshold = score_threshold or settings.relevance_score_threshold

    vectorstore = get_vector_store()

    try:
        results = vectorstore.similarity_search_with_relevance_scores(query, k=k)
    except Exception as e:
        logger.error(f"Similarity search failed: {e}")
        return []

    # Filter by relevance threshold
    filtered = [(doc, score) for doc, score in results if score >= score_threshold]

    logger.info(
        f"Query: '{query[:80]}...' | "
        f"Retrieved {len(results)} candidates, "
        f"{len(filtered)} passed threshold ({score_threshold})"
    )

    for doc, score in results:
        source = doc.metadata.get("source_file", "unknown")
        status = "✓ PASS" if score >= score_threshold else "✗ SKIP"
        logger.debug(f"  {status}  score={score:.4f}  source={source}")

    return filtered


def get_retriever():
    """Get a basic retriever (kept for backward compatibility)."""
    global _retriever
    if _retriever is None:
        vectorstore = get_vector_store()
        _retriever = vectorstore.as_retriever(
            search_kwargs={"k": settings.retriever_k}
        )
        logger.info(f"Retriever initialized with k={settings.retriever_k}")
    return _retriever