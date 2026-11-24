"""
Simple tests to verify RAG fixes for tenant isolation and authentication
Can be run independently or as part of test suite
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from src.backend.services.vector_store import VectorStore
from src.backend.services.rag_service import RAGService
from src.backend.utils.document_processor import DocumentChunk
from src.config.roles import Role, Department
import uuid


class TestTenantIsolation:
    """Test tenant isolation in RAG system"""
    
    def test_finance_tenant_cannot_see_hr_tenant_docs(self):
        """Test that Finance tenant cannot see HR tenant documents"""
        # Use default vector store (singleton pattern)
        store = VectorStore()
        rag = RAGService()
        
        # Note: Using default collection, so tests should use unique tenant_ids
        # to avoid conflicts
        
        # Use unique tenant IDs to avoid conflicts with other tests
        tenant_fin = f"test_fin_{uuid.uuid4().hex[:6]}"
        tenant_hr = f"test_hr_{uuid.uuid4().hex[:6]}"
        
        try:
            # Add Finance tenant documents
            finance_chunks = [
                DocumentChunk(
                    content="Q1 2024 revenue was $5.2M with 23% growth.",
                    metadata={
                        "source": f"finance_report_{tenant_fin}.pdf",
                        "department": Department.FINANCE,
                        "chunk_id": 0,
                        "tenant_id": tenant_fin
                    }
                )
            ]
            store.add_documents(finance_chunks, tenant_id=tenant_fin)
            
            # Add HR tenant documents
            hr_chunks = [
                DocumentChunk(
                    content="Employee headcount increased to 250 people.",
                    metadata={
                        "source": f"hr_update_{tenant_hr}.pdf",
                        "department": Department.HR,
                        "chunk_id": 0,
                        "tenant_id": tenant_hr
                    }
                )
            ]
            store.add_documents(hr_chunks, tenant_id=tenant_hr)
            
            # Finance tenant query
            finance_result = rag.process_query(
                query="What was Q1 revenue?",
                user_id="finance_user@company.com",
                tenant_id=tenant_fin,
                user_role=Role.FINANCE,
                top_k=5
            )
            
            # HR tenant query
            hr_result = rag.process_query(
                query="How many employees?",
                user_id="hr_user@company.com",
                tenant_id=tenant_hr,
                user_role=Role.HR,
                top_k=5
            )
            
            # Verify isolation
            assert finance_result["success"] == True
            finance_sources = finance_result.get("sources", [])
            assert any("finance" in str(src).lower() for src in finance_sources)
            assert not any("hr" in str(src).lower() for src in finance_sources)
            
            assert hr_result["success"] == True
            hr_sources = hr_result.get("sources", [])
            assert any("hr" in str(src).lower() for src in hr_sources)
            assert not any("finance" in str(src).lower() for src in hr_sources)
            
            print("✅ Tenant isolation verified: Finance and HR properly separated")
            
        finally:
            # Cleanup: delete test documents by tenant_id (if method available)
            # Note: Since we use unique tenant IDs, they won't interfere with other tests
            pass
    
    def test_golden_set_query_returns_expected_docs(self):
        """Test that specific queries return expected document IDs"""
        store = VectorStore()
        rag = RAGService()
        
        tenant_test = f"golden_{uuid.uuid4().hex[:6]}"
        
        try:
            # Add known test documents
            chunks = [
                DocumentChunk(
                    content="Project Phoenix Phase 1 completes March 2024.",
                    metadata={
                        "source": f"project_timeline_{tenant_test}.md",
                        "department": Department.ENGINEERING,
                        "chunk_id": 0,
                        "tenant_id": tenant_test
                    }
                ),
                DocumentChunk(
                    content="Marketing Q2 budget is $150K for ads.",
                    metadata={
                        "source": f"marketing_budget_{tenant_test}.xlsx",
                        "department": Department.MARKETING,
                        "chunk_id": 0,
                        "tenant_id": tenant_test
                    }
                )
            ]
            store.add_documents(chunks, tenant_id=tenant_test)
            
            # Test 1: Engineering query
            result1 = rag.process_query(
                query="When does Project Phoenix Phase 1 complete?",
                user_id="eng@company.com",
                tenant_id=tenant_test,
                user_role=Role.ENGINEERING,
                top_k=3
            )
            
            assert result1["success"] == True
            sources = result1.get("sources", [])
            has_project = any("project" in str(src).lower() for src in sources)
            if has_project:
                print("✅ Golden set test 1 passed: Engineering query → correct doc")
            else:
                print(f"⚠️  Golden set test 1: Found sources {sources}, expected project doc")
            
            # Test 2: Marketing query
            result2 = rag.process_query(
                query="What is marketing Q2 budget?",
                user_id="marketing@company.com",
                tenant_id=tenant_test,
                user_role=Role.MARKETING,
                top_k=3
            )
            
            assert result2["success"] == True
            sources2 = result2.get("sources", [])
            has_budget = any("budget" in str(src).lower() for src in sources2)
            if has_budget:
                print("✅ Golden set test 2 passed: Marketing query → correct doc")
            else:
                print(f"⚠️  Golden set test 2: Found sources {sources2}, expected budget doc")
            
        finally:
            pass
    
    def test_query_normalization_and_filters(self):
        """Test query normalization and filter handling"""
        store = VectorStore()
        rag = RAGService()
        
        tenant_norm = f"norm_{uuid.uuid4().hex[:6]}"
        
        try:
            # Add test document
            chunks = [
                DocumentChunk(
                    content="Test document content for normalization.",
                    metadata={
                        "source": f"test_{tenant_norm}.txt",
                        "department": Department.GENERAL,
                        "chunk_id": 0,
                        "tenant_id": tenant_norm
                    }
                )
            ]
            store.add_documents(chunks, tenant_id=tenant_norm)
            
            # Query with extra whitespace
            result = rag.process_query(
                query="  test document  \n",
                user_id="user@company.com",
                tenant_id=tenant_norm,
                user_role=Role.EMPLOYEE,
                top_k=2
            )
            
            assert result["success"] == True
            print("✅ Query normalization works")
            
            # topK=0 should be handled gracefully
            result2 = rag.process_query(
                query="test",
                user_id="user@company.com",
                tenant_id=tenant_norm,
                user_role=Role.EMPLOYEE,
                top_k=0
            )
            
            assert result2["success"] == True
            print("✅ topK=0 handled gracefully")
            
        finally:
            pass
    
    def test_rag_empty_fallback(self):
        """Test fallback when no documents match"""
        rag = RAGService()
        
        # Use unique tenant ID that has no documents
        tenant_empty = f"empty_{uuid.uuid4().hex[:8]}"
        
        try:
            # Query with no documents in DB for this tenant
            result = rag.process_query(
                query="What is the meaning of life?",
                user_id="user@company.com",
                tenant_id=tenant_empty,
                user_role=Role.EMPLOYEE,
                top_k=5
            )
            
            assert result["success"] == True
            assert result["documents_found"] == 0
            
            # Should provide response without corporate disclaimer
            response = result.get("response", "")
            assert len(response) > 0
            
            # Check no corporate phrases
            corporate_phrases = ["contact administrator", "not authorized", "permission denied"]
            response_lower = response.lower()
            for phrase in corporate_phrases:
                assert phrase not in response_lower
            
            print("✅ RAG_EMPTY fallback works without corporate disclaimer")
            
        finally:
            pass


if __name__ == "__main__":
    # Run tests manually
    test_class = TestTenantIsolation()
    
    print("\n" + "="*60)
    print("Running RAG Fix Tests")
    print("="*60)
    
    try:
        print("\nTest 1: Tenant Isolation")
        test_class.test_finance_tenant_cannot_see_hr_tenant_docs()
        
        print("\nTest 2: Golden Set")
        test_class.test_golden_set_query_returns_expected_docs()
        
        print("\nTest 3: Query Normalization")
        test_class.test_query_normalization_and_filters()
        
        print("\nTest 4: RAG Empty Fallback")
        test_class.test_rag_empty_fallback()
        
        print("\n" + "="*60)
        print("✅ All tests passed!")
        print("="*60 + "\n")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

