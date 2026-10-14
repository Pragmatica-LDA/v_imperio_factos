"""Modelos open source no Ollama (Ollama Cloud em ollama.com ou servidor próprio): /api/chat com `format` = JSON schema.

No Ollama Cloud os modelos usam o nome do catálogo (ex.: "gpt-oss:120b"); o sufixo "-cloud" só existe
quando se passa por um Ollama local, e é retirado aqui quando o destino é o ollama.com.
"""

from __future__ import annotations

import json
import time

import httpx
from django.conf import settings

from .base import LLMResult, Provider, ProviderError

# Opções do Ollama que passam directamente de ModelConfig.params para `options`.
OLLAMA_OPTIONS = ("temperature", "num_ctx", "num_predict", "top_p", "top_k", "seed", "repeat_penalty")


def base_url(config=None) -> str:
    url = (config.base_url if config and config.base_url else settings.OLLAMA_BASE_URL) or ""
    if not url:
        raise ProviderError("OLLAMA_BASE_URL vazio e sem base_url na ModelConfig.")
    return url.rstrip("/")


def headers() -> dict:
    key = settings.OLLAMA_API_KEY
    return {"Authorization": f"Bearer {key}"} if key else {}


def model_name(model_id: str, url: str) -> str:
    if "ollama.com" in url and model_id.endswith("-cloud"):
        return model_id.removesuffix("-cloud")
    return model_id


def list_models(url: str | None = None) -> list[dict]:
    """Modelos disponíveis (GET /api/tags): no ollama.com, o catálogo cloud; num servidor próprio, os descarregados."""
    response = httpx.get(f"{(url or base_url()).rstrip('/')}/api/tags", headers=headers(), timeout=30)
    response.raise_for_status()
    return response.json().get("models", [])


SCHEMA_INSTRUCTION = (
    "\n\nFormato da resposta: devolve APENAS um objecto JSON válido (sem texto antes ou depois, sem ```), "
    "que cumpra exactamente este JSON Schema:\n{schema}"
)


class OllamaProvider(Provider):
    def analyse(self, system: str, user: str, schema: dict) -> LLMResult:
        # O Ollama Cloud ignora `format` (sem constrained decoding): o schema vai também no prompt.
        if self.params.get("schema_in_prompt", True):
            system += SCHEMA_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))
        options = {k: self.params[k] for k in OLLAMA_OPTIONS if k in self.params}
        # O contexto por omissão do Ollama é curto e cortava o prompt sem avisar.
        options.setdefault("num_ctx", settings.OLLAMA_DEFAULT_NUM_CTX)
        url = base_url(self.config)
        request = {
            "model": model_name(self.config.model_id, url),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": options,
            "keep_alive": self.params.get("keep_alive", "10m"),
        }
        if "think" in self.params:
            request["think"] = self.params["think"]
        started = time.monotonic()
        try:
            response = httpx.post(f"{url}/api/chat", json=request, headers=headers(),
                                  timeout=settings.LLM_REQUEST_TIMEOUT)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"ligação: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        data = response.json()
        eval_count, eval_ns = data.get("eval_count"), data.get("eval_duration")
        meta = {
            "done_reason": data.get("done_reason"),
            "load_duration_ms": (data.get("load_duration") or 0) // 1_000_000,
            "prompt_eval_ms": (data.get("prompt_eval_duration") or 0) // 1_000_000,
            "eval_ms": (eval_ns or 0) // 1_000_000,
            "tokens_per_s": round(eval_count / (eval_ns / 1e9), 1) if eval_count and eval_ns else None,
            "num_ctx": options["num_ctx"],
        }
        prompt_tokens = data.get("prompt_eval_count")
        if prompt_tokens and prompt_tokens >= options["num_ctx"]:
            raise ProviderError(f"prompt ({prompt_tokens} tokens) não cabe em num_ctx={options['num_ctx']}")
        if data.get("done_reason") == "length":
            raise ProviderError(f"resposta truncada (done_reason=length): {data['message']['content'][-200:]}")
        return LLMResult(text=data["message"]["content"], tokens_in=prompt_tokens, tokens_out=eval_count,
                         latency_ms=latency_ms, meta=meta)
