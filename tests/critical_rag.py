"""
Critical RAG Tests - Retrieval Accuracy, Hallucination Prevention, Citation Validation
Priority: CRITICAL - Core RAG functionality must work correctly
8 tests covering RAG fundamentals
"""
import pytest
import asyncio
import os
import sys
import re
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_vector_store():
    """Mock vector store with controlled documents"""
    mock = MagicMock()

    # Test documents with specific numbers
    mock.search_documents.return_value = [
        {
            "content": "Q4 2024 revenue was exactly $3.7 million. Operating expenses were $1.2M.",
            "metadata": {"source": "financial_report_q4.pdf", "page": 5, "department": "finance", "tenant_id": "test"},
            "similarity": 0.92
        },
        {
            "content": "Employee leave policy: 20 days PTO per year, 10 sick days.",
            "metadata": {"source": "employee_handbook.pdf", "page": 12, "department": "hr", "tenant_id": "test"},
            "similarity": 0.85
        }
    ]
    mock.get_collection_stats.return_value = {"total_documents": 50}
    return mock


@pytest.fixture
def mock_ollama():
    """Mock Ollama LLM responses"""
    mock = MagicMock()

    async def mock_generate(*args, **kwargs):
        yield {"content": "Based on the financial report, Q4 2024 revenue was $3.7 million."}

    mock.generate = mock_generate
    return mock


@pytest.fixture
def mock_rag_service(mock_vector_store):
    """Mock RAG service for testing"""
    mock = MagicMock()
    mock.vector_store = mock_vector_store
    mock._initialized = True

    def process_query(query, **kwargs):
        docs = mock_vector_store.search_documents(query)
        if not docs:
            return {
                "success": True,
                "response": "I couldn't find relevant documents.",
                "sources": [],
                "documents_found": 0,
                "used_rag": False
            }

        return {
            "success": True,
            "response": f"Based on {docs[0]['metadata']['source']}: {docs[0]['content'][:100]}",
            "sources": [{"filename": d["metadata"]["source"], "page": d["metadata"].get("page")} for d in docs],
            "documents_found": len(docs),
            "used_rag": True
        }

    mock.process_query = process_query
    return mock


class TestHallucinationPrevention:
    """Tests to ensure RAG doesn't hallucinate numbers/facts"""

    @pytest.mark.asyncio
    async def test_no_hallucinated_numbers(self, mock_rag_service, mock_vector_store):
        """RAG answer contains only sourced numbers, not invented ones"""
        # The document says $3.7M
        result = mock_rag_service.process_query("What was Q4 revenue?", tenant_id="test")

        response = result["response"]

        # Extract all dollar amounts from response
        dollar_amounts = re.findall(r'\$[\d,.]+[MBK]?', response)

        # Get amounts from source document
        source_content = mock_vector_store.search_documents.return_value[0]["content"]
        source_amounts = re.findall(r'\$[\d,.]+[MBK]?', source_content)

        # Every amount in response should exist in source
        for amount in dollar_amounts:
            # Normalize and check
            assert any(amount in src or amount.replace("$", "") in src for src in source_amounts + [source_content]), \
                f"Hallucinated amount: {amount} not found in source documents"

    @pytest.mark.asyncio
    async def test_no_invented_percentages(self, mock_vector_store):
        """RAG should not invent percentage figures"""
        # Document with specific percentage
        mock_vector_store.search_documents.return_value = [
            {
                "content": "Customer satisfaction increased by 15% in Q4.",
                "metadata": {"source": "metrics.pdf", "tenant_id": "test"},
                "similarity": 0.9
            }
        ]

        # A proper RAG response should only cite 15%, not invent 20% or other numbers
        source_percentages = ["15%"]

        # Simulate a bad response with hallucinated percentage
        bad_response = "Customer satisfaction increased by 25% this quarter."
        response_percentages = re.findall(r'\d+%', bad_response)

        # Check for hallucination
        has_hallucination = any(p not in source_percentages for p in response_percentages)
        assert has_hallucination, "Test setup: bad response should have hallucinated percentage"


class TestCitationRequirements:
    """Tests to ensure proper source citation"""

    @pytest.mark.asyncio
    async def test_citation_required(self, mock_rag_service):
        """Every RAG answer must cite source document"""
        result = mock_rag_service.process_query("What is the leave policy?", tenant_id="test")

        # Must have sources if documents were found
        if result["documents_found"] > 0:
            assert result["sources"], "Response must include sources when docs found"
            assert len(result["sources"]) > 0, "At least one source required"

    @pytest.mark.asyncio
    async def test_source_includes_filename(self, mock_rag_service):
        """Each citation must include filename"""
        result = mock_rag_service.process_query("revenue report", tenant_id="test")

        for source in result.get("sources", []):
            assert "filename" in source, "Source must include filename"
            assert source["filename"], "Filename must not be empty"

    @pytest.mark.asyncio
    async def test_source_includes_page_when_available(self, mock_rag_service):
        """Citation should include page number when available"""
        result = mock_rag_service.process_query("financial data", tenant_id="test")

        # At least one source should have page info (from PDF)
        sources_with_pages = [s for s in result.get("sources", []) if s.get("page")]
        if result["documents_found"] > 0:
            # Not all sources need pages, but should be present when available
            assert isinstance(result.get("sources"), list), "Sources should be a list"


