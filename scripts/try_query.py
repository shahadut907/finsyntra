#!/usr/bin/env python3
"""
Test RAG Query Pipeline Without Authentication
"""
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.backend.services.rag_service import RAGService
from src.config.roles import Role

def test_query_without_filters():
    """Test direct vector store query without RBAC filters"""
    print("🔍 Testing direct vector store query (no filters)")
    print("=" * 50)
    
    try:
        rag = RAGService()
        
        # Test query
        test_query = "financial revenue company"
        
        # Direct vector store search (bypassing RBAC)
        print(f"Query: '{test_query}'")
        
        # Try to get embedding and search directly
        embedding = rag.vector_store._get_cached_embedding(test_query)
        if embedding:
            print("✅ Embedding generated successfully")
            
            # Direct ChromaDB query
            results = rag.vector_store.collection.query(
                query_embeddings=[embedding],
                n_results=10,
                include=["metadatas", "documents", "distances"]
            )
            
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            
            print(f"📊 Raw results: {len(documents)} documents found")
            
            for i, (doc, meta, dist) in enumerate(zip(documents[:3], metadatas[:3], distances[:3])):
                print(f"\n📄 Document {i+1}:")
                print(f"  Source: {meta.get('source', 'unknown')}")
                print(f"  Department: {meta.get('department', 'unknown')}")
                print(f"  Distance: {dist:.3f}")
                print(f"  Content: {doc[:100]}...")
                
        else:
            print("❌ Failed to generate embedding")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_query_with_rbac():
    """Test query with RBAC filters for different roles"""
    print("\n🔒 Testing query with RBAC filters")
    print("=" * 50)
    
    test_query = "company financial information"
    roles_to_test = [Role.EMPLOYEE, Role.FINANCE, Role.C_LEVEL]
    
    for role in roles_to_test:
        print(f"\n👤 Testing as {role.value}:")
        try:
            rag = RAGService()
            results = rag.vector_store.search_documents(
                query=test_query,
                user_role=role,
                limit=5
            )
            
            print(f"  📊 Found {len(results)} documents")
            for i, result in enumerate(results[:2]):
                source = result.get('metadata', {}).get('source', 'unknown')
                print(f"    - {source}")
                
        except Exception as e:
            print(f"  ❌ Error for {role.value}: {e}")

def test_golden_token():
    """Test for the golden token in documents"""
    print("\n🏆 Testing for golden token")
    print("=" * 50)
    
    try:
        rag = RAGService()
        
        # Search for the golden token
        golden_query = "ZEBRA-ALPHA-BUDGET-TOKEN"
        
        embedding = rag.vector_store._get_cached_embedding(golden_query)
        if embedding:
            results = rag.vector_store.collection.query(
                query_embeddings=[embedding],
                n_results=5,
                include=["metadatas", "documents"]
            )
            
            documents = results.get("documents", [[]])[0]
            found_token = any(golden_query in doc for doc in documents)
            
            if found_token:
                print("✅ Golden token found in documents!")
            else:
                print("❌ Golden token NOT found - may need to add golden document")
                
                # Try keyword search
                all_docs = rag.vector_store.collection.get(include=["documents"])
                all_text = " ".join(all_docs.get("documents", []))
                if golden_query in all_text:
                    print("✅ Golden token found via keyword search")
                else:
                    print("❌ Golden token completely missing")
        
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    test_query_without_filters()
    test_query_with_rbac() 
    test_golden_token()

if __name__ == "__main__":
    main()
