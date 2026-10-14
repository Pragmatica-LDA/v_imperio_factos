"""Modelos GPT via SDK oficial da OpenAI (Responses API) com structured outputs `strict`."""

from __future__ import annotations

import time

import openai
from django.conf import settings

from .base import LLMResult, Provider, ProviderError

# Valor por omissão quando a ModelConfig não tem base_url (o bench_seed grava-o explicitamente).
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(Provider):
    def __init__(self, config):
        super().__init__(config)
        # base_url explícito: o OPENAI_BASE_URL do ambiente pode apontar para outro serviço OpenAI-compatível
        # (ex.: Ollama), e a SDK usá-lo-ia sem avisar.
        self.client = openai.OpenAI(
            base_url=config.base_url or OPENAI_DEFAULT_BASE_URL,
            api_key=settings.OPENAI_API_KEY or None,
            timeout=settings.LLM_REQUEST_TIMEOUT, max_retries=settings.LLM_MAX_RETRIES,
        )

    def analyse(self, system: str, user: str, schema: dict) -> LLMResult:
        request = {
            "model": self.config.model_id,
            "instructions": system,
            "input": user,
            "max_output_tokens": self.params.get("max_tokens", 16000),
            "text": {"format": {"type": "json_schema", "name": "analise_noticia", "schema": schema, "strict": True}},
        }
        if self.params.get("reasoning_effort"):
            request["reasoning"] = {"effort": self.params["reasoning_effort"]}
        if self.params.get("temperature") is not None:
            request["temperature"] = self.params["temperature"]
        started = time.monotonic()
        try:
            response = self.client.responses.create(**request)
        except openai.APIStatusError as exc:
            raise ProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(f"ligação: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        usage = response.usage
        meta = {
            "status": response.status,
            "response_id": response.id,
            "reasoning_tokens": getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None),
            "cached_tokens": getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
        }
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None)
            raise ProviderError(f"resposta incompleta: {reason}")
        return LLMResult(text=response.output_text, tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
                         latency_ms=latency_ms, meta=meta)
