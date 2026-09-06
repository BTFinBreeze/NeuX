"""Tests for Knowledge Base and RAG functionality."""

import tempfile
from pathlib import Path

import pytest


class TestKnowledgeBaseService:
    """Test cases for KnowledgeBaseService."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            workspace = Path(tmp_dir) / "test_workspace"
            workspace.mkdir()

            (workspace / "notes").mkdir()
            (workspace / "attachments").mkdir()
            (workspace / "references").mkdir()
            (workspace / ".agni").mkdir()

            yield workspace

    @pytest.fixture
    def kb_service(self, temp_workspace):
        """Create a KnowledgeBaseService instance."""
        from app.services.kb_service import KnowledgeBaseService

        service = KnowledgeBaseService(temp_workspace)
        yield service
        service.close()

    def test_scan_markdown_files(self, temp_workspace, kb_service):
        """Test scanning markdown files from notes directory."""
        (temp_workspace / "notes" / "test1.md").write_text(
            "# Test Note 1\n\nThis is the first test note.", encoding="utf-8"
        )
        (temp_workspace / "notes" / "test2.md").write_text(
            "# Test Note 2\n\nThis is the second test note.", encoding="utf-8"
        )

        docs = kb_service._scan_notes()

        assert len(docs) == 2
        paths = {doc["path"].replace("\\", "/") for doc in docs}
        assert "notes/test1.md" in paths
        assert "notes/test2.md" in paths
        assert "Test Note 1" in docs[0]["content"] or docs[1]["content"]

    def test_scan_pdf_files(self, temp_workspace, kb_service):
        """Test scanning PDF files from attachments and references directories."""
        test_pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n"
            b"<</Type/Catalog/Pages 2 0 R>>\n"
            b"endobj\n"
            b"2 0 obj\n"
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>\n"
            b"endobj\n"
            b"3 0 obj\n"
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>\n"
            b"endobj\n"
            b"4 0 obj\n"
            b"<<>>\n"
            b"stream\n"
            b"BT /F1 12 Tf 72 700 Td (PDF Test Content) Tj ET\n"
            b"endstream\n"
            b"endobj\n"
            b"xref\n"
            b"0 5\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000190 00000 n \n"
            b"trailer\n"
            b"<</Size 5/Root 1 0 R>>\n"
            b"startxref\n"
            b"266\n"
            b"%%EOF\n"
        )

        (temp_workspace / "attachments" / "test_attachment.pdf").write_bytes(test_pdf_content)
        (temp_workspace / "references" / "test_reference.pdf").write_bytes(test_pdf_content)

        docs = kb_service._scan_notes()

        assert len(docs) == 2
        paths = {doc["path"].replace("\\", "/") for doc in docs}
        assert "attachments/test_attachment.pdf" in paths
        assert "references/test_reference.pdf" in paths

    def test_scan_mixed_files(self, temp_workspace, kb_service):
        """Test scanning mixed file types."""
        (temp_workspace / "notes" / "test.md").write_text(
            "# Test Note\n\nMarkdown content.", encoding="utf-8"
        )

        test_pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj\n"
            b"<</Type/Catalog/Pages 2 0 R>>\n"
            b"endobj\n"
            b"2 0 obj\n"
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>\n"
            b"endobj\n"
            b"3 0 obj\n"
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>\n"
            b"endobj\n"
            b"4 0 obj\n"
            b"<<>>\n"
            b"stream\n"
            b"BT /F1 12 Tf 72 700 Td (PDF Content) Tj ET\n"
            b"endstream\n"
            b"endobj\n"
            b"xref\n"
            b"0 5\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000190 00000 n \n"
            b"trailer\n"
            b"<</Size 5/Root 1 0 R>>\n"
            b"startxref\n"
            b"266\n"
            b"%%EOF\n"
        )

        (temp_workspace / "attachments" / "test.pdf").write_bytes(test_pdf_content)

        docs = kb_service._scan_notes()

        assert len(docs) == 2
        paths = {doc["path"].replace("\\", "/") for doc in docs}
        assert "notes/test.md" in paths
        assert "attachments/test.pdf" in paths

    def test_index_and_query(self, temp_workspace, kb_service):
        """Test indexing documents and querying the knowledge base."""
        (temp_workspace / "notes" / "machine_learning.md").write_text(
            """# Machine Learning Basics

Machine learning is a subset of artificial intelligence that focuses on using algorithms to learn from data.

Key concepts include:
- Supervised learning
- Unsupervised learning
- Reinforcement learning

Neural networks are a popular approach in deep learning.""",
            encoding="utf-8",
        )

        (temp_workspace / "notes" / "python.md").write_text(
            """# Python Programming

