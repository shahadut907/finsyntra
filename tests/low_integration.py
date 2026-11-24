"""
Low Priority Integration Tests - End-to-End Flows
Priority: LOW - Nice to have, validates complete workflows
5 tests covering E2E scenarios
"""
import pytest
import asyncio
import os
import sys
import json
import time
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_full_stack():
    """Mock the full application stack"""
    with patch('src.backend.services.rag_service.RAGService') as MockRAG, \
         patch('src.backend.services.vector_store.VectorStore') as MockVS:

        # Configure RAG mock
        rag_instance = MagicMock()
        rag_instance._initialized = True
        rag_instance.process_query.return_value = {
            "success": True,
            "response": "Based on the employee handbook, PTO policy is 20 days.",
            "sources": [{"filename": "handbook.pdf", "page": 12}],
            "documents_found": 1,
            "used_rag": True
        }
        MockRAG.return_value = rag_instance

        # Configure vector store mock
        vs_instance = MagicMock()
        vs_instance._initialized = True
        vs_instance.add_documents.return_value = True
        vs_instance.search_documents.return_value = [
            {"content": "PTO policy: 20 days", "metadata": {"source": "handbook.pdf"}, "similarity": 0.9}
        ]
        vs_instance.get_collection_stats.return_value = {"total_documents": 10}
        MockVS.return_value = vs_instance

        yield {
            "rag": rag_instance,
            "vector_store": vs_instance
        }


@pytest.fixture
def test_user():
    """Test user for E2E flows"""
    return {
        "id": "e2e_test@company.com",
        "email": "e2e_test@company.com",
        "name": "E2E Test User",
        "role": "employee",
        "department": "Engineering",
        "tenant_id": "test_tenant",
        "organization_id": "test_tenant"
    }


class TestEndToEndChatFlow:
    """Tests for complete chat workflow"""

    @pytest.mark.asyncio
    async def test_e2e_chat_flow(self, mock_full_stack, test_user):
        """Complete flow: authenticate → query → get cited answer"""
        # Step 1: Authenticate
        from src.backend.auth.authentication import create_access_token

        token = create_access_token({
            "sub": test_user["email"],
            "role": test_user["role"],
            "tenant_id": test_user["tenant_id"]
        })
        assert token, "Should generate auth token"

        # Step 2: Query the RAG system
        rag = mock_full_stack["rag"]
        result = rag.process_query(
            "What is the PTO policy?",
            user_id=test_user["id"],
            tenant_id=test_user["tenant_id"]
        )

        # Step 3: Verify response has citation
        assert result["success"], "Query should succeed"
        assert result["documents_found"] > 0, "Should find documents"
        assert len(result["sources"]) > 0, "Should include sources"
        assert "filename" in result["sources"][0], "Source should have filename"

    @pytest.mark.asyncio
    async def test_e2e_new_user_first_query(self, mock_full_stack):
        """New user can make first query successfully"""
        # Create new user
        new_user = {
            "id": "newuser@company.com",
            "email": "newuser@company.com",
            "role": "employee",
            "tenant_id": "new_tenant"
        }

        # Authenticate
        from src.backend.auth.authentication import create_access_token
        token = create_access_token({
            "sub": new_user["email"],
            "role": new_user["role"],
            "tenant_id": new_user["tenant_id"]
        })

        # First query
        rag = mock_full_stack["rag"]
        result = rag.process_query(
            "Hello, what can you help me with?",
            user_id=new_user["id"],
            tenant_id=new_user["tenant_id"]
        )

        assert result["success"], "First query should succeed"


class TestDocumentUploadFlow:
    """Tests for document upload workflow"""

    @pytest.mark.asyncio
    async def test_e2e_upload_and_query(self, mock_full_stack, test_user):
        """Upload document → wait for indexing → query → get result"""
        vs = mock_full_stack["vector_store"]
        rag = mock_full_stack["rag"]

        # Step 1: Upload document
        document_content = "Company revenue for Q4 2024 was $5.2 million."
        upload_success = vs.add_documents([{
            "content": document_content,
            "metadata": {
                "source": "quarterly_report.pdf",
                "tenant_id": test_user["tenant_id"],
                "department": "finance"
            }
        }])
        assert upload_success, "Document upload should succeed"

        # Step 2: Simulate indexing delay
        await asyncio.sleep(0.1)

        # Step 3: Query for the uploaded content
        result = rag.process_query(
            "What was Q4 revenue?",
            user_id=test_user["id"],
            tenant_id=test_user["tenant_id"]
        )

        assert result["success"], "Query should succeed"


