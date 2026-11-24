"""Server-side allowlist of user-selectable chat models.

The browser only ever sends an *alias* (``prism`` / ``atlas`` / ``axiom``) and
optionally a reasoning-effort value. Both are validated here against a fixed
table; provider model ids, URLs and request parameters never come from the
client.

Mappings and parameters were checked against Groq's documentation
(console.groq.com/docs/reasoning, /docs/models, /docs/model/*) on 2026-11-01:

* openai/gpt-oss-20b, openai/gpt-oss-120b - production models; accept
  ``reasoning_effort`` low|medium|high; ``reasoning_format`` is NOT supported,
  reasoning text is suppressed with ``include_reasoning: false``.
* qwen/qwen3.8-27b - *preview* model ("evaluation purposes only ... may be
  discontinued at short notice"); accepts ``reasoning_effort``
  none|default|low|medium|high; reasoning text is suppressed with
  ``reasoning_format: "hidden"``.

Availability is confirmed at runtime against the provider's /models listing,
so an alias is only offered as operational when its model is actually served
for the configured key.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from src.config.settings import settings

logger = logging.getLogger(__name__)

EFFORT_LABELS = {"low": "Low", "medium": "Medium", "high": "High"}


class ModelSelectionError(ValueError):
    """Client sent an alias/effort the server does not allow."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ModelProfile:
    alias: str
    label: str
    description: str
    provider: str
    provider_model: str
    efforts: Tuple[str, ...] = ()
    default_effort: Optional[str] = None
    # Provider request fields that keep private reasoning out of the answer.
    reasoning_controls: Dict[str, object] = field(default_factory=dict)
    preview: bool = False
    sampling: Dict[str, float] = field(default_factory=dict)


# Per-effort generation budget. Reasoning tokens are spent before answer text
# (an empty answer was observed at 320 tokens), so higher effort needs room.
# Timeouts stay below the SSE hard timeout (validated in settings.py).
_EFFORT_BUDGET = {
    None: (1024, 20),
    "low": (1024, 20),
    "medium": (2048, 30),
    "high": (4096, 40),
}

GROQ_PROFILES: Tuple[ModelProfile, ...] = (
    ModelProfile(
        alias="prism",
        label="Prism",
        description="Fast answers for everyday questions",
        provider="groq",
        provider_model="openai/gpt-oss-20b",
        efforts=("low", "medium", "high"),
        default_effort="low",
        reasoning_controls={"include_reasoning": False},
    ),
    ModelProfile(
        alias="atlas",
        label="Atlas",
        description="Balanced depth for document analysis",
        provider="groq",
        provider_model="openai/gpt-oss-120b",
        efforts=("low", "medium", "high"),
        default_effort="medium",
        reasoning_controls={"include_reasoning": False},
    ),
    ModelProfile(
        alias="axiom",
        label="Axiom",
        description="Deliberate reasoning for complex questions (preview model)",
        provider="groq",
        provider_model="qwen/qwen3.8-27b",
        efforts=("low", "medium", "high"),
        default_effort="medium",
        reasoning_controls={"reasoning_format": "hidden"},
        preview=True,
        # Qwen documents that greedy/very-low-temperature decoding degrades
        # its thinking mode; keep sampling moderate.
        sampling={"temperature": 0.6, "top_p": 0.95},
    ),
)


@dataclass(frozen=True)
class ModelSelection:
    """A validated, server-resolved choice for one request."""

    alias: str
    label: str
    provider: str
    provider_model: str
    reasoning_effort: Optional[str]
    reasoning_controls: Dict[str, object]
    max_completion_tokens: int
    timeout_seconds: int
    sampling: Dict[str, float]

    @property
    def cache_token(self) -> str:
        return f"{self.alias}:{self.provider_model}:{self.reasoning_effort or '-'}"

    def public_dict(self) -> Dict[str, Optional[str]]:
        """What the client and the message record are allowed to see."""
        return {
            "alias": self.alias,
            "label": self.label,
            "reasoning_effort": self.reasoning_effort,
        }

    def record_dict(self) -> Dict[str, Optional[str]]:
        """Stored with the assistant message (no secrets, no URLs)."""
        return {
            **self.public_dict(),
            "provider": self.provider,
            "provider_model": self.provider_model,
        }


def _active_provider() -> str:
    return settings.llm_provider.strip().lower()


def _ollama_profiles() -> Tuple[ModelProfile, ...]:
    # A local Ollama deployment serves exactly one configured model and has no
    # verified reasoning control, so only Prism is offered and effort is hidden.
    return (
        ModelProfile(
            alias="prism",
            label="Prism",
            description="Local model configured for this server",
            provider="ollama",
            provider_model=settings.ollama_model,
        ),
    )


