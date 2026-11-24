#!/usr/bin/env python3
"""
Document Loader Script - Load existing documents into ChromaDB vector store
Place this file at: scripts/load_documents.py
"""
import os
import sys

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.backend.services.rag_service import RAGService
from src.config.settings import settings


def main():
    """Load your existing documents into the vector store"""
    print("🚀 FinSyntra Document Loader")
    print("=" * 50)
    
    # Check if data directory exists
    data_dir = os.path.join(project_root, "src", "data", "raw")
    if not os.path.exists(data_dir):
        print(f"❌ Data directory not found: {data_dir}")
        print("📁 Please ensure your documents are in: src/data/raw/")
        return False
    
    # List files in data directory
    files = [f for f in os.listdir(data_dir) if f.endswith(('.md', '.csv', '.txt', '.pdf'))]
    if not files:
        print(f"❌ No supported documents found in {data_dir}")
        print("📄 Supported formats: .md, .csv, .txt, .pdf")
        return False
    
    print(f"📂 Found {len(files)} documents to process:")
    for file in files:
        file_path = os.path.join(data_dir, file)
        file_size = os.path.getsize(file_path)
        print(f"   - {file} ({file_size:,} bytes)")
    
    # Initialize RAG service
    print("\n🧠 Initializing RAG Service...")
    try:
        rag_service = RAGService()
        print("✅ RAG Service initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize RAG Service: {e}")
        print("💡 Make sure Ollama is running and your environment is set up correctly")
        return False
    
    # Clear existing documents (optional)
    print("\n🗑️ Clearing existing vector store...")
    try:
        rag_service.vector_store.clear_collection()
        print("✅ Vector store cleared")
    except Exception as e:
        print(f"⚠️ Warning: Could not clear vector store: {e}")
    
    # Load documents
    print(f"\n📚 Processing and loading documents...")
    try:
        result = rag_service.load_documents(data_dir)
        
        if result["success"]:
            print("✅ Documents loaded successfully!")
            print(f"📊 Processed {result['chunks_processed']} text chunks")
            print(f"📄 Documents loaded:")
            for doc in result.get('documents', []):
                print(f"   - {doc}")
            
            # Test the system
            print("\n🧪 Testing system status...")
            system_info = rag_service.get_system_info()
            vector_stats = system_info.get('vector_store', {})
            total_docs = vector_stats.get('total_documents', 0)
            
            print(f"📈 Vector store: {total_docs} document chunks stored")
            print(f"🤖 Ollama status: {'✅ Ready' if system_info.get('ollama_status') else '❌ Not available'}")
            
            if total_docs > 0:
                print("\n🎉 Success! Your RAG system is ready!")
                print("💡 Next steps:")
                print("   1. Start your FastAPI server: python -m src.backend.endpoints")
                print("   2. Open your React frontend")
                print("   3. Try asking questions about your documents!")
            
        else:
            print(f"❌ Failed to load documents: {result['message']}")
            if 'error' in result:
                print(f"Error details: {result['error']}")
            return False
            
    except Exception as e:
        print(f"❌ Error during document loading: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    if success:
        print("\n✨ Document loading completed successfully!")
    else:
        print("\n💥 Document loading failed!")
    sys.exit(0 if success else 1)