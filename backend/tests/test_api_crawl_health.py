"""/api/stats/crawl-health/: séries por site e período e estado ok | warn | alert, com Fetch sintéticos."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from crawl.models import Article, Fetch
from sources.models import DiscoveryRun, EntryPoint, Site

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    """A LocMemCache sobrevive entre testes no mesmo processo: limpa (stats, crawl-health, parâmetros)."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()

GOOD_Q = {"ok": True, "errors": [], "warnings": ["images:no_credit"]}
BAD_Q = {"ok": False, "errors": ["missing:published_at", "body:empty"], "warnings": []}


@pytest.fixture
def api(seeded):
    u = get_user_model().objects.create_user("agente")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")
    return c


def hour_start(hours_ago: int):
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    return now - timedelta(hours=hours_ago) + timedelta(minutes=1)


def add_fetches(site_slug: str, at, total: int, ok: int, quality_ok: int | None = None):
    """`ok` leituras bem-sucedidas (das quais `quality_ok` com qualidade) e o resto falhas técnicas."""
    site = Site.objects.get(slug=site_slug)
    a, _ = Article.objects.get_or_create(site=site, canonical_url=f"{site.base_url}x", defaults={"status": "active"})
    quality_ok = ok if quality_ok is None else quality_ok
    rows = []
    for i in range(total):
        if i < ok:
            q = GOOD_Q if i < quality_ok else BAD_Q
            rows.append(Fetch(article=a, url=a.canonical_url, reason="revisit", outcome="ok",
                              quality=q, quality_ok=q["ok"]))
        else:
            rows.append(Fetch(article=a, url=a.canonical_url, reason="revisit", outcome="technical_failure"))
    ids = [f.pk for f in Fetch.objects.bulk_create(rows)]
    Fetch.objects.filter(pk__in=ids).update(requested_at=at)


def add_runs(site_slug: str, ep_name: str, at, found: int, n: int = 2, ok: bool = True):
    ep = EntryPoint.objects.get(site__slug=site_slug, name=ep_name)
    ids = [DiscoveryRun.objects.create(entrypoint=ep, ok=ok, found=found).pk for _ in range(n)]
    DiscoveryRun.objects.filter(pk__in=ids).update(started_at=at)


def site_of(data, slug):
    return next(s for s in data["sites"] if s["site"] == slug)


def test_crawl_health_alerta_quando_sucesso_cai(api):
    # JN: 95% durante 7 horas e 50% na última → alerta (limiar e queda face à média móvel)
    for h in range(7, 0, -1):
        add_fetches("jn", hour_start(h), total=20, ok=19)
    add_fetches("jn", hour_start(0), total=20, ok=10)
    # Público: estável a 100%
    for h in range(7, -1, -1):
        add_fetches("publico", hour_start(h), total=10, ok=10)

    r = api.get("/api/stats/crawl-health/?bucket=hour")
    assert r.status_code == 200, r.content
    d = r.json()
    assert d["bucket"] == "hour" and d["status"] == "alert"

    jn = site_of(d, "jn")
    assert jn["status"] == "alert"
    codes = {x["code"] for x in jn["reasons"]}
    assert {"success_rate", "success_rate_drop"} <= codes
    assert jn["latest"]["success_rate"] == 0.5
    assert jn["latest"]["success_rate_avg"] == 0.95
    assert len(jn["series"]) == 8
    assert jn["series"][0]["success_rate"] == 0.95 and jn["series"][0]["technical_failures"] == 1
    assert jn["totals"]["fetch_total"] == 160

    pub = site_of(d, "publico")
    assert pub["status"] == "ok" and pub["reasons"] == []
    assert pub["latest"]["quality_ok_rate"] == 1.0

    # Sem dados suficientes → aviso
    assert site_of(d, "observador")["status"] == "warn"


def test_crawl_health_aviso_e_campos_que_falham(api):
    for h in range(3, -1, -1):
        add_fetches("jn", hour_start(h), total=10, ok=10, quality_ok=8)   # qualidade 80% < 90% → aviso
    d = api.get("/api/stats/crawl-health/?site=jn").json()
    assert [s["site"] for s in d["sites"]] == ["jn"]
    jn = d["sites"][0]
    assert jn["status"] == "warn"
    assert [x["code"] for x in jn["reasons"]] == ["quality_ok_rate"]
    top = {(q["kind"], q["code"]): q for q in jn["top_quality_fields"]}
    assert top[("error", "missing:published_at")]["count"] == 8
    assert top[("error", "body:empty")]["rate"] == 0.2
    assert top[("warning", "images:no_credit")]["count"] == 32


def test_crawl_health_queda_na_descoberta(api):
    for h in range(7, -1, -1):
        add_fetches("jn", hour_start(h), total=10, ok=10)
    for h in range(7, 0, -1):
        add_runs("jn", "news-sitemap", hour_start(h), found=100)
    add_runs("jn", "news-sitemap", hour_start(0), found=10)
    jn = api.get("/api/stats/crawl-health/?site=jn").json()["sites"][0]
    assert jn["status"] == "alert", (jn["reasons"], jn["discovery_by_entrypoint"])
    drop = next(x for x in jn["reasons"] if x["code"] == "discovery_drop")
    assert drop["entrypoint"] == "news-sitemap" and drop["moving_avg"] == 100
    assert jn["series"][-1]["discovery_found_avg"] == 10
    assert jn["series"][-1]["discovery_runs"] == 2


def test_crawl_health_bucket_dia_e_validacao(api):
    for d in range(3):
        add_fetches("publico", timezone.now() - timedelta(days=d), total=10, ok=10)
    r = api.get("/api/stats/crawl-health/?bucket=day&since=7d&site=publico")
    assert r.status_code == 200
    assert len(r.json()["sites"][0]["series"]) == 3
    assert api.get("/api/stats/crawl-health/?bucket=semana").status_code == 400
    assert api.get("/api/stats/crawl-health/?since=ontem").status_code == 400
    assert api.get("/api/stats/crawl-health/?site=nao-existe").status_code == 400
    assert APIClient().get("/api/stats/crawl-health/").status_code == 401
