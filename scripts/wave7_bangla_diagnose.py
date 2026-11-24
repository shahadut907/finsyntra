"""Diagnose where the Bangla /api/chat pipeline hangs, by timing each stage
of RAGService.process_query directly (no HTTP, no asyncio) using the real
.env (real Groq key, real corpus). Never prints the API key."""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.backend.services.rag_service as rs
from src.backend.services.rag_service import RAGService
from src.config.roles import Role

orig_detect = rs.detect_language
orig_prepare = rs.prepare_retrieval_query
orig_search = RAGService._search_documents_gpu_optimized
orig_verify = RAGService._verify_documents_batch
orig_generate = RAGService._generate_gpu_optimized_response


def timed(label, fn):
    def wrapper(*args, **kwargs):
        t0 = time.time()
        print(f"[{label}] START", flush=True)
        try:
            result = fn(*args, **kwargs)
            print(f"[{label}] DONE in {time.time()-t0:.2f}s", flush=True)
            return result
        except Exception as e:
            print(f"[{label}] RAISED {type(e).__name__} after {time.time()-t0:.2f}s: {e}", flush=True)
            raise
    return wrapper


rs.detect_language = timed("detect_language", orig_detect)
rs.prepare_retrieval_query = timed("prepare_retrieval_query", orig_prepare)
RAGService._search_documents_gpu_optimized = timed("search_documents", orig_search)
RAGService._verify_documents_batch = timed("verify_documents_batch", orig_verify)
RAGService._generate_gpu_optimized_response = timed("generate_response", orig_generate)

print("Constructing RAGService()...", flush=True)
t0 = time.time()
svc = RAGService()
print(f"RAGService() constructed in {time.time()-t0:.2f}s", flush=True)

print("Calling process_query with Bangla handbook question...", flush=True)
t0 = time.time()
result = svc.process_query(
    query="কোম্পানির ছুটির নীতি সম্পর্কে বলুন।",
    user_id="employee@finsolve.com",
    tenant_id="tenant_acme",
    top_k=8,
    departments=["employee"],
    conversation_id="diag-bn-1",
    include_citations=True,
    user_role=Role.EMPLOYEE,
    user_name="employee",
    conversation_history=[],
)
print(f"process_query returned in {time.time()-t0:.2f}s", flush=True)
print("RESULT:", {k: v for k, v in result.items() if k != "performance_breakdown"})
