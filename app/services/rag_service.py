"""RAG Service - retrieval-augmented generation pipeline."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

from app.services.kb_service import KnowledgeBaseService
from app.services.llm_service import LLMService


SYSTEM_PROMPT = """你是一个知识库助手，帮助用户理解和查询工作区中的知识文档。

请根据提供的知识库片段来回答用户的问题。回答时请注意：
1. 如果知识库片段中有相关信息，请基于这些信息给出准确、详细的回答。
2. 如果知识库片段中没有相关信息，请如实告知用户，并基于你的知识给出一般性回答。
3. 在回答中引用相关片段时，可以提及来源文档的名称。
4. 保持回答简洁、有条理，使用中文回复。"""


class RAGService:
    """RAG pipeline: retrieve relevant chunks, then generate answer via LLM."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.kb_service = KnowledgeBaseService(self.workspace_root)
        self.llm_service = LLMService()

    def query(
        self,
        question: str,
        *,
        n_results: int = 5,
        stream: bool = False,
    ) -> str | Generator[str, None, None]:
        """Query the knowledge base and generate an answer.

        Returns a string (non-streaming) or a generator yielding chunks (streaming).
        """
        # Retrieve relevant chunks
        chunks = self.kb_service.query(question, n_results=n_results)

        # Build context from retrieved chunks
        if chunks:
            context_parts: list[str] = []
            for i, chunk in enumerate(chunks):
                source = chunk.get("title") or chunk.get("source", "未知文档")
                context_parts.append(f"[片段{i + 1} 来源: {source}]\n{chunk['content']}")
            context = "\n\n---\n\n".join(context_parts)
        else:
            context = "（知识库中暂无相关文档，请基于你的知识回答。）"

        # Build messages
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"知识库相关内容：\n\n{context}\n\n用户问题：{question}",
            },
        ]

        print(messages)
        return self.llm_service.chat(messages, stream=stream)

    def index_workspace(self) -> dict[str, Any]:
        """Index all workspace documents into the knowledge base."""
        return self.kb_service.index_documents()

    def get_indexed_documents(self) -> list[dict[str, Any]]:
        """Get list of indexed documents."""
        return self.kb_service.get_indexed_documents()

    def list_index_candidates(self) -> list[dict[str, str]]:
        """Get every file that may be indexed (notes, PDF and PPTX)."""
        return self.kb_service.collect_index_candidates()

    def index_document(self, content: str, source_path: str) -> dict[str, Any]:
        """Index a single document."""
        return self.kb_service.index_documents(
            documents=[{"path": source_path, "content": content}]
        )

    def remove_document(self, source: str) -> dict[str, Any]:
        """Remove a document from the knowledge base."""
        return self.kb_service.remove_document(source)

    def rebuild_index(self, source_paths: list[str] | None = None) -> dict[str, Any]:
        """Rebuild the entire knowledge base index.

        When source_paths is given, only those workspace-relative document
        paths are indexed after the previous collection has been cleared.
        """
        return self.kb_service.rebuild_index(source_paths=source_paths)

    def clear_index(self) -> dict[str, Any]:
        """Clear the entire knowledge base index."""
        return self.kb_service.clear_index()

    def close(self) -> None:
        """Release resources."""
        self.kb_service.close()