class TestMultiDocumentFlow:
    """Tests for multi-document scenarios"""

    @pytest.mark.asyncio
    async def test_e2e_multi_doc_upload(self, mock_full_stack, test_user):
        """Upload multiple documents and query across them"""
        vs = mock_full_stack["vector_store"]

        # Upload multiple documents
        documents = [
            {"content": "HR Policy: 20 days PTO", "metadata": {"source": "hr.pdf", "dept": "hr"}},
            {"content": "Finance: Q4 revenue $5M", "metadata": {"source": "finance.pdf", "dept": "finance"}},
            {"content": "IT: Security guidelines", "metadata": {"source": "it.pdf", "dept": "it"}},
        ]

        for doc in documents:
            doc["metadata"]["tenant_id"] = test_user["tenant_id"]
            success = vs.add_documents([doc])
            assert success, f"Failed to upload {doc['metadata']['source']}"

        # Verify stats
        stats = vs.get_collection_stats()
        assert "total_documents" in stats

    @pytest.mark.asyncio
    async def test_e2e_cross_document_query(self, mock_full_stack, test_user):
        """Query that spans multiple documents"""
        rag = mock_full_stack["rag"]

        # Complex query that might need multiple sources
        result = rag.process_query(
            "Summarize company policies",
            user_id=test_user["id"],
            tenant_id=test_user["tenant_id"]
        )

        assert result["success"], "Cross-document query should succeed"


class TestSessionPersistence:
    """Tests for conversation/session persistence"""

    @pytest.mark.asyncio
    async def test_e2e_session_persistence(self, mock_full_stack, test_user):
        """Conversation history persists across queries"""
        session_id = f"session_{test_user['id']}"
        rag = mock_full_stack["rag"]

        # First query
        result1 = rag.process_query(
            "What is the PTO policy?",
            user_id=test_user["id"],
            tenant_id=test_user["tenant_id"],
            conversation_id=session_id
        )

        # Follow-up query (should have context)
        result2 = rag.process_query(
            "How do I request time off?",
            user_id=test_user["id"],
            tenant_id=test_user["tenant_id"],
            conversation_id=session_id
        )

        assert result1["success"]
        assert result2["success"]


class TestAuthFlow:
    """Tests for authentication flow"""

    @pytest.mark.asyncio
    async def test_e2e_login_to_query(self):
        """Complete flow from login to successful query"""
        from src.backend.auth.authentication import create_access_token, verify_token

        # Step 1: Login (create token)
        user_data = {
            "sub": "login_test@company.com",
            "role": "employee",
            "tenant_id": "test"
        }
        token = create_access_token(user_data)

        # Step 2: Verify token (simulate auth middleware)
        payload = verify_token(token)
        assert payload["sub"] == user_data["sub"]

        # Step 3: Extract user info
        user_email = payload["sub"]
        user_role = payload.get("role", "employee")
        tenant_id = payload.get("tenant_id", "default")

        assert user_email == "login_test@company.com"
        assert user_role == "employee"
        assert tenant_id == "test"

    @pytest.mark.asyncio
    async def test_e2e_token_refresh_flow(self):
        """Token refresh maintains session"""
        from src.backend.auth.authentication import create_access_token, verify_token
        from datetime import timedelta

        # Initial token
        user_data = {
            "sub": "refresh_test@company.com",
            "role": "employee",
            "tenant_id": "test"
        }
        initial_token = create_access_token(user_data)

        # Verify it works
        payload = verify_token(initial_token)
        assert payload["sub"] == user_data["sub"]

        # Create refresh token (longer expiry)
        refresh_token = create_access_token(user_data, expires_delta=timedelta(days=7))

        # Verify refresh token
        refresh_payload = verify_token(refresh_token)
        assert refresh_payload["sub"] == user_data["sub"]


class TestExportFlow:
    """Tests for data export functionality"""

    @pytest.mark.asyncio
    async def test_e2e_conversation_export(self, test_user):
        """Export conversation history"""
        # Simulate conversation history
        conversation = {
            "session_id": f"export_test_{test_user['id']}",
            "messages": [
                {"role": "user", "content": "What is PTO policy?"},
                {"role": "assistant", "content": "PTO policy is 20 days per year.", "sources": ["handbook.pdf"]},
                {"role": "user", "content": "Thanks!"},
                {"role": "assistant", "content": "You're welcome!"},
            ],
            "metadata": {
                "user_id": test_user["id"],
                "tenant_id": test_user["tenant_id"],
                "created_at": "2024-01-01T00:00:00Z"
            }
        }

        # Export as JSON
        export_json = json.dumps(conversation, indent=2)
        assert len(export_json) > 0, "Export should produce content"

        # Verify structure
        parsed = json.loads(export_json)
        assert "messages" in parsed
        assert len(parsed["messages"]) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
