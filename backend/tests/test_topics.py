"""Temperatura dos temas, match de caminhos e taxonomia semente."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from analysis import service
from analysis.models import Analysis
from tests.test_analysis import JN, OBS, base_output, fake, make_version, set_param, theme  # noqa: F401
from topics import service as tservice
from topics.models import ArticleTopic, Edition, Topic, TopicTemperature
from topics.resolve import resolve_path

pytestmark = pytest.mark.django_db


def test_temperature_formula():
    assert tservice.temperature([], 3, 24, 0.5) == 0.0
    assert tservice.temperature([(1.0, 0)], 1, 24, 0.5) == 1.0
    assert tservice.temperature([(1.0, 24)], 1, 24, 0.5) == pytest.approx(0.5)
    # 2 notícias, 2 sites: (1 + 0,5·0,25) × (1 + 0,5 × 1)
    assert tservice.temperature([(1.0, 0), (0.5, 48)], 2, 24, 0.5) == pytest.approx((1 + 0.125) * 1.5)
    assert tservice.temperature([(1.0, -5)], 1, 24, 0.5) == 1.0   # data no futuro não aquece mais


def test_recompute_all(fake):
    now = timezone.now()
    fake.output = base_output(themes=[theme(["Política", "Governo"], weight=1.0, edition="Governo 2026"),
                                      theme(["Política"], weight=0.5)])
    v1 = make_version(*OBS, published_at=now - timedelta(hours=24))
    service.analyze(v1.pk)
    fake.output = base_output(themes=[theme(["Política", "Governo"], weight=0.5)])
    v2 = make_version(*JN, published_at=now)
    service.analyze(v2.pk)
    # Notícia fora da janela não conta.
    fake.output = base_output(themes=[theme(["Política", "Governo"], weight=1.0)])
    v3 = make_version(*JN, published_at=now - timedelta(hours=100))
    service.analyze(v3.pk)

    assert tservice.recompute_all(now=now) == Topic.objects.count()
    gov = Topic.objects.get(name="Governo")
    expected = (1.0 * 0.5 + 0.5 * 1.0) * (1 + 0.5 * 1)    # 2 sites
    assert gov.temperature == pytest.approx(expected, rel=1e-4)
    # O pai não soma os filhos: só a ligação directa (peso 0,5, 24 h, 1 site).
    assert Topic.objects.get(name="Política").temperature == pytest.approx(0.25, rel=1e-4)
    h = TopicTemperature.objects.get(topic=gov)
    assert (h.articles, h.sites) == (2, 2)
    assert Edition.objects.get(label="Governo 2026").temperature == pytest.approx(0.5, rel=1e-4)


def test_only_latest_analysis_per_article_counts(fake):
    now = timezone.now()
    fake.output = base_output(themes=[theme(["Desporto"], weight=1.0)])
    v1 = make_version(*OBS, published_at=now)
    service.analyze(v1.pk)
    fake.output = base_output(themes=[theme(["Cultura"], weight=1.0)])
    v2 = make_version("observador", "", article=v1.article, content={**v1.content, "title": "Outro título"})
    service.analyze(v2.pk)
    tservice.recompute_all(now=now)
    assert Topic.objects.get(name="Desporto").temperature == 0.0
    assert Topic.objects.get(name="Cultura").temperature == pytest.approx(1.0)


def test_merged_topic_migrates_temperature(fake):
    now = timezone.now()
    fake.output = base_output(themes=[theme(["OE2026"], weight=1.0)])
    service.analyze(make_version(*OBS, published_at=now).pk)
    old = Topic.objects.get(name="OE2026")
    target = Topic.objects.create(name="Orçamento do Estado 2026", slug="oe-2026", status="active")
    old.status, old.merged_into = "merged", target
    old.save()
    tservice.recompute_all(now=now)
    old.refresh_from_db()
    target.refresh_from_db()
    assert old.temperature == 0.0 and target.temperature == pytest.approx(1.0)


def test_resolve_path_matching(db):
    pol = Topic.objects.create(name="Política", slug="politica", status="active")
    gov = Topic.objects.create(name="Governo", slug="politica-governo", parent=pol, status="active")
    irs = Topic.objects.create(name="IRS Jovem", slug="irs-jovem", parent=gov, status="active")

    t, created, dbg = resolve_path(["politica", "GOVERNO"], "tema")     # sem acentos / maiúsculas
    assert t == gov and not created
    t, created, dbg = resolve_path(["Economia", "IRS Jovem"], "tema")  # folha noutro ramo
    assert t == irs and not created and dbg["steps"][-1]["match"] == "folha noutro ramo"
    t, created, _ = resolve_path(["Política", "Governo", "Remodelação"], "evento", analysis_id=7)
    assert created and t.status == "por_rever" and t.kind == "evento" and t.parent == gov
    assert t.slug == "politica-governo-remodelacao"


def test_seed_taxonomy_idempotent(db):
    from topics.seed import ensure_taxonomy

    n = ensure_taxonomy()
    assert n == Topic.objects.count() and n > 10
    assert ensure_taxonomy() == 0
    assert not Topic.objects.exclude(status="active").exists()
    assert Topic.objects.get(name="Orçamento do Estado").recurrence == "anual"