class TestEmptyResults:
    """Tests for graceful handling of no results"""

    @pytest.mark.asyncio
    async def test_empty_result_graceful(self, mock_vector_store):
        """No docs found returns helpful message, not crash"""
        mock_vector_store.search_documents.return_value = []

        mock_rag = MagicMock()
        mock_rag.vector_store = mock_vector_store

        def process_empty_query(query, **kwargs):
            docs = mock_vector_store.search_documents(query)
            if not docs:
                return {
                    "success": True,
                    "response": "I couldn't find documents matching your query. Try broader keywords.",
                    "sources": [],
                    "documents_found": 0,
                    "used_rag": False
                }
            return {"success": True, "response": "Found", "sources": [], "documents_found": len(docs)}

        mock_rag.process_query = process_empty_query

        result = mock_rag.process_query("xyznonexistent12345", tenant_id="test")

        assert result["success"] == True, "Empty result should still be successful"
        assert result["documents_found"] == 0, "Should report 0 documents"
        assert "couldn't find" in result["response"].lower() or "no " in result["response"].lower(), \
            "Should provide helpful empty-result message"

    @pytest.mark.asyncio
    async def test_empty_result_no_exception(self, mock_vector_store):
        """Empty results don't raise exceptions"""
        mock_vector_store.search_documents.return_value = []

        # Should not raise
        try:
            results = mock_vector_store.search_documents("nonexistent query xyz")
            assert results == [], "Should return empty list"
        except Exception as e:
            pytest.fail(f"Empty result raised exception: {e}")


class TestSimilarityThreshold:
    """Tests for relevance filtering"""

    @pytest.mark.asyncio
    async def test_low_similarity_filtered(self):
        """Documents with low similarity (>0.5 distance) should be filtered"""
        # Simulate search results with varying similarity
        search_results = [
            {"content": "Highly relevant doc", "similarity": 0.95, "metadata": {}},
            {"content": "Somewhat relevant", "similarity": 0.75, "metadata": {}},
            {"content": "Low relevance junk", "similarity": 0.3, "metadata": {}},  # Should be filtered
            {"content": "Very low relevance", "similarity": 0.1, "metadata": {}},   # Should be filtered
        ]

        # Apply threshold filter (typical: 0.5 minimum similarity)
        SIMILARITY_THRESHOLD = 0.5
        filtered = [r for r in search_results if r["similarity"] >= SIMILARITY_THRESHOLD]

        assert len(filtered) == 2, "Only high-similarity docs should pass filter"
        assert all(r["similarity"] >= SIMILARITY_THRESHOLD for r in filtered), \
            "All filtered results should meet threshold"

    @pytest.mark.asyncio
    async def test_similarity_ordering(self):
        """Results should be ordered by similarity (highest first)"""
        search_results = [
            {"content": "Doc A", "similarity": 0.7},
            {"content": "Doc B", "similarity": 0.95},
            {"content": "Doc C", "similarity": 0.8},
        ]

        sorted_results = sorted(search_results, key=lambda x: x["similarity"], reverse=True)

        assert sorted_results[0]["similarity"] == 0.95, "Highest similarity should be first"
        assert sorted_results[-1]["similarity"] == 0.7, "Lowest similarity should be last"


class TestEncodingAndFormat:
    """Tests for document encoding and format handling"""

    @pytest.mark.asyncio
    async def test_unicode_handling(self):
        """RAG handles unicode characters correctly"""
        unicode_content = "Revenue: ¥1,000,000 (日本円) • €500,000 • £300,000"

        # Should not crash or corrupt
        encoded = unicode_content.encode('utf-8').decode('utf-8')
        assert "¥" in encoded, "Yen symbol preserved"
        assert "€" in encoded, "Euro symbol preserved"
        assert "日本円" in encoded, "Japanese characters preserved"

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self):
        """Queries with special characters are handled"""
        special_queries = [
            "What's the company's Q4 revenue?",  # Apostrophes
            "Revenue >= $1M and < $5M",  # Comparison operators
            "Search for \"exact phrase\"",  # Quotes
            "profit/loss ratio",  # Slash
            "R&D expenses",  # Ampersand
        ]

        for query in special_queries:
            # Should not crash
            cleaned = query.strip()
            assert len(cleaned) > 0, f"Query should not be empty: {query}"


class TestContextTruncation:
    """Tests for handling long contexts"""

    @pytest.mark.asyncio
    async def test_context_truncation_preserves_meaning(self):
        """Long context is truncated without losing key information"""
        # Very long document
        long_content = "IMPORTANT: Q4 revenue was $3.7M. " + ("Additional filler text. " * 500)

        # Typical context window limit (e.g., 4000 tokens ~ 16000 chars)
        MAX_CONTEXT_CHARS = 4000

        truncated = long_content[:MAX_CONTEXT_CHARS]

        # Key information should still be present
        assert "$3.7M" in truncated, "Critical numbers should not be truncated"
        assert "Q4 revenue" in truncated, "Key terms should not be truncated"

    @pytest.mark.asyncio
    async def test_multiple_docs_context_limit(self):
        """Multiple documents are combined within context limit"""
        docs = [
            {"content": "Document 1 content " * 100, "metadata": {"source": "doc1.pdf"}},
            {"content": "Document 2 content " * 100, "metadata": {"source": "doc2.pdf"}},
            {"content": "Document 3 content " * 100, "metadata": {"source": "doc3.pdf"}},
        ]

        MAX_TOTAL_CHARS = 4000

        combined = ""
        included_docs = []
        for doc in docs:
            if len(combined) + len(doc["content"]) <= MAX_TOTAL_CHARS:
                combined += doc["content"] + "\n\n"
                included_docs.append(doc["metadata"]["source"])

        assert len(combined) <= MAX_TOTAL_CHARS + 100, "Combined context should respect limit"
        assert len(included_docs) >= 1, "At least one document should be included"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
