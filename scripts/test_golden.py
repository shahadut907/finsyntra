#!/usr/bin/env python3
"""
Golden Document Test - Ensures retrieval of planted test token
"""
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.backend.services.rag_service import RAGService
from src.backend.utils.document_processor import DocumentChunk
from src.config.roles import Role, Department
from datetime import datetime

def create_golden_document():
    """Create a golden test document with unique token"""
    print("🏆 Creating golden test document")
    
    golden_content = """
    FinSyntra Company Test Document
    
    This is a test document containing the unique identifier ZEBRA-ALPHA-BUDGET-TOKEN 
    for verification of the RAG system functionality.
    
    Company Budget Overview:
    - Total allocated budget: $2.5M
    - ZEBRA-ALPHA-BUDGET-TOKEN verification successful
    - Emergency fund: $500K
    
    This document should always be retrievable when searching for the token.
    """
    
    # Create document chunk
    chunk = DocumentChunk(
        content=golden_content.strip(),
        metadata={
            "source": "golden_test_document.md",
            "department": "general",
            "doc_type": "test",
            "content_type": "text",
            "chunk_id": 0,
            "indexed_at": datetime.now().isoformat(),
            "file_modified": datetime.now().isoformat()
        }
    )
    
    return [chunk]

def test_golden_document_ingestion():
    """Test that golden document can be ingested"""
    print("📥 Testing golden document ingestion")
    
    try:
        rag = RAGService()
        golden_chunks = create_golden_document()
        
        success = rag.vector_store.add_documents(golden_chunks)
        
        if success:
            print("✅ Golden document ingested successfully")
            return True
        else:
            print("❌ Failed to ingest golden document")
            return False
            
    except Exception as e:
        print(f"❌ Error ingesting golden document: {e}")
        return False

def test_golden_document_retrieval():
    """Test that golden token can be retrieved"""
    print("🔍 Testing golden token retrieval")
    
    try:
        rag = RAGService()
        
        # Test 1: Direct search for the token
        results = rag.vector_store.search_documents(
            query="ZEBRA-ALPHA-BUDGET-TOKEN",
            user_role=Role.EMPLOYEE,
            limit=5
        )
        
        if results:
            for result in results:
                if "ZEBRA-ALPHA-BUDGET-TOKEN" in result.get("content", ""):
                    print("✅ Golden token found via semantic search")
                    return True
        
        # Test 2: Keyword search fallback
        keyword_results = rag.vector_store.keyword_search(
            query="ZEBRA-ALPHA-BUDGET-TOKEN",
            limit=5
        )
        
        if keyword_results:
            for result in keyword_results:
                if "ZEBRA-ALPHA-BUDGET-TOKEN" in result.get("content", ""):
                    print("✅ Golden token found via keyword search")
                    return True
        
        print("❌ Golden token NOT found in any search")
        return False
        
    except Exception as e:
        print(f"❌ Error testing golden retrieval: {e}")
        return False

def test_end_to_end_golden():
    """Test complete end-to-end golden document flow"""
    print("🔄 Testing end-to-end golden document flow")
    
    try:
        rag = RAGService()
        
        # Full RAG query for the golden token
        response = rag.text_generation(
            query="What is the ZEBRA-ALPHA-BUDGET-TOKEN?",
            user_role=Role.EMPLOYEE,
            conversation_id="golden_test_session"
        )
        
        response_text = response.get("text", "")
        metadata = response.get("metadata", {})
        
        if "ZEBRA-ALPHA-BUDGET-TOKEN" in response_text:
            print("✅ Golden token found in full RAG response")
            print(f"   Documents found: {metadata.get('document_count', 0)}")
            print(f"   Sources: {metadata.get('sources', [])}")
            return True
        else:
            print("❌ Golden token NOT found in RAG response")
            print(f"   Response: {response_text[:200]}...")
            print(f"   Documents found: {metadata.get('document_count', 0)}")
            return False
            
    except Exception as e:
        print(f"❌ Error in end-to-end test: {e}")
        return False

def main():
    """Run all golden document tests"""
    print("🏆 Golden Document Test Suite")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    # Test 1: Ingestion
    if test_golden_document_ingestion():
        tests_passed += 1
    
    # Test 2: Retrieval  
    if test_golden_document_retrieval():
        tests_passed += 1
        
    # Test 3: End-to-end
    if test_end_to_end_golden():
        tests_passed += 1
    
    print(f"\n📊 Test Results: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("✅ All golden document tests PASSED")
        sys.exit(0)
    else:
        print("❌ Some golden document tests FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
