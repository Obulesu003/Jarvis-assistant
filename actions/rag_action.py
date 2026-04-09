"""
rag_action.py - Action functions for document RAG.
"""
import logging

logger = logging.getLogger(__name__)

_indexer = None


def get_indexer():
    """Get or create the document indexer."""
    global _indexer
    if _indexer is None:
        from memory.rag_pipeline import DocumentIndexer
        try:
            from integrations.core.llm_orchestrator import get_client
            gemini = get_client()
        except Exception:
            gemini = None
        _indexer = DocumentIndexer(gemini_client=gemini)
        _indexer.initialize()
    return _indexer


def rag_action(params: dict, player=None):
    """Action to interact with document RAG."""
    cmd = params.get("command", "query")

    idx = get_indexer()

    if cmd == "index":
        folder = params.get("folder", "")
        if not folder:
            return {"status": "error", "message": "Missing folder parameter"}
        count = idx.index_folder(folder)
        return {"status": "indexed", "files": count}

    elif cmd == "query":
        question = params.get("question", "")
        if not question:
            return {"status": "error", "message": "Missing question parameter"}
        result = idx.query(question)
        return {"status": "result", **result}

    elif cmd == "stats":
        stats = idx.get_stats()
        return {"status": "stats", **stats}

    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}
