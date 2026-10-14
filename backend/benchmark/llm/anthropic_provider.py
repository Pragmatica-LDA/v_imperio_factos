"""Claude via SDK oficial da Anthropic, com structured outputs (output_config.format)."""

from __future__ import annotations

import time

import anthropic
from django.conf import settings

from .base import LLMResult, Provider, ProviderError


class AnthropicProvider(Provider):
    def __init__(self, config):
        super().__init__(config)
        kwargs = {"timeout": settings.LLM_REQUEST_TIMEOUT, "max_retries": settings.LLM_MAX_RETRIES}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = anthropic.Anthropic(**kwargs)

    def analyse(self, system: str, user: str, schema: dict) -> LLMResult:
        output_config = {"format": {"type": "json_schema", "schema": schema}}
        if self.params.get("effort"):
            output_config["effort"] = self.params["effort"]
        request = {
            "model": self.config.model_id,
            "max_tokens": self.params.get("max_tokens", 16000),
            # O system prompt é igual em todos os artigos: fica em cache entre pedidos.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if self.params.get("thinking"):
            request["thinking"] = self.params["thinking"]
        # Sem `fallbacks`: no benchmark queremos medir este modelo; uma recusa fica registada como erro.
        started = time.monotonic()
        try:
            response = self.client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"ligação: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        usage = response.usage
        meta = {
            "stop_reason": response.stop_reason,
            "request_id": response._request_id,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        }
        if response.stop_reason == "refusal":
            raise ProviderError(f"recusa: {response.stop_details}")
        text = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason == "max_tokens":
            raise ProviderError(f"resposta truncada (max_tokens={request['max_tokens']}): {text[-200:]}")
        tokens_in = (usage.input_tokens or 0) + (meta["cache_read_input_tokens"] or 0) + (
            meta["cache_creation_input_tokens"] or 0)
        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=usage.output_tokens,
                         latency_ms=latency_ms, meta=meta)
