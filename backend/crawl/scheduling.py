"""Cadência das revisitas (função pura + helper que lê a BD).

Regras (docs/features/versoes.md), todos os valores são parâmetros:
- tema quente (temperatura >= topics.hot_threshold): revisit.min_interval_h;
- a arrefecer: interpolado entre o mínimo e revisit.max_interval_h;
- tema frio (< topics.cold_threshold): as revisitas param;
- sem tema: revisit.no_topic_interval_h até revisit.no_topic_max_age_h;
- sempre: uma revisita tardia a published_at + revisit.late_days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from core import parameters


@dataclass
class Cadence:
    next_at: datetime | None
    reason: str


def compute(
    *,
    now: datetime,
    published_at: datetime | None,
    temperature: float | None,
    late_done: bool,
    p: dict,
) -> Cadence:
    ref = published_at or now
    late_at = ref + timedelta(days=p["revisit.late_days"])
    interval_h: float | None
    if temperature is not None:
        hot, cold = p["topics.hot_threshold"], p["topics.cold_threshold"]
        lo, hi = p["revisit.min_interval_h"], p["revisit.max_interval_h"]
        if temperature >= hot:
            interval_h, why = lo, f"tema quente ({temperature:.2f})"
        elif temperature < cold:
            interval_h, why = None, f"tema frio ({temperature:.2f})"
        else:
            frac = (hot - temperature) / (hot - cold) if hot > cold else 1.0
            interval_h, why = lo + frac * (hi - lo), f"tema a arrefecer ({temperature:.2f})"
    else:
        if now - ref < timedelta(hours=p["revisit.no_topic_max_age_h"]):
            interval_h, why = p["revisit.no_topic_interval_h"], "sem tema"
        else:
            interval_h, why = None, "sem tema, fora da janela"

    candidate = now + timedelta(hours=interval_h) if interval_h is not None else None
    if not late_done and late_at > now:
        if candidate is None or late_at <= candidate:
            return Cadence(late_at, f"revisita tardia ({p['revisit.late_days']}d); {why}")
    if candidate is None and not late_done and late_at <= now:
        return Cadence(now, "revisita tardia em atraso")
    if candidate is None:
        return Cadence(None, f"sem revisitas: {why}")
    return Cadence(candidate, f"{why}: {interval_h:.1f}h")


PARAM_KEYS = (
    "revisit.late_days", "topics.hot_threshold", "topics.cold_threshold", "revisit.min_interval_h",
    "revisit.max_interval_h", "revisit.no_topic_max_age_h", "revisit.no_topic_interval_h",
)


def load_params() -> dict:
    return {k: float(parameters.get(k)) for k in PARAM_KEYS}


def hottest_topic(article):
    """(Topic, temperatura) do tema mais quente da última análise feita, ou (None, None)."""
    from topics.models import ArticleTopic

    links = (
        ArticleTopic.objects.filter(analysis__version__article=article, analysis__status="done")
        .select_related("topic", "topic__merged_into", "analysis")
        .order_by("-analysis__version__number", "-analysis__created_at")
    )
    best = None
    latest_analysis = None
    for link in links:
        if latest_analysis is None:
            latest_analysis = link.analysis_id
        if link.analysis_id != latest_analysis:
            break
        topic = link.topic.merged_into or link.topic
        if best is None or topic.temperature > best.temperature:
            best = topic
    return (best, best.temperature) if best else (None, None)


def reschedule(article, now: datetime) -> Cadence:
    """Recalcula e grava next_revisit_at (não guarda o artigo: o caller faz save)."""
    if article.status != "active":
        article.next_revisit_at, article.revisit_reason = None, f"sem revisitas: {article.status}"
        return Cadence(None, article.revisit_reason)
    topic, temp = hottest_topic(article)
    cad = compute(now=now, published_at=article.published_at, temperature=temp,
                  late_done=article.late_revisit_done, p=load_params())
    article.next_revisit_at, article.revisit_reason, article.revisit_topic = cad.next_at, cad.reason, topic
    return cad
