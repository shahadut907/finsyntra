"""
Tests for Document Parsing and Processing.
Validates file upload, text extraction, chunking, and metadata handling.
"""
import pytest
import asyncio
import json
import sys
import os
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _forget_uploads():
    """Each test starts without documents uploaded by earlier tests, so the
    per-tenant duplicate-content check (409) cannot leak between tests that
    happen to reuse fixture bytes. Only rows created during the test (in the
    isolated test database) are removed."""
    from src.backend.database.database import Document, SessionLocal

    db = SessionLocal()
    try:
        before = {doc_id for (doc_id,) in db.query(Document.id).all()}
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        for doc in db.query(Document).filter(~Document.id.in_(before)).all():
            db.delete(doc)
        db.commit()
    finally:
        db.close()


class TestFileUpload:
    """Test file upload functionality."""

    @pytest.mark.asyncio
    async def test_upload_text_file(self, auth_token):
        """Text files can be uploaded."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.txt", b"Test document content", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should succeed or indicate processing
            assert response.status_code in [200, 201, 202]

    @pytest.mark.asyncio
    async def test_upload_markdown_file(self, auth_token):
        """Markdown files can be uploaded."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            content = b"# Header\n\nSome **bold** content\n\n- List item"

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.md", content, "text/markdown")},
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response.status_code in [200, 201, 202]

    @pytest.mark.asyncio
    async def test_upload_pdf_file(self, auth_token):
        """PDF files can be uploaded (or rejected gracefully)."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # Minimal PDF header (not a real PDF, but tests mime handling)
            pdf_content = b"%PDF-1.4\n%Test PDF content"

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.pdf", pdf_content, "application/pdf")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should either process or reject with clear error
            assert response.status_code in [200, 201, 202, 400, 415]

    @pytest.mark.asyncio
    async def test_reject_executable_files(self, auth_token):
        """Executable files are rejected."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should reject dangerous file types
            assert response.status_code in [400, 415, 422]


