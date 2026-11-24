#!/usr/bin/env python3
"""
FinSyntra RAG System - Startup Script
Simple and clean startup for the RAG chatbot system
"""

import os
import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    required_packages = [
        'fastapi', 'uvicorn', 'chromadb', 'sentence-transformers',
        'ollama', 'langchain', 'asyncpg', 'redis'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing packages: {', '.join(missing_packages)}")
        print("Run: pip install -r requirements.txt")
        return False
    
    print("✅ All dependencies installed")
    return True

def check_ollama():
    """Check if Ollama is running"""
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama is running")
            return True
    except:
        pass
    
    print("⚠️  Ollama not detected. Make sure Ollama is installed and running:")
    print("   Download: https://ollama.ai")
    print("   Run: ollama serve")
    return False

def start_backend():
    """Start the FastAPI backend server"""
    print("\n🚀 Starting FinSyntra RAG Backend...")
    
    # Set environment variables
    os.environ.setdefault("FIN_DEBUG", "true")
    os.environ.setdefault("FIN_HOST", "localhost")
    os.environ.setdefault("FIN_PORT", "8000")
    
    try:
        # Start the server
        cmd = [
            sys.executable, "-m", "uvicorn",
            "src.backend.api.endpoints:app",
            "--host", "localhost",
            "--port", "8000",
            "--reload"
        ]
        
        print(f"📡 Backend will be available at: http://localhost:8000")
        print(f"📚 API Documentation: http://localhost:8000/docs")
        print(f"🔧 Health Check: http://localhost:8000/health")
        print("\n" + "="*50)
        
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        return False
    
    return True

def main():
    """Main startup function"""
    print("🎯 FinSyntra RAG System - Startup")
    print("="*50)
    
    # Check if we're in the right directory
    if not Path("src/backend/api/endpoints.py").exists():
        print("❌ Please run this script from the project root directory")
        return False
    
    # Check dependencies
    if not check_dependencies():
        return False
    
    # Check Ollama (optional but recommended)
    check_ollama()
    
    # Start the backend
    return start_backend()

if __name__ == "__main__":
    main() 