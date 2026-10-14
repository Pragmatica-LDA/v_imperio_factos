"""Providers de LLM da análise de produção.

Reaproveita os providers do benchmark (benchmark/llm/) para os resultados do benchmark se transferirem para
produção. Acrescenta o provider `fake` (llm.provider = "fake"): resposta determinística e válida no schema,
para testes e para correr o pipeline sem custos.
"""

from __future__ import annotations

import json
import re
import time
from types import SimpleNamespace

from benchmark.llm import LLMResult, Provider, ProviderError, get_provider as bench_get_provider, parse_json
from core import parameters

__all__ = ["LLMResult", "ProviderError", "parse_json", "load_config", "get_provider", "FakeProvider"]


def load_config() -> SimpleNamespace:
    """Config no formato da ModelConfig do benchmark (provider, model_id, base_url, params), a partir dos parâmetros."""
    provider = str(parameters.get("llm.provider"))
    params = {"max_tokens": int(parameters.get("llm.max_output_tokens"))}
    params.update(parameters.get("llm.params") or {})
    # Os modelos Claude 5.5 recusam `temperature`: só vai para openai/ollama, e só se não vier em llm.params.
    if provider in ("openai", "ollama") and "temperature" not in params:
        params["temperature"] = float(parameters.get("llm.temperature"))
    return SimpleNamespace(provider=provider, model_id=str(parameters.get("llm.model")),
                           base_url=str(parameters.get("llm.base_url") or ""), params=params)


def get_provider(config) -> Provider:
    if config.provider == "fake":
        return FakeProvider(config)
    return bench_get_provider(config)


# --- Provider fake -------------------------------------------------------------------------------------------

_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?: (?:de |da |do |dos |das )?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,3})"
)
_TAXONOMY_RE = re.compile(r"^- (.+?) · (\w+)$", re.M)


def fake_output(system: str, user: str) -> dict:
    """Saída determinística a partir do texto: nomes próprios compostos como pessoas, 1.º tema da taxonomia.

    Os testes substituem esta função (monkeypatch) quando precisam de uma saída concreta.
    """
    body = user.split("Corpo:", 1)[-1]
    names = list(dict.fromkeys(_NAME_RE.findall(body)))[:5]
    entities = [{
        "name": n, "canonical_name": n, "type": "pessoa", "is_public": True, "roles": ["mencionado"],
        "position_at_date": None, "sentiment": "neutro", "sentiment_reason": "Mencionado sem juízo (fake).",
    } for n in names]
    sources = []
    if "Lusa" in user:
        sources.append({"type": "agencia", "entity_name": "Agência Lusa", "partial_attribute": None,
                        "excerpt": "Lusa"})
    taxonomy = _TAXONOMY_RE.findall(system.split("Taxonomia de temas", 1)[-1])
    if taxonomy:
        themes = [{"path": taxonomy[0][0].split(" > "), "kind": "tema", "edition": None, "weight": 1.0,
                   "is_new": False}]
    else:
        themes = [{"path": ["Geral"], "kind": "tema", "edition": None, "weight": 0.5, "is_new": True}]
    return {
        "piece_type": "noticia",
        "entities": entities,
        "sources": sources,
        "themes": themes,
        "locations": [],
        "ai_indicator": {"score": 0, "signals": []},
        "debug": {"reasoning": "Saída do provider fake (determinística).", "sources_used": ["corpo"],
                  "sources_discarded": []},
    }


class FakeProvider(Provider):
    def analyse(self, system: str, user: str, schema: dict) -> LLMResult:
        started = time.monotonic()
        out = fake_output(system, user)
        text = json.dumps(out, ensure_ascii=False)
        return LLMResult(text=text, tokens_in=len(system + user) // 4, tokens_out=len(text) // 4,
                         latency_ms=int((time.monotonic() - started) * 1000), meta={"fake": True})
