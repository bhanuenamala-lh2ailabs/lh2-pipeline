"""Thin Claude wrapper: single-purpose prompts, retry, response caching.

Claude usage discipline (spec §8): one extraction / one match per call, Haiku
for both, cache every response, never re-run a cached judgment.

Testability: pass a ``responder`` callable (system, user, model) -> str to use
instead of the real API. Production leaves it None and lazily builds the
Anthropic client from the API key.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Optional

from ..logging_setup import get_logger

log = get_logger("lh2.judge")

Responder = Callable[[str, str, str], str]


def _cache_key(kind: str, system: str, user: str, model: str) -> str:
    h = hashlib.sha1(f"{system}\x00{user}\x00{model}".encode("utf-8")).hexdigest()
    return f"claude:{kind}:{h}"


def _extract_json(text: str) -> Any:
    """Pull the first JSON value out of a model response (tolerates code fences)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except Exception:
        # find first { or [ ... balanced-ish fallback
        m = re.search(r"(\{.*\}|\[.*\])", t, flags=re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise


class ClaudeClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_default: str = "claude-haiku-4-5-20251001",
        store=None,                       # noqa: ANN001 — optional Store for caching
        max_tokens: int = 1024,
        responder: Optional[Responder] = None,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.model_default = model_default
        self.store = store
        self.max_tokens = max_tokens
        self._responder = responder
        self.max_retries = max_retries
        self._client = None
        self.calls = 0          # cost counter (non-cached API calls)
        self.tokens = 0

    # -- real transport (lazy anthropic) ----------------------------------- #
    def _ensure_client(self):
        if self._client is not None:
            return
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                'anthropic SDK not installed. Install with: pip install -e ".[enrich]"'
            ) from e
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def _raw_call(self, system: str, user: str, model: str) -> str:
        if self._responder is not None:
            return self._responder(system, user, model)
        self._ensure_client()
        last: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                self.calls += 1
                try:
                    self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
                except Exception:
                    pass
                return "".join(
                    block.text for block in resp.content if getattr(block, "type", "") == "text"
                )
            except Exception as e:  # pragma: no cover - network dependent
                last = e
                log.info("claude_retry", attempt=attempt, err=str(e))
        raise RuntimeError(f"Claude call failed after {self.max_retries} attempts: {last}")

    # -- public: cached JSON judgment -------------------------------------- #
    def judge_json(self, kind: str, system: str, user: str, model: Optional[str] = None) -> Any:
        model = model or self.model_default
        key = _cache_key(kind, system, user, model)
        if self.store is not None:
            cached = self.store.cache_get(key)
            if cached is not None:
                log.debug("claude_cache_hit", kind=kind)
                return cached
        text = self._raw_call(system, user, model)
        value = _extract_json(text)
        if self.store is not None:
            self.store.cache_set(key, value)
        return value
