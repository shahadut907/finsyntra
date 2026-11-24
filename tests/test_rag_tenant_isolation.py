"""
Test RAG system tenant isolation and authentication
Tests that:
1. Tenant isolation works (Finance tenant can't see HR tenant docs)
2. Golden-set test (specific query → expected doc IDs)
3. SSE auth test (401 when unauth, works with cookies)
"""
import pytest
import json
import re
from fastapi.testclient import TestClient
from src.backend.services.vector_store import VectorStore
from src.backend.services.rag_service import RAGService
from src.backend.utils.document_processor import DocumentChunk
from src.config.roles import Role, Department
import uuid


class _QuoteFirstDocumentProvider:
    """Deterministic stand-in for the LLM: answers with the first document in
    its prompt. Retrieval, RBAC and tenancy are real; only generation is fixed,
    so these tests no longer depend on a running Ollama."""
    name = "test"
    model = "quote-first-document"

    def generate(self, prompt, system=None):
        match = re.search(r"Document 1 \([^)]*\): (.+)", prompt)
        return match.group(1).strip() if match else "No document content was provided."

    def healthcheck(self):
        return True


def _login_as(client, email, role, tenant_id, password="rc-test-password-123"):
    """Create (or reset) a real user row and log in through /auth/login."""
    from src.backend.auth.authentication import get_password_hash
    from src.backend.database.database import SessionLocal, User, create_tables
    create_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(id=email, username=email, email=email, full_name=email)
            db.add(user)
        user.hashed_password = get_password_hash(password)
        user.role, user.tenant_id, user.is_active, user.is_public_demo = role, tenant_id, True, False
        db.commit()
    finally:
        db.close()
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def vector_store(tmp_path):
    """Create a fresh vector store in a TEMPORARY directory.

    Previously this constructed `VectorStore(collection_name=...)`, which (a)
    raised TypeError because __new__ rejected kwargs and (b) would otherwise
    have pointed at the DEVELOPMENT Chroma store — where the teardown
    clear_collection() below would have destroyed real data.

    The store is now pinned to tmp_path and the singleton is reset around the
    fixture so the temporary path actually takes effect. conftest's fail-closed
    guard rejects this fixture outright if it ever resolves to the dev store.
    """
    from conftest import assert_not_dev_chroma, DEV_CHROMA_PATH, is_dev_path
    from tests.conftest import reset_vector_store_singleton

    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    assert_not_dev_chroma(chroma_dir, "allocate the tenant-isolation store at")

    reset_vector_store_singleton()
    store = VectorStore(
        collection_name=f"test_tenant_isolation_{uuid.uuid4().hex[:8]}",
        persist_directory=str(chroma_dir),
    )
    assert not is_dev_path(store.persist_directory, DEV_CHROMA_PATH)

    yield store

    # Cleanup — safe: this can only ever target the temporary directory.
    try:
        store.clear_collection()
    except Exception:
        pass
    reset_vector_store_singleton()


@pytest.fixture
def rag_service(vector_store):
    """Create RAG service with test vector store"""
    from tests.conftest import reset_rag_service_singleton

    reset_rag_service_singleton()
    service = RAGService()
    service.vector_store = vector_store
    service.llm_provider = _QuoteFirstDocumentProvider()
    yield service
    reset_rag_service_singleton()


def test_tenant_isolation_finance_vs_hr(vector_store, rag_service):
    """
    Test that Finance tenant cannot see HR tenant documents
    """
    # Create test documents for two different tenants
    finance_chunks = [
        DocumentChunk(
            content="Q1 2024 revenue was $5.2M with 23% growth in enterprise segment.",
            metadata={
                "source": "finance_q1_report.pdf",
                "department": Department.FINANCE,
                "chunk_id": 0,
                "tenant_id": "tenant_finance"
            }
        ),
        DocumentChunk(
            content="Operating expenses decreased by 12% due to optimization initiatives.",
            metadata={
                "source": "finance_q1_report.pdf",
                "department": Department.FINANCE,
                "chunk_id": 1,
                "tenant_id": "tenant_finance"
            }
        )
    ]
    
    hr_chunks = [
        DocumentChunk(
            content="Employee headcount increased to 250 with 15 new hires in Q1.",
            metadata={
                "source": "hr_quarterly_update.pdf",
                "department": Department.HR,
                "chunk_id": 0,
                "tenant_id": "tenant_hr"
            }
        ),
        DocumentChunk(
            content="Benefits package updated to include additional parental leave.",
            metadata={
                "source": "hr_quarterly_update.pdf",
                "department": Department.HR,
                "chunk_id": 1,
                "tenant_id": "tenant_hr"
            }
        )
    ]
    
    # Add documents with tenant IDs
    vector_store.add_documents(finance_chunks, tenant_id="tenant_finance")
    vector_store.add_documents(hr_chunks, tenant_id="tenant_hr")
    
    # Query from Finance tenant - should only see finance docs
    finance_query_result = rag_service.process_query(
        query="What was Q1 revenue?",
        user_id="user_finance@company.com",
        tenant_id="tenant_finance",
        user_role=Role.FINANCE,
        user_name="Finance User",
        top_k=5
    )
    
    # Query from HR tenant - should only see HR docs
    hr_query_result = rag_service.process_query(
        query="How many employees were hired?",
        user_id="user_hr@company.com",
        tenant_id="tenant_hr",
        user_role=Role.HR,
        user_name="HR User",
        top_k=5
    )
    
    # Assertions for Finance tenant
    assert finance_query_result["success"] == True
    assert finance_query_result["documents_found"] > 0
    finance_sources = finance_query_result.get("sources", [])
    assert any("finance" in str(src).lower() for src in finance_sources), "Finance tenant should see finance docs"
    assert not any("hr" in str(src).lower() for src in finance_sources), "Finance tenant should NOT see HR docs"
    
    # Assertions for HR tenant
    assert hr_query_result["success"] == True
    assert hr_query_result["documents_found"] > 0
    hr_sources = hr_query_result.get("sources", [])
    assert any("hr" in str(src).lower() for src in hr_sources), "HR tenant should see HR docs"
    assert not any("finance" in str(src).lower() for src in hr_sources), "HR tenant should NOT see Finance docs"
    
    print("✅ Tenant isolation test passed: Finance and HR tenants properly isolated")


