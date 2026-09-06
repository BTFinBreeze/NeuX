"""Knowledge Base Service - document chunking, embedding, and ChromaDB storage."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import chromadb
import fitz
from chromadb.config import Settings

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from sentence_transformers import SentenceTransformer

try:
    from pptx import Presentation  # type: ignore[import-untyped]

    PPTX_IMPORT_ERROR: Exception | None = None
except Exception as error:  # pragma: no cover - depends on local environment.
    Presentation = None  # type: ignore[assignment]
    PPTX_IMPORT_ERROR = error


class KnowledgeBaseService:
    """Manages the local knowledge base for a workspace.

    Documents are chunked, embedded, and stored in ChromaDB.
    Each workspace has its own collection in the ChromaDB.
    """

    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 100

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        kb_dir = self.workspace_root / ".agni" / "kb"
        kb_dir.mkdir(parents=True, exist_ok=True)

        self._chroma_client = chromadb.PersistentClient(
            path=str(kb_dir / "chroma_db"),
            settings=Settings(anonymized_telemetry=False),
        )
        self._embedding_model: SentenceTransformer | None = None

    def _get_embedding_model(self) -> SentenceTransformer:
        if self._embedding_model is None:
            self._embedding_model = SentenceTransformer(
                "all-MiniLM-L6-v2",
                device="cpu",
            )
        return self._embedding_model

    @property
    def collection_name(self) -> str:
        """Derive a unique collection name from the workspace path."""
        path_hash = hashlib.md5(str(self.workspace_root).encode()).hexdigest()[:12]
        return f"kb_{path_hash}"

    def _get_collection(self):
        return self._chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def index_documents(
        self,
        documents: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Index all supported documents in the workspace.

        Supports:
        - Markdown files in notes/ directory
        - PDF files in attachments/ and references/ directories
        - PowerPoint (.pptx) files in attachments/ and references/ directories

        If documents is provided, use those instead of scanning the workspace.
        Each document dict should have 'path' and 'content' keys.
        """
        if documents is None:
            documents = self._scan_notes()
        return self._index_document_list(documents)

    def _index_document_list(self, documents: list[dict[str, str]]) -> dict[str, Any]:
        if not documents:
            return {"success": True, "data": {"indexed": 0, "chunks": 0}}

        collection = self._get_collection()

        all_ids: list[str] = []
        all_embeddings: list[list[float]] = []
        all_metadatas: list[dict[str, str]] = []
        all_documents: list[str] = []

        for doc in documents:
            doc_path = doc["path"]
            content = doc["content"]
            chunks = self._chunk_text(content)

            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_path}:{i}"
                embedding = self._get_embedding_model().encode(chunk).tolist()
                all_ids.append(chunk_id)
                all_embeddings.append(embedding)
                all_metadatas.append({
                    "source": doc_path,
                    "chunk_index": str(i),
                    "title": Path(doc_path).stem,
                })
                all_documents.append(chunk)

        # Remove old docs for these sources before adding new ones
        source_paths = list({doc["path"] for doc in documents})
        for source in source_paths:
            existing = collection.get(where={"source": source})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])

        if all_ids:
            collection.add(
                ids=all_ids,
                embeddings=all_embeddings,
                metadatas=all_metadatas,
                documents=all_documents,
            )

        return {
            "success": True,
            "data": {
                "indexed": len(documents),
                "chunks": len(all_ids),
            },
        }

    def query(
        self,
        query_text: str,
        *,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Query the knowledge base for relevant chunks."""
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []

        query_embedding = self._get_embedding_model().encode(query_text).tolist()
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
        )

        chunks: list[dict[str, Any]] = []
        if results and results["documents"] and results["documents"][0]:
            for i, doc_text in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                chunks.append({
                    "content": doc_text,
                    "source": metadata.get("source", ""),
                    "title": metadata.get("title", ""),
                    "score": (
                        1.0 - results["distances"][0][i]
                        if results.get("distances")
                        else 0.0
                    ),
                })
        return chunks

    def get_indexed_documents(self) -> list[dict[str, Any]]:
        """Return list of indexed document sources with chunk counts."""
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []

        all_data = collection.get()
        source_counts: dict[str, dict[str, Any]] = {}
        if all_data and all_data["metadatas"]:
            for meta in all_data["metadatas"]:
                source = meta.get("source", "")
                title = meta.get("title", "")
                if source not in source_counts:
                    source_counts[source] = {"source": source, "title": title, "chunks": 0}
                source_counts[source]["chunks"] += 1

        return list(source_counts.values())

    def remove_document(self, source: str) -> dict[str, Any]:
        """Remove a document from the knowledge base."""
        collection = self._get_collection()
        existing = collection.get(where={"source": source})
        if existing and existing["ids"]:
            collection.delete(ids=existing["ids"])
            return {"success": True, "data": {"removed": len(existing["ids"])}}
        return {"success": True, "data": {"removed": 0}}

    def close(self) -> None:
        """Release ChromaDB resources (close SQLite connection)."""
        try:
            self._chroma_client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self._chroma_client = None

    def clear_index(self) -> dict[str, Any]:
        """Clear the entire knowledge base index."""
        self._chroma_client.delete_collection(name=self.collection_name)
        return {"success": True, "data": {"cleared": True}}

    def rebuild_index(
        self,
        source_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Rebuild the knowledge base index from scratch.

        If source_paths is given, only those workspace-relative document paths
        (e.g. "notes/a.md", "attachments/b.pptx") are re-indexed after the
        previous collection has been cleared.
        """
        self.clear_index()
        if source_paths is None:
            return self.index_documents()

        selected = set(str(path) for path in source_paths)
        documents = [doc for doc in self._scan_notes() if doc["path"] in selected]
        return self._index_document_list(documents)

    def collect_index_candidates(self) -> list[dict[str, str]]:
        """List every file in the workspace that may carry indexable text.

        Used by the UI to let the user choose which documents to index.
        Each entry carries 'path' (workspace-relative), 'title' and 'kind'
        (one of: markdown / pdf / pptx). Text is not extracted here so that
        opening the picker stays fast.
        """
        candidates: list[dict[str, str]] = []

        def add_candidates(folder: Path, suffixes: tuple[str, ...], kind: str) -> None:
            for item in sorted(folder.rglob("*"), key=lambda p: p.name.lower()):
                if not item.is_file() or item.suffix.lower() not in suffixes:
                    continue
                candidates.append({
                    "path": str(item.relative_to(self.workspace_root)).replace("\\", "/"),
                    "title": item.name,
                    "kind": kind,
                })

        notes_dir = self.workspace_root / "notes"
        if notes_dir.exists():
            add_candidates(notes_dir, (".md",), "markdown")

        attachments_dir = self.workspace_root / "attachments"
        if attachments_dir.exists():
            add_candidates(attachments_dir, (".pdf",), "pdf")
            add_candidates(attachments_dir, (".pptx",), "pptx")

        references_dir = self.workspace_root / "references"
        if references_dir.exists():
            add_candidates(references_dir, (".pdf",), "pdf")
            add_candidates(references_dir, (".pptx",), "pptx")

        return candidates

    def _scan_notes(self) -> list[dict[str, str]]:
        """Scan workspace for all supported documents: Markdown, PDF and PPTX."""
        documents: list[dict[str, str]] = []

        notes_dir = self.workspace_root / "notes"
        if notes_dir.exists():
            for note_path in sorted(notes_dir.rglob("*.md"), key=lambda p: p.name.lower()):
                try:
                    content = note_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if content.strip():
                    documents.append({
                        "path": str(note_path.relative_to(self.workspace_root)).replace("\\", "/"),
                        "content": content,
                    })

        for folder_name in ("attachments", "references"):
            folder = self.workspace_root / folder_name
            if not folder.exists():
                continue
            for file_path in sorted(folder.rglob("*"), key=lambda p: p.name.lower()):
                if not file_path.is_file():
                    continue
                suffix = file_path.suffix.lower()
                if suffix == ".pdf":
                    content = self._extract_pdf_text(file_path)
                elif suffix == ".pptx":
                    content = self._extract_pptx_text(file_path)
                else:
                    continue
                if content.strip():
                    documents.append({
                        "path": str(file_path.relative_to(self.workspace_root)).replace("\\", "/"),
                        "content": content,
                    })

        return documents

    def _extract_pptx_text(self, pptx_path: Path) -> str:
        """Extract the visible text of every slide from a .pptx file."""
        if Presentation is None:
            return ""
        try:
            presentation = Presentation(str(pptx_path))
        except Exception:
            return ""

        slide_parts: list[str] = []
        try:
            for slide in presentation.slides:
                texts: list[str] = []
                for shape in slide.shapes:
                    text = self._shape_text(shape)
                    if text.strip():
                        texts.append(text)
                if texts:
                    slide_parts.append("\n".join(texts))
        except Exception:
            return ""
        return "\n\n".join(slide_parts)

    def _shape_text(self, shape: object) -> str:
        """Recursively gather text from a pptx shape (text frame / group / table)."""
        chunks: list[str] = []
        try:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        chunks.append(text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    row_text = "\t".join(text for text in cells if text)
                    if row_text:
                        chunks.append(row_text)
            if getattr(shape, "shapes", None) is not None:
                for child in shape.shapes:
                    child_text = self._shape_text(child)
                    if child_text.strip():
                        chunks.append(child_text)
        except Exception:
            return ""
        return "\n".join(chunks)

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extract text content from a PDF file."""
        try:
            doc = fitz.open(pdf_path)
            text_parts: list[str] = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
            doc.close()
            return "\n\n".join(text_parts)
        except Exception:
            return ""

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        if len(text) <= self.CHUNK_SIZE:
            return [text] if text.strip() else []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunk = text[start:end]

            # Try to break at a natural boundary
            if end < len(text):
                for sep in ("\n\n", "\n", "。", ".", " "):
                    last_sep = chunk.rfind(sep)
                    if last_sep > self.CHUNK_SIZE // 2:
                        end = start + last_sep + len(sep)
                        chunk = text[start:end]
                        break

            chunks.append(chunk.strip())
            start = end - self.CHUNK_OVERLAP

        return [c for c in chunks if c]