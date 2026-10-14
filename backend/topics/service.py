"""Temperatura dos temas e das edições.

temperatura = Σ peso × 0,5^(idade_h / topics.half_life_h) × (1 + topics.media_weight × (nº de sites − 1))

- Σ sobre as ligações notícia↔tema da **última análise feita de cada notícia** (as versões antigas não contam),
  das notícias com data (published_at, ou first_seen_at se não houver) dentro de `topics.window_h`.
- idade_h: horas desde essa data.
- Sem roll-up: cada tema conta só as notícias ligadas **directamente** a ele. Os pais não somam os filhos
  ("Política" não fica sempre quente); um pai só aquece se o LLM ligar a notícia ao próprio pai (assunto geral).
  Na prática a temperatura vive nas folhas e nas edições, como pede docs/features/temas.md.
- Temas fundidos: as ligações contam para o tema final (`merged_into`) e o fundido fica a 0.
- Histórico (`TopicTemperature`) só quando o valor é > 0 ou acabou de passar a 0 (evita linhas vazias a cada 15 min).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from analysis.models import Analysis
from core import parameters
from topics.models import ArticleTopic, Edition, Topic, TopicTemperature
from topics.resolve import final_topic


def temperature(items: list[tuple[float, float]], n_sites: int, half_life_h: float, media_weight: float) -> float:
    """items = [(peso, idade_h)]. Função pura (testável)."""
    if not items:
        return 0.0
    base = sum(w * 0.5 ** (max(0.0, age) / half_life_h) for w, age in items)
    return base * (1 + media_weight * max(0, n_sites - 1))


def latest_done_analyses(since: datetime):
    """IDs da última análise feita de cada notícia com data de referência >= since."""
    latest = (Analysis.objects.filter(version__article_id=OuterRef("version__article_id"), status="done")
              .order_by("-version__number", "-finished_at").values("pk")[:1])
    qs = Analysis.objects.filter(status="done").filter(pk=Subquery(latest))
    return qs.filter(Q(version__article__published_at__gte=since)
                     | Q(version__article__published_at__isnull=True, version__article__first_seen_at__gte=since))


def recompute_all(now: datetime | None = None) -> int:
    now = now or timezone.now()
    window_h = float(parameters.get("topics.window_h"))
    half_life = float(parameters.get("topics.half_life_h"))
    media_weight = float(parameters.get("topics.media_weight"))
    since = now - timedelta(hours=window_h)

    analyses = latest_done_analyses(since)
    links = (ArticleTopic.objects.filter(analysis__in=analyses)
             .select_related("topic", "topic__merged_into", "analysis__version__article"))

    per_topic: dict[int, dict] = defaultdict(lambda: {"items": [], "articles": set(), "sites": set()})
    per_edition: dict[int, dict] = defaultdict(lambda: {"items": [], "articles": set(), "sites": set()})
    for link in links:
        art = link.analysis.version.article
        ref = art.published_at or art.first_seen_at or now
        age_h = (now - ref).total_seconds() / 3600
        topic = final_topic(link.topic)
        for bucket in (per_topic[topic.pk], per_edition[link.edition_id] if link.edition_id else None):
            if bucket is None:
                continue
            if art.pk in bucket["articles"]:
                continue   # a mesma notícia ligada duas vezes ao tema (edições diferentes): conta uma vez
            bucket["items"].append((link.weight, age_h))
            bucket["articles"].add(art.pk)
            bucket["sites"].add(art.site_id)

    history, topics = [], []
    for topic in Topic.objects.all().only("pk", "temperature", "temperature_at", "status"):
        data = per_topic.get(topic.pk) if topic.status != "merged" else None
        value = round(temperature(data["items"], len(data["sites"]), half_life, media_weight), 6) if data else 0.0
        if value > 0 or topic.temperature > 0:
            history.append(TopicTemperature(topic_id=topic.pk, at=now, value=value,
                                            articles=len(data["articles"]) if data else 0,
                                            sites=len(data["sites"]) if data else 0))
        topic.temperature, topic.temperature_at = value, now
        topics.append(topic)
    Topic.objects.bulk_update(topics, ["temperature", "temperature_at"], batch_size=500)
    TopicTemperature.objects.bulk_create(history)

    for ed in Edition.objects.all().only("pk", "temperature"):
        data = per_edition.get(ed.pk)
        value = round(temperature(data["items"], len(data["sites"]), half_life, media_weight), 6) if data else 0.0
        if value != ed.temperature:
            Edition.objects.filter(pk=ed.pk).update(temperature=value)
    return len(topics)