Python is a high-level programming language.

Popular libraries for machine learning:
- scikit-learn
- TensorFlow
- PyTorch

Python is widely used in data science and AI research.""",
            encoding="utf-8",
        )

        result = kb_service.index_documents()

        assert result["success"] is True
        assert result["data"]["indexed"] == 2
        assert result["data"]["chunks"] > 0

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 2
        assert any("machine_learning" in doc["title"] for doc in indexed_docs)
        assert any("python" in doc["title"] for doc in indexed_docs)

        results = kb_service.query("machine learning neural networks")

        assert len(results) > 0
        assert any("neural networks" in r["content"].lower() for r in results)

    def test_query_empty_knowledge_base(self, kb_service):
        """Test querying an empty knowledge base."""
        results = kb_service.query("test query")

        assert len(results) == 0

    def test_remove_document(self, temp_workspace, kb_service):
        """Test removing a document from the knowledge base."""
        (temp_workspace / "notes" / "to_remove.md").write_text(
            "# Document to Remove\n\nThis document will be removed.", encoding="utf-8"
        )

        kb_service.index_documents()

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 1

        result = kb_service.remove_document("notes/to_remove.md")

        assert result["success"] is True
        assert result["data"]["removed"] == 1

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 0

    def test_clear_index(self, temp_workspace, kb_service):
        """Test clearing the entire index."""
        (temp_workspace / "notes" / "doc1.md").write_text(
            "# Document 1\n\nContent.", encoding="utf-8"
        )
        (temp_workspace / "notes" / "doc2.md").write_text(
            "# Document 2\n\nContent.", encoding="utf-8"
        )

        kb_service.index_documents()

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 2

        result = kb_service.clear_index()

        assert result["success"] is True

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 0

    def test_rebuild_index(self, temp_workspace, kb_service):
        """Test rebuilding the index."""
        (temp_workspace / "notes" / "old_doc.md").write_text(
            "# Old Document\n\nOld content.", encoding="utf-8"
        )

        kb_service.index_documents()

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 1

        (temp_workspace / "notes" / "new_doc.md").write_text(
            "# New Document\n\nNew content.", encoding="utf-8"
        )
        (temp_workspace / "notes" / "old_doc.md").unlink()

        result = kb_service.rebuild_index()

        assert result["success"] is True
        assert result["data"]["indexed"] == 1

        indexed_docs = kb_service.get_indexed_documents()
        assert len(indexed_docs) == 1
        assert "new_doc" in indexed_docs[0]["title"]


class TestRAGService:
    """Test cases for RAGService."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            workspace = Path(tmp_dir) / "test_workspace"
            workspace.mkdir()

            (workspace / "notes").mkdir()
            (workspace / "attachments").mkdir()
            (workspace / ".agni").mkdir()

            (workspace / "notes" / "knowledge.md").write_text(
                """# Project Knowledge

This is a test knowledge base for the Agni project.

Key features:
- Workspace management
- Note taking
- PDF annotation
- Knowledge graph visualization
- RAG-based question answering

The RAG feature uses ChromaDB for vector storage and SentenceTransformer for embeddings.""",
                encoding="utf-8",
            )

            yield workspace

    @pytest.fixture
    def rag_service(self, temp_workspace):
        """Create an RAGService instance."""
        from app.services.rag_service import RAGService

        service = RAGService(temp_workspace)
        yield service
        service.close()

    def test_rag_index_workspace(self, rag_service):
        """Test indexing the workspace."""
        result = rag_service.index_workspace()

        assert result["success"] is True
        assert result["data"]["indexed"] == 1
        assert result["data"]["chunks"] > 0

    def test_rag_get_indexed_documents(self, rag_service):
        """Test getting indexed documents."""
        rag_service.index_workspace()

        docs = rag_service.get_indexed_documents()

        assert len(docs) == 1
        assert "knowledge" in docs[0]["title"]

    def test_rag_query_retrieval(self, rag_service):
        """Test RAG query retrieval (without LLM API call)."""
        rag_service.index_workspace()

        chunks = rag_service.kb_service.query("RAG question answering")

        assert len(chunks) > 0
        assert any("RAG" in chunk["content"] for chunk in chunks)

    def test_rag_index_single_document(self, rag_service):
        """Test indexing a single document."""
        result = rag_service.index_document(
            content="# New Document\n\nThis is a new document.",
            source_path="notes/new_doc.md",
        )

        assert result["success"] is True
        assert result["data"]["indexed"] == 1

        docs = rag_service.get_indexed_documents()
        assert len(docs) == 1
        assert "new_doc" in docs[0]["title"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])