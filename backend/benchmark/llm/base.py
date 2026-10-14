"""Contrato comum dos providers de LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class ProviderError(Exception):
    """Falha do provider (rede, HTTP, recusa, resposta truncada). Fica registada no AnalysisResult."""


@dataclass
class LLMResult:
    text: str                              # resposta crua (o JSON em texto)
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None          # medido do nosso lado, pedido completo
    meta: dict = field(default_factory=dict)   # stop_reason, tokens/s reportados pelo provider…


class Provider:
    """Um provider recebe a ModelConfig e faz um pedido com output estruturado por JSON schema."""

    def __init__(self, config):
        self.config = config
        self.params = dict(config.params or {})

    def analyse(self, system: str, user: str, schema: dict) -> LLMResult:
        raise NotImplementedError


def parse_json(text: str) -> object:
    """Lê o JSON da resposta. Tolera blocos ```json e texto antes/depois (modelos locais às vezes fazem isso)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
