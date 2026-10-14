"""Prompt da análise de produção.

Usa o system prompt, o template do pedido e o schema do benchmark (benchmark/bench/), para os resultados do
benchmark se transferirem. A única adaptação: a "taxonomia" do prompt deixa de ser o ficheiro estático
(themes_seed.json) e passa a ser a lista dos temas da BD mais quentes (`analysis.topic_candidates`), cada um com
o caminho completo (path) e a recorrência, no mesmo formato. O LLM responde com `path` + `is_new`, e o match
com a BD faz-se pelo caminho (topics/resolve.py).
"""

from __future__ import annotations

from types import SimpleNamespace

from benchmark.bench.prompt import SYSTEM_PROMPT_V1, USER_TEMPLATE_V1, render_system, render_user
from benchmark.bench.schema import OUTPUT_SCHEMA_V1, validate
from core import parameters

PROMPT_VERSION = "prod-v1+bench-v1"
OUTPUT_SCHEMA = OUTPUT_SCHEMA_V1
BLOCK_PREFIX = {"h2": "## ", "h3": "### ", "li": "- ", "quote": "> "}

__all__ = ["PROMPT_VERSION", "OUTPUT_SCHEMA", "build", "topic_candidates", "validate"]


def body_text(blocks: list[dict]) -> str:
    """Mesmo formato do bench_import_articles: um bloco por parágrafo, com prefixo nos títulos/listas/citações."""
    return "\n\n".join(f"{BLOCK_PREFIX.get(b.get('kind'), '')}{(b.get('text') or '').strip()}"
                       for b in blocks or [] if b.get("text"))


def topic_candidates(limit: int | None = None) -> list[dict]:
    """Temas não fundidos (activos e por rever), mais quentes primeiro. Devolve [{id, path, recurrence}].

    A selecção é pela temperatura; a lista vai ordenada pelo caminho, para o system prompt mudar pouco entre
    pedidos (cache do prompt no provider).
    """
    from topics.models import Topic

    limit = int(limit if limit is not None else parameters.get("analysis.topic_candidates"))
    topics = list(Topic.objects.exclude(status="merged").order_by("-temperature", "name")[:limit])
    out = [{"id": t.pk, "path": topic_path(t), "recurrence": t.recurrence} for t in topics]
    return sorted(out, key=lambda c: [p.lower() for p in c["path"]])


def topic_path(topic) -> list[str]:
    path, node, seen = [], topic, set()
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        path.append(node.name)
        node = node.parent
    return list(reversed(path))


def build(version, candidates: list[dict]) -> tuple[str, str, dict]:
    """(system, user, info) para uma versão. `info` vai para o debug (truncagem, candidatos)."""
    content = version.content or {}
    article = version.article
    max_chars = int(parameters.get("analysis.max_chars"))
    body = body_text(content.get("body"))
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars].rsplit(" ", 1)[0] + " […]"
    authors = ", ".join(a.get("name", "") for a in content.get("authors") or [])
    published = content.get("published_at") or (article.published_at.isoformat() if article.published_at else None)
    view = SimpleNamespace(
        site=article.site.slug,
        section=" / ".join(x for x in (content.get("section"), content.get("subsection")) if x),
        piece_type_site=content.get("piece_type") or "",
        published_at=_Iso(published),
        byline=content.get("byline_raw") or authors,
        tags=content.get("tags") or [],
        title=content.get("title") or article.title or "",
        lead=content.get("lead") or "",
        body=body,
    )
    prompt = SimpleNamespace(system_prompt=SYSTEM_PROMPT_V1, user_template=USER_TEMPLATE_V1,
                             taxonomy=[{"path": c["path"], "recurrence": c["recurrence"]} for c in candidates])
    system = render_system(prompt)
    if not candidates:
        system += "(sem temas na base de dados: propõe temas novos com is_new=true)\n"
    user = render_user(prompt, view)
    return system, user, {"truncated": truncated, "body_chars": len(body), "max_chars": max_chars}


class _Iso:
    """render_user chama .isoformat(); aqui a data já vem em ISO (texto) do parser."""

    def __init__(self, value):
        self.value = value

    def __bool__(self):
        return bool(self.value)

    def isoformat(self):
        return self.value