def _profiles() -> Tuple[ModelProfile, ...]:
    return GROQ_PROFILES if _active_provider() == "groq" else _ollama_profiles()


def _profile(alias: str) -> Optional[ModelProfile]:
    return next((p for p in _profiles() if p.alias == alias), None)


class _AvailabilityCache:
    """Remembers which provider models the configured key can use."""

    TTL_SECONDS = 600

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: Optional[set] = None
        self._checked_at = 0.0

    def reset(self) -> None:
        with self._lock:
            self._models = None
            self._checked_at = 0.0

    def served_models(self) -> Optional[set]:
        """Model ids listed by the provider, or None when unknown."""
        if _active_provider() != "groq":
            return None
        with self._lock:
            fresh = self._models is not None and time.monotonic() - self._checked_at < self.TTL_SECONDS
            if fresh:
                return self._models
        try:
            response = requests.get(
                f"{settings.groq_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                timeout=5,
            )
            if response.status_code != 200:
                logger.warning("MODEL_CATALOG_LIST_FAILED status=%s", response.status_code)
                return self._models
            ids = {
                item.get("id")
                for item in (response.json().get("data") or [])
                if isinstance(item, dict) and item.get("active", True)
            }
        except (requests.exceptions.RequestException, ValueError):
            logger.warning("MODEL_CATALOG_LIST_FAILED", exc_info=True)
            return self._models
        with self._lock:
            self._models = ids
            self._checked_at = time.monotonic()
        return ids


availability = _AvailabilityCache()


def _is_available(profile: ModelProfile) -> Tuple[bool, Optional[str]]:
    if profile.provider == "ollama":
        return True, None
    served = availability.served_models()
    if served is None:
        # Listing unavailable: only the model the server was configured and
        # validated with at startup is known to work.
        if profile.provider_model == settings.groq_model:
            return True, None
        return False, "Availability could not be confirmed with the provider"
    if profile.provider_model not in served:
        return False, "Not available for this server's provider account"
    return True, None


def default_alias() -> str:
    configured = (settings.chat_default_model or "").strip().lower()
    profiles = _profiles()
    if _profile(configured) and _is_available(_profile(configured))[0]:
        return configured
    for profile in profiles:
        if _is_available(profile)[0]:
            return profile.alias
    return profiles[0].alias


def get_catalog() -> Dict[str, object]:
    models: List[Dict[str, object]] = []
    for profile in _profiles():
        available, reason = _is_available(profile)
        models.append({
            "id": profile.alias,
            "label": profile.label,
            "description": profile.description,
            "available": available,
            "unavailable_reason": reason,
            "preview": profile.preview,
            "efforts": [{"id": e, "label": EFFORT_LABELS[e]} for e in profile.efforts],
            "default_effort": profile.default_effort,
        })
    return {"models": models, "default_model": default_alias()}


def resolve_selection(alias: Optional[str], effort: Optional[str]) -> ModelSelection:
    """Validate a client choice and resolve it to provider parameters.

    ``alias=None`` means "server default". Unknown aliases, unavailable
    models and efforts the model does not support are rejected rather than
    silently replaced.
    """
    requested = (alias or "").strip().lower() or default_alias()
    profile = _profile(requested)
    if profile is None:
        raise ModelSelectionError("invalid_model", "The selected model is not offered by this server.")
    available, reason = _is_available(profile)
    if not available:
        raise ModelSelectionError("model_unavailable", f"{profile.label} is unavailable: {reason}.")

    requested_effort = (effort or "").strip().lower() or None
    if requested_effort is None:
        resolved_effort = profile.default_effort
    elif requested_effort in profile.efforts:
        resolved_effort = requested_effort
    else:
        raise ModelSelectionError(
            "invalid_effort",
            f"{profile.label} does not support a '{requested_effort}' thinking effort."
            if profile.efforts else f"{profile.label} has no adjustable thinking effort.",
        )

    max_tokens, timeout = _EFFORT_BUDGET.get(resolved_effort, _EFFORT_BUDGET[None])
    # Never exceed the SSE hard deadline (minus a margin for retrieval).
    timeout = max(5, min(timeout, settings.rag_hard_timeout_seconds - 4))
    return ModelSelection(
        alias=profile.alias,
        label=profile.label,
        provider=profile.provider,
        provider_model=profile.provider_model,
        reasoning_effort=resolved_effort,
        reasoning_controls=dict(profile.reasoning_controls),
        max_completion_tokens=max_tokens,
        timeout_seconds=timeout,
        sampling=dict(profile.sampling),
    )
