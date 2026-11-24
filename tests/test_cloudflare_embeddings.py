"""Cloudflare embeddings provider: client behaviour and collection isolation (no network)."""
import pytest
from unittest.mock import patch, MagicMock

from src.backend.services import vector_store as vs


def _resp(status=200, payload=None):
    r = MagicMock(); r.status_code = status; r.text = "x"
    r.json.return_value = payload if payload is not None else {}
    return r


def _client():
    return vs.CloudflareEmbeddingsClient("acct", "tok", "@cf/baai/bge-m3", batch_size=2, max_retries=0)


def test_embed_batches_and_returns_vectors():
    ok = lambda n: _resp(200, {"success": True, "result": {"data": [[0.0] * 1024] * n}})
    with patch.object(vs.requests, "post", side_effect=[ok(2), ok(1)]) as post:
        out = _client().embed(["a", "b", "c"])
    assert len(out) == 3 and len(out[0]) == 1024 and post.call_count == 2


def test_wrong_shape_raises_and_never_falls_back():
    with patch.object(vs.requests, "post", return_value=_resp(200, {"success": True, "result": {"data": [[0.1]]}})):
        with pytest.raises(vs.CloudflareEmbeddingsError):
            _client().embed(["a", "b"])


def test_http_error_raises_without_leaking_token():
    with patch.object(vs.requests, "post", return_value=_resp(403)):
        with pytest.raises(vs.CloudflareEmbeddingsError) as e:
            _client().embed(["a"])
    assert "tok" not in str(e.value).replace("token", "")


def test_missing_credentials_rejected():
    with pytest.raises(vs.CloudflareEmbeddingsError):
        vs.CloudflareEmbeddingsClient("", "", "m")


def test_collections_never_shared_between_providers():
    assert vs.resolve_collection_name(None, "cloudflare") != vs.resolve_collection_name(None, "local")
    assert vs.resolve_collection_name("explicit", "cloudflare") == "explicit"