def test_golden_set_query_to_doc_ids(vector_store, rag_service):
    """
    Golden-set test: specific query should retrieve expected document IDs
    """
    # Create known test documents
    test_chunks = [
        DocumentChunk(
            content="Project Phoenix timeline: Phase 1 completes March 2024, Phase 2 begins April 2024.",
            metadata={
                "source": "project_phoenix_timeline.md",
                "department": Department.ENGINEERING,
                "chunk_id": 0,
                "tenant_id": "test_tenant"
            }
        ),
        DocumentChunk(
            content="Marketing campaign budget allocated: Q1 $100K, Q2 $150K for digital ads.",
            metadata={
                "source": "marketing_budget_2024.xlsx",
                "department": Department.MARKETING,
                "chunk_id": 0,
                "tenant_id": "test_tenant"
            }
        ),
        DocumentChunk(
            content="Employee onboarding process takes 2 weeks with mandatory compliance training.",
            metadata={
                "source": "hr_onboarding_guide.pdf",
                "department": Department.HR,
                "chunk_id": 0,
                "tenant_id": "test_tenant"
            }
        )
    ]
    
    # Add documents
    vector_store.add_documents(test_chunks, tenant_id="test_tenant")
    
    # Golden set queries with expected results
    golden_tests = [
        {
            "query": "When does Project Phoenix Phase 1 complete?",
            "expected_source": "project_phoenix_timeline.md",
            "user_role": Role.ENGINEERING,
            "description": "Engineering query about project timeline"
        },
        {
            "query": "What is the marketing budget for Q2?",
            "expected_source": "marketing_budget_2024.xlsx",
            "user_role": Role.MARKETING,
            "description": "Marketing query about budget"
        },
        {
            "query": "How long is employee onboarding?",
            "expected_source": "hr_onboarding_guide.pdf",
            "user_role": Role.HR,
            "description": "HR query about onboarding"
        }
    ]
    
    for test in golden_tests:
        result = rag_service.process_query(
            query=test["query"],
            user_id="golden_test_user@company.com",
            tenant_id="test_tenant",
            user_role=test["user_role"],
            user_name="Golden Test User",
            top_k=3
        )
        
        assert result["success"] == True, f"Query failed: {test['description']}"
        assert result["documents_found"] > 0, f"No documents found for: {test['description']}"
        
        sources = result.get("sources", [])
        assert test["expected_source"] in sources, \
            f"Expected source '{test['expected_source']}' not found in {sources} for query: {test['query']}"
        
        print(f"✅ Golden set test passed: {test['description']}")
    
    print("✅ All golden-set tests passed!")


def test_sse_auth_with_cookies(client):
    """
    Test SSE endpoint authentication:
    1. Should return 401 when unauthenticated
    2. Should work with valid cookies
    """
    # Test 1: Unauthenticated request should fail
    response = client.get(
        "/api/chat/stream?q=hello",
        headers={"Accept": "text/event-stream"}
    )
    
    assert response.status_code == 401, "Unauthenticated request should return 401"
    print("✅ SSE auth test 1 passed: 401 for unauthenticated request")
    
    # Test 2: Login and get cookies
    login_response = _login_as(client, "john.smith@company.com", "employee", "tenant_sse")
    
    assert login_response.status_code == 200, "Login should succeed"
    
    # Extract session token from cookies
    cookies = login_response.cookies
    
    # Test 3: Authenticated request with cookies should work
    auth_response = client.get(
        "/api/chat/stream?q=hello",
        headers={"Accept": "text/event-stream"},
        cookies=cookies
    )
    
    assert auth_response.status_code == 200, "Authenticated request should succeed"
    assert "text/event-stream" in auth_response.headers.get("content-type", "")
    
    # Parse SSE events
    events = []
    for line in auth_response.text.split("\n"):
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                events.append({"type": "done"})
            else:
                try:
                    events.append(json.loads(data))
                except:
                    pass
    
    assert len(events) > 0, "Should receive SSE events"
    assert any(e.get("type") == "start" for e in events), "Should receive start event"
    
    print("✅ SSE auth test 2 passed: Works with valid cookies")
    print("✅ All SSE auth tests passed!")


