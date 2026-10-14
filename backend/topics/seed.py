"""Taxonomia semente dos temas: a mesma do benchmark (benchmark/fixtures/themes_seed.json), como temas activos.

Idempotente: cria o que falta pelo caminho (topics/resolve.py), nunca altera o que existe.
"""

from __future__ import annotations

from benchmark.bench.prompt import load_taxonomy
from topics.models import Topic
from topics.resolve import resolve_path


def ensure_taxonomy(taxonomy: list[dict] | None = None) -> int:
    created = 0
    for item in taxonomy if taxonomy is not None else load_taxonomy():
        topic, was_created, dbg = resolve_path(item["path"], "tema", allow_elsewhere=False)
        new_ids = [s["topic_id"] for s in dbg["steps"] if s.get("match") == "criado por rever"]
        if new_ids:
            Topic.objects.filter(pk__in=new_ids).update(status="active", debug={"criado_por": "seed da taxonomia"})
            created += len(new_ids)
        recurrence = item.get("recurrence") or "nenhuma"
        if topic.recurrence != recurrence and topic.pk in new_ids:
            Topic.objects.filter(pk=topic.pk).update(recurrence=recurrence)
    return created
