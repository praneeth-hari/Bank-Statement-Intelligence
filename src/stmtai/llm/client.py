"""A small Ollama client using only the standard library.

Ollama runs models locally (``ollama serve``, default http://127.0.0.1:11434). Nothing here sends data off the
machine, which matters for bank statements even when they are synthetic today.

Structured output: the request carries a JSON schema in ``format`` and Ollama constrains decoding to it, so the
reply always parses. That guarantees *shape*, not *truth*; the checks in ``stmtai.llm.validate`` are what decide
whether a proposed value is acceptable.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"  # ~1.9 GB at 4-bit, fits a 4 GB GPU with room for the context


class LLMUnavailable(RuntimeError):
    """Ollama is not reachable, the model is not pulled, or the call failed. Never fatal to extraction."""


@dataclass
class OllamaClient:
    model: str = field(default_factory=lambda: os.environ.get("STMTAI_LLM_MODEL", DEFAULT_MODEL))
    host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    timeout: float = 120.0  # seconds per call; the first call includes loading the model
    num_ctx: int = 4096
    seed: int = 7
    keep_alive: str = "10m"
    calls: int = 0
    seconds: float = 0.0
    last_error: Optional[str] = None
    cache_dir: Optional[Path] = None  # replies are stored here, so a repeated evaluation run costs nothing
    cache_hits: int = 0

    def __post_init__(self) -> None:
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.host = self.host.rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    # ------------------------------------------------------------------ transport
    def _request(self, path: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.host + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise LLMUnavailable(f"Ollama returned {exc.code} for {path}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise LLMUnavailable(f"cannot reach Ollama at {self.host} ({exc}). Is `ollama serve` running?") from exc
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"Ollama sent something that is not JSON for {path}") from exc

    def _cache_path(self, body: dict) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        return Path(self.cache_dir) / f"{key}.json"

    # ------------------------------------------------------------------ public
    def check(self) -> None:
        """Raise ``LLMUnavailable`` unless the server is up and the model is pulled."""
        tags = self._request("/api/tags", timeout=5)
        names = [m.get("name", "") for m in tags.get("models", [])]
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in names:
            have = ", ".join(names) or "none"
            raise LLMUnavailable(f"model '{self.model}' is not pulled (have: {have}). Run: ollama pull {self.model}")

    def chat_json(self, system: str, user: str, schema: dict, max_tokens: int = 700) -> Any:
        """One chat turn that must answer in ``schema``. Returns the parsed object."""
        body = {
            "model": self.model, "stream": False, "format": schema, "keep_alive": self.keep_alive,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        cached = self._cache_path(body)
        if cached is not None and cached.exists():
            self.cache_hits += 1
            reply = json.loads(cached.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            try:
                reply = self._request("/api/chat", body)
            except LLMUnavailable as exc:
                self.last_error = str(exc)
                raise
            finally:
                self.calls += 1
                self.seconds += time.time() - t0
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(reply), encoding="utf-8")
        content = (reply.get("message") or {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            self.last_error = f"model reply was not valid JSON: {content[:120]!r}"
            raise LLMUnavailable(self.last_error) from exc


def from_spec(spec: Optional[str]) -> Optional[OllamaClient]:
    """``STMTAI_LLM`` values: empty/off -> None; ``ollama`` -> default model; ``ollama:<model>`` -> that model."""
    if not spec or spec.strip().lower() in ("0", "off", "none", "false"):
        return None
    kind, _, model = spec.strip().partition(":")
    if kind.lower() != "ollama":
        raise ValueError(f"unknown LLM provider '{kind}' (only 'ollama' is supported)")
    return OllamaClient(model=model) if model else OllamaClient()
