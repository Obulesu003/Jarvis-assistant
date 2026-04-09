"""
rag_pipeline.py - JARVIS indexes all personal documents.
"What does my contract say about X?" — Gemini answers from your documents.
Uses ChromaDB (local vector DB) + Gemini for synthesis.
Supported: PDF, DOCX, TXT, MD, code files, CSV, JSON
"""
import logging
import uuid
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


class DocumentIndexer:
    """
    JARVIS indexes all personal documents for RAG.
    Uses ChromaDB for local vector storage + Gemini for synthesis.
    """

    def __init__(self, memory_dir: str = "memory/docs", gemini_client=None):
        self._memory_dir = Path(memory_dir)
        self._memory_dir.mkdir(exist_ok=True)
        self._gemini = gemini_client
        self._client = None
        self._collection = None
        self._ready = False

    def initialize(self):
        """Initialize ChromaDB for document storage."""
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._memory_dir))
            self._collection = self._client.get_or_create_collection(
                "documents",
                metadata={"description": "JARVIS document RAG index"}
            )
            self._ready = True
            logger.info(f"[DocumentIndexer] ChromaDB ready at {self._memory_dir}")
        except Exception as e:
            logger.error(f"[DocumentIndexer] Init failed: {e}")

    def index_folder(self, folder_path: str, extensions: list[str] | None = None) -> int:
        """Index all documents in a folder. Returns number of files indexed."""
        if not self._ready:
            self.initialize()
        if not self._ready:
            return 0

        if extensions is None:
            extensions = [".pdf", ".docx", ".txt", ".md", ".py", ".js", ".ts", ".csv", ".json", ".yaml", ".yml"]

        folder = Path(folder_path)
        if not folder.exists():
            logger.warning(f"[DocumentIndexer] Folder not found: {folder_path}")
            return 0

        count = 0
        for file_path in folder.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                try:
                    self._index_file(file_path)
                    count += 1
                except Exception as e:
                    logger.debug(f"[DocumentIndexer] Failed to index {file_path}: {e}")

        logger.info(f"[DocumentIndexer] Indexed {count} files from {folder_path}")
        return count

    def _index_file(self, path: Path) -> bool:
        """Extract text from file and store in ChromaDB."""
        if not self._collection:
            return False

        text = self._extract_text(path)
        if not text:
            return False

        chunks = self._chunk(text, chunk_size=500, overlap=50)
        if not chunks:
            return False

        ids = [f"{path.name}_{i}" for i in range(len(chunks))]
        metadatas = [{"file": str(path), "filename": path.name, "path": str(path)} for _ in chunks]

        try:
            self._collection.add(
                documents=chunks,
                ids=ids,
                metadatas=metadatas,
            )
            return True
        except Exception as e:
            logger.error(f"[DocumentIndexer] ChromaDB add failed: {e}")
            return False

    def _extract_text(self, path: Path) -> str:
        """Extract text from any supported file type."""
        try:
            if path.suffix.lower() == ".pdf":
                import fitz
                doc = fitz.open(path)
                return "".join([page.get_text() for page in doc])
            elif path.suffix.lower() in (".docx", ".doc"):
                from docx import Document
                return "\n".join([p.text for p in Document(path).paragraphs])
            elif path.suffix.lower() in (".yaml", ".yml"):
                import yaml
                with open(path, encoding="utf-8", errors="ignore") as f:
                    data = yaml.safe_load(f)
                    return str(data) if data else ""
            else:
                return path.read_text(encoding="utf-8", errors="ignore")
        except ImportError as e:
            logger.debug(f"[DocumentIndexer] Missing dependency: {e}")
            return ""
        except Exception as e:
            logger.debug(f"[DocumentIndexer] Extract failed for {path}: {e}")
            return ""

    def _chunk(self, text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """Split text into overlapping chunks."""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        chunks = []
        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if chunk.strip():
                chunks.append(chunk.strip())
        return chunks

    def query(self, question: str) -> dict:
        """Answer a question about personal documents."""
        if not self._ready:
            self.initialize()
        if not self._collection or not self._gemini:
            return {"answer": "Document search not available.", "sources": []}

        try:
            results = self._collection.query(query_texts=[question], n_results=5)
            if not results or not results["documents"]:
                return {"answer": "No relevant documents found.", "sources": []}

            context = "\n\n---\n\n".join(results["documents"][0])
            sources = list(set(r.get("filename", "") for r in results["metadatas"][0]))

            prompt = f"""Based on these documents, answer the question. Be specific and cite the source.

Documents:
{context}

Question: {question}

Answer:"""

            answer = self._gemini.generate(prompt)
            return {
                "answer": answer,
                "sources": sources,
                "chunks_found": len(results["documents"][0]),
            }
        except Exception as e:
            logger.error(f"[DocumentIndexer] Query failed: {e}")
            return {"answer": "Document search failed.", "sources": []}

    def get_stats(self) -> dict:
        """Get index statistics."""
        if not self._collection:
            return {"documents": 0, "ready": False}
        try:
            count = self._collection.count()
            return {"documents": count, "ready": self._ready}
        except Exception:
            return {"documents": 0, "ready": self._ready}