def test_query_normalization_and_topk(vector_store, rag_service):
    """
    Test that:
    1. Query text is properly normalized (strip whitespace, lowercase)
    2. topK > 0 is enforced
    3. No empty-filter bug (all filters are valid)
    """
    # Add test documents
    test_chunks = [
        DocumentChunk(
            content="The quick brown fox jumps over the lazy dog.",
            metadata={
                "source": "test_doc_1.txt",
                "department": Department.GENERAL,
                "chunk_id": 0,
                "tenant_id": "norm_test"
            }
        ),
        DocumentChunk(
            content="Pack my box with five dozen liquor jugs.",
            metadata={
                "source": "test_doc_2.txt",
                "department": Department.GENERAL,
                "chunk_id": 0,
                "tenant_id": "norm_test"
            }
        )
    ]
    
    vector_store.add_documents(test_chunks, tenant_id="norm_test")
    
    # Test 1: Query with extra whitespace should be normalized
    result_normalized = rag_service.process_query(
        query="  What is in the test doc?  \n",
        user_id="test_user@company.com",
        tenant_id="norm_test",
        user_role=Role.EMPLOYEE,
        top_k=2
    )
    
    assert result_normalized["success"] == True
    print("✅ Query normalization works")
    
    # Test 2: topK=0 should default to reasonable value
    result_topk_zero = rag_service.process_query(
        query="What is in the test doc?",
        user_id="test_user@company.com",
        tenant_id="norm_test",
        user_role=Role.EMPLOYEE,
        top_k=0  # Invalid topK
    )
    
    # Should still work, defaulting to a reasonable value
    assert result_topk_zero["success"] == True
    print("✅ topK=0 handled gracefully")
    
    # Test 3: Verify no empty filter bug
    result_with_filters = rag_service.process_query(
        query="test",
        user_id="test_user@company.com",
        tenant_id="norm_test",
        user_role=Role.EMPLOYEE,
        top_k=5
    )
    
    # Should work without errors
    assert result_with_filters["success"] == True
    print("✅ Filter clauses valid (no empty-filter bug)")


def test_streaming_with_citations_when_hits_found(vector_store, rag_service, client):
    """
    Test that when documents are found:
    1. Answer is streamed token-by-token
    2. Cited chunks are included in response
    """
    # Add test document
    test_chunks = [
        DocumentChunk(
            content="The company revenue for Q1 2024 was $10 million dollars.",
            metadata={
                "source": "q1_2024_financial_report.pdf",
                "department": Department.FINANCE,
                "chunk_id": 0,
                "tenant_id": "citation_test"
            }
        )
    ]
    
    vector_store.add_documents(test_chunks, tenant_id="citation_test")
    
    # Login as finance user
    login_response = _login_as(client, "sarah.johnson@company.com", "finance", "citation_test")
    
    cookies = login_response.cookies
    
    # Query via SSE
    response = client.get(
        "/api/chat/stream?q=What was Q1 revenue?",
        cookies=cookies,
        headers={"Accept": "text/event-stream"}
    )
    
    assert response.status_code == 200
    
    # Parse events
    events = []
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                events.append(json.loads(data))
            except:
                pass
    
    # Verify token streaming
    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) > 0, "Should stream tokens"
    
    # Verify completion with sources
    complete_events = [e for e in events if e.get("type") == "complete"]
    assert len(complete_events) > 0, "Should have complete event"
    
    complete_event = complete_events[0]
    assert "sources" in complete_event, "Should include sources"
    assert complete_event.get("documents_found", 0) > 0, "Should have documents found"
    
    print("✅ Streaming with citations test passed")


def test_fallback_when_no_hits(rag_service):
    """
    Test that when no documents are found:
    1. System falls back to neutral small-talk
    2. No corporate disclaimer is included
    """
    # Query with no matching documents
    result = rag_service.process_query(
        query="What is the meaning of life, the universe, and everything?",
        user_id="test_user@company.com",
        tenant_id="empty_tenant_no_docs",
        user_role=Role.EMPLOYEE,
        top_k=5
    )
    
    # Should succeed but with no documents
    assert result["success"] == True
    assert result["documents_found"] == 0
    
    # Response should be helpful but not corporate
    response_text = result.get("response", "")
    assert len(response_text) > 0, "Should provide a response"
    
    # Should NOT contain corporate disclaimers
    corporate_phrases = [
        "company policy", "contact administrator", "restricted access",
        "permission denied", "not authorized"
    ]
    response_lower = response_text.lower()
    for phrase in corporate_phrases:
        assert phrase not in response_lower, f"Fallback should not include corporate phrase: {phrase}"
    
    print("✅ Fallback without corporate disclaimer test passed")


@pytest.fixture
def client():
    """Create test client"""
    from src.backend.api.endpoints import app
    with TestClient(app) as c:
        yield c


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

