"""Small, provider-neutral LLM inference boundary for FinSyntra."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Optional

import requests

from src.config.settings import settings

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.services.model_catalog import ModelSelection

logger = logging.getLogger(__name__)


class LLMGenerationError(RuntimeError):
    """Safe, machine-readable generation failure.

    Provider response bodies and transport exceptions are logged server-side but
    are never copied into ``user_message``.
    """

    def __init__(self, reason: str, message: str, retry_after_seconds: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.user_message = message
        self.retry_after_seconds = retry_after_seconds


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate(
        self, prompt: str, system: Optional[str] = None, options: "Optional[ModelSelection]" = None
    ) -> str:
        """Return generated text or raise ``LLMGenerationError``.

        ``options`` is a server-validated model selection (see
        ``model_catalog.resolve_selection``); ``None`` keeps the configured
        defaults.

        ``system`` carries operator instructions in the provider's system
        channel, kept apart from ``prompt`` (which may contain retrieved,
        untrusted document text).
        """

    @abstractmethod
    def healthcheck(self) -> bool:
        """Return whether the configured provider is reachable and authorized."""


_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_private_reasoning(text: str) -> str:
    """Defence in depth: reasoning is requested hidden, but never let a
    provider-side default leak ``<think>`` blocks into a delivered answer."""
    cleaned = _THINK_BLOCK.sub("", text)
    if "<think>" in cleaned.lower():  # unterminated block: drop everything after it
        cleaned = cleaned[: cleaned.lower().index("<think>")]
    return cleaned.strip()


def _parse_retry_after(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = int(float(value))
        return max(0, min(parsed, 3600))
    except (TypeError, ValueError):
        return None


@dataclass
class OllamaProvider(LLMProvider):
    base_url: str
    model: str
    timeout_seconds: int
    cuda_available: bool = False
    name: str = "ollama"

    def _model_options(self) -> dict:
        return {"num_ctx": 2048, "num_gpu": -1 if self.cuda_available else 0, "num_thread": 4}

    def warm_up(self) -> None:
        """Load the local model once at startup without running inference."""
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json={"model": self.model, "keep_alive": "10m", "stream": False,
                      "options": self._model_options()},
                timeout=(2, min(self.timeout_seconds, 15)),
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("OLLAMA_WARMUP_FAILED error=%s", type(exc).__name__)
            return
        if response.status_code != 200:
            logger.warning("OLLAMA_WARMUP_FAILED status=%s", response.status_code)
        else:
            logger.info("OLLAMA_WARMUP_COMPLETE")

    def generate(self, prompt: str, system: Optional[str] = None, options=None) -> str:
        # Ollama serves the single configured model; the catalog offers no
        # other alias or effort for it, so ``options`` carries nothing to apply.
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    **({"system": system} if system else {}),
                    "stream": False,
                    "keep_alive": "10m",
                    "options": {
                        **self._model_options(),
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 320,
                        "repeat_penalty": 1.1,
                        "stop": ["Question:", "Context:", "\n\nUser:"],
                    },
                },
                timeout=self.timeout_seconds,
            )
            if response.status_code != 200:
                logger.error("LLM_HTTP_ERROR provider=ollama status=%s model=%s", response.status_code, self.model)
                raise LLMGenerationError("error", "The language model could not generate a response.")
            try:
                payload = response.json()
            except ValueError as exc:
                logger.error("LLM_MALFORMED_RESPONSE provider=ollama model=%s", self.model, exc_info=True)
                raise LLMGenerationError("malformed", "The language model returned an unreadable response.") from exc
            if not isinstance(payload, dict):
                raise LLMGenerationError("malformed", "The language model returned an unexpected response.")
            text = (payload.get("response") or "").strip()
            if not text:
                raise LLMGenerationError("malformed", "The language model returned an empty response.")
            return text
        except LLMGenerationError:
            raise
        except requests.exceptions.Timeout as exc:
            logger.error("LLM_TIMEOUT provider=ollama model=%s timeout=%ss", self.model, self.timeout_seconds)
            raise LLMGenerationError(
                "timeout", f"The language model did not respond within {self.timeout_seconds}s."
            ) from exc
        except requests.exceptions.RequestException as exc:
            logger.error("LLM_UNAVAILABLE provider=ollama model=%s", self.model, exc_info=True)
            raise LLMGenerationError("unavailable", "The language model service is unavailable.") from exc
        except Exception as exc:
            logger.error("LLM_ERROR provider=ollama model=%s", self.model, exc_info=True)
            raise LLMGenerationError("error", "The language model could not generate a response.") from exc

    def healthcheck(self) -> bool:
        try:
            response = requests.get(f"{self.base_url.rstrip('/')}/api/tags", timeout=3)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


@dataclass
class GroqProvider(LLMProvider):
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    max_completion_tokens: int = 1024
    reasoning_effort: str = "auto"
    name: str = "groq"

    def _resolved_reasoning_effort(self) -> Optional[str]:
        effort = (self.reasoning_effort or "").strip().lower()
        if effort == "auto":
            return "low" if "gpt-oss" in self.model.lower() else None
        if effort in {"", "none"}:
            return None
        return effort

    def generate(self, prompt: str, system: Optional[str] = None, options=None) -> str:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        model = options.provider_model if options else self.model
        max_tokens = options.max_completion_tokens if options else self.max_completion_tokens
        timeout = options.timeout_seconds if options else self.timeout_seconds
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "top_p": 0.9,
            "max_completion_tokens": max_tokens,
            "stream": False,
        }
        if options:
            # Allowlisted values only (model_catalog); never client-supplied.
            body.update(options.sampling)
            body.update(options.reasoning_controls)
            effort = options.reasoning_effort
        else:
            effort = self._resolved_reasoning_effort()
        if effort:
            body["reasoning_effort"] = effort
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                logger.warning("LLM_RATE_LIMITED provider=groq model=%s retry_after=%s", model, retry_after)
                raise LLMGenerationError(
                    "rate_limited",
                    "The language model is temporarily busy. Please try again shortly.",
                    retry_after_seconds=retry_after,
                )
            if response.status_code in {401, 403}:
                logger.error("LLM_AUTH_ERROR provider=groq status=%s model=%s", response.status_code, model)
                raise LLMGenerationError("unavailable", "The language model service is unavailable.")
            if response.status_code >= 500:
                logger.error("LLM_UPSTREAM_ERROR provider=groq status=%s model=%s", response.status_code, model)
                raise LLMGenerationError("unavailable", "The language model service is unavailable.")
            if response.status_code != 200:
                logger.error("LLM_HTTP_ERROR provider=groq status=%s model=%s", response.status_code, model)
                raise LLMGenerationError("error", "The language model could not generate a response.")
            try:
                payload = response.json()
                choice = payload["choices"][0]
                text = _strip_private_reasoning(choice["message"].get("content") or "")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                logger.error("LLM_MALFORMED_RESPONSE provider=groq model=%s", model, exc_info=True)
                raise LLMGenerationError("malformed", "The language model returned an unreadable response.") from exc
            if not text:
                usage = payload.get("usage") or {}
                logger.error(
                    "LLM_EMPTY_RESPONSE provider=groq model=%s finish_reason=%s completion_tokens=%s "
                    "reasoning_tokens=%s max_completion_tokens=%s",
                    model, choice.get("finish_reason"), usage.get("completion_tokens"),
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                    max_tokens,
                )
                raise LLMGenerationError("malformed", "The language model returned an empty response.")
            return text
        except LLMGenerationError:
            raise
        except requests.exceptions.Timeout as exc:
            logger.error("LLM_TIMEOUT provider=groq model=%s timeout=%ss", model, timeout)
            raise LLMGenerationError(
                "timeout", f"The language model did not respond within {timeout}s."
            ) from exc
        except requests.exceptions.RequestException as exc:
            logger.error("LLM_UNAVAILABLE provider=groq model=%s", model, exc_info=True)
            raise LLMGenerationError("unavailable", "The language model service is unavailable.") from exc
        except Exception as exc:
            logger.error("LLM_ERROR provider=groq model=%s", model, exc_info=True)
            raise LLMGenerationError("error", "The language model could not generate a response.") from exc

    def healthcheck(self) -> bool:
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=min(self.timeout_seconds, 5),
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


def create_llm_provider(*, cuda_available: bool = False) -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            cuda_available=cuda_available,
        )
    if provider == "groq":
        return GroqProvider(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            model=settings.groq_model,
            timeout_seconds=settings.groq_timeout_seconds,
            max_completion_tokens=settings.groq_max_completion_tokens,
            reasoning_effort=settings.groq_reasoning_effort,
        )
    raise RuntimeError(f"Unsupported LLM provider: {provider}")