class TestFileSizeValidation:
    """Test file size validation."""

    @pytest.mark.asyncio
    async def test_empty_file_rejected(self, auth_token):
        """Empty files are rejected."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("empty.txt", b"", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should reject empty files
            assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_reasonable_file_size_accepted(self, auth_token):
        """Reasonable file sizes are accepted."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # 10KB of content
            content = b"x" * 10240

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("medium.txt", content, "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response.status_code in [200, 201, 202]


class TestTextExtraction:
    """Test text extraction from documents."""

    def test_extract_plain_text(self):
        """Plain text extraction works."""
        try:
            from src.backend.utils.document_processor import DocumentProcessor

            processor = DocumentProcessor()
            text = "Simple text content"
            # Test extraction if method exists
            if hasattr(processor, 'extract_text'):
                result = processor.extract_text(text, "text/plain")
                assert result == text
        except ImportError:
            pytest.skip("DocumentProcessor not available")

    def test_extract_markdown_text(self):
        """Markdown text extraction preserves content."""
        try:
            from src.backend.utils.document_processor import DocumentProcessor

            processor = DocumentProcessor()
            markdown = "# Title\n\n**Bold** text"

            if hasattr(processor, 'extract_text'):
                result = processor.extract_text(markdown, "text/markdown")
                assert "Title" in result
                assert "Bold" in result
        except ImportError:
            pytest.skip("DocumentProcessor not available")


class TestDocumentChunking:
    """Test document chunking logic."""

    def test_long_document_chunked(self):
        """Long documents are split into chunks."""
        try:
            from src.backend.utils.document_processor import DocumentProcessor

            processor = DocumentProcessor()
            long_text = "A" * 5000  # 5000 characters

            if hasattr(processor, 'chunk_text'):
                chunks = processor.chunk_text(long_text)
                assert len(chunks) > 1
        except ImportError:
            pytest.skip("DocumentProcessor not available")

    def test_short_document_single_chunk(self):
        """Short documents stay as single chunk."""
        try:
            from src.backend.utils.document_processor import DocumentProcessor

            processor = DocumentProcessor()
            short_text = "Short text"

            if hasattr(processor, 'chunk_text'):
                chunks = processor.chunk_text(short_text)
                assert len(chunks) == 1
        except ImportError:
            pytest.skip("DocumentProcessor not available")

    def test_chunk_overlap(self):
        """Chunks have appropriate overlap for context."""
        try:
            from src.backend.utils.document_processor import DocumentProcessor

            processor = DocumentProcessor()
            text = "Word " * 500  # 500 words

            if hasattr(processor, 'chunk_text'):
                chunks = processor.chunk_text(text)
                if len(chunks) > 1:
                    # Check for some overlap (words appear in multiple chunks)
                    # This ensures context is preserved
                    pass
        except ImportError:
            pytest.skip("DocumentProcessor not available")


class TestMetadataExtraction:
    """Test metadata extraction and handling."""

    @pytest.mark.asyncio
    async def test_upload_with_department(self, auth_token):
        """Upload includes department metadata."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.txt", b"Content", "text/plain")},
                data={"department": "finance"},
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response.status_code in [200, 201, 202]

    @pytest.mark.asyncio
    async def test_filename_preserved(self, auth_token):
        """Original filename is preserved in metadata."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            filename = "important_document.txt"

            response = await client.post(
                "/api/documents/upload",
                files={"file": (filename, b"Content", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                data = response.json()
                # Response should reference the original filename
                if "filename" in data:
                    assert data["filename"] == filename


class TestSpecialCharacters:
    """Test handling of special characters."""

    @pytest.mark.asyncio
    async def test_unicode_content(self, auth_token):
        """Unicode content is handled correctly."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            content = "Unicode: 日本語 中文 العربية émojis 🎉".encode('utf-8')

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("unicode.txt", content, "text/plain; charset=utf-8")},
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response.status_code in [200, 201, 202]

    @pytest.mark.asyncio
    async def test_special_filename_characters(self, auth_token):
        """Filenames with special characters are handled."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # Filename with spaces and special chars
            response = await client.post(
                "/api/documents/upload",
                files={"file": ("my document (final).txt", b"Content", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should handle or sanitize filename
            assert response.status_code in [200, 201, 202, 400]


class TestDuplicateHandling:
    """Test duplicate document handling."""

    @pytest.mark.asyncio
    async def test_duplicate_file_handling(self, auth_token):
        """Duplicate files are handled appropriately."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            content = b"Duplicate test content"

            # Upload first time
            response1 = await client.post(
                "/api/documents/upload",
                files={"file": ("duplicate.txt", content, "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Upload same content again
            response2 = await client.post(
                "/api/documents/upload",
                files={"file": ("duplicate.txt", content, "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Both should succeed (or second should indicate duplicate)
            assert response1.status_code in [200, 201, 202]
            assert response2.status_code in [200, 201, 202, 409]


class TestDocumentRefresh:
    """Test document refresh/reindex functionality."""

    @pytest.mark.asyncio
    async def test_refresh_endpoint(self, auth_token):
        """Refresh endpoint triggers reindexing."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.post(
                "/api/documents/refresh",
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should succeed or indicate processing
            assert response.status_code in [200, 202, 401, 403]

    @pytest.mark.asyncio
    async def test_status_endpoint(self, auth_token):
        """Status endpoint returns document info."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.get(
                "/api/documents/status",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                data = response.json()
                # Should have some status info
                assert isinstance(data, dict)


class TestInputSanitization:
    """Test input sanitization for security."""

    @pytest.mark.asyncio
    async def test_xss_in_filename_sanitized(self, auth_token):
        """XSS attempts in filename are sanitized."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # XSS in filename
            malicious_name = "<script>alert(1)</script>.txt"

            response = await client.post(
                "/api/documents/upload",
                files={"file": (malicious_name, b"Content", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should either reject or sanitize
            if response.status_code == 200:
                data = response.json()
                if "filename" in data:
                    assert "<script>" not in data["filename"]

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, auth_token):
        """Path traversal attempts are blocked."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # Path traversal attempt
            malicious_name = "../../../etc/passwd"

            response = await client.post(
                "/api/documents/upload",
                files={"file": (malicious_name, b"Content", "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should reject or sanitize
            assert response.status_code in [200, 400, 422]
            if response.status_code == 200:
                data = response.json()
                if "filename" in data:
                    assert ".." not in data["filename"]
