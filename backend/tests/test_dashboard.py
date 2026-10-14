"""Dashboard de fiabilidade do crawl: só staff, renderiza e consome o crawl-health por sessão."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    """A LocMemCache sobrevive entre testes no mesmo processo: limpa (stats, crawl-health, parâmetros)."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def test_dashboard_exige_staff(seeded):
    c = Client()
    r = c.get("/dashboard/crawl/")
    assert r.status_code == 302 and "/admin/login/" in r["Location"]
    u = get_user_model().objects.create_user("normal", password="x")
    c.force_login(u)
    assert c.get("/dashboard/crawl/").status_code == 302


def test_dashboard_renderiza_para_staff(seeded):
    u = get_user_model().objects.create_user("staff", password="x", is_staff=True)
    c = Client()
    c.force_login(u)
    r = c.get("/dashboard/crawl/")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Fiabilidade do crawl" in html
    assert "/api/stats/crawl-health/" in html
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/" in html
    assert 'value="jn"' in html
    # A sessão serve também para a API que a página consome
    assert c.get("/api/stats/crawl-health/").status_code == 200
    assert c.get("/api/failures/?limit=20").status_code == 200


def test_admin_tem_link_para_o_dashboard(seeded):
    u = get_user_model().objects.create_superuser("admin", password="x")
    c = Client()
    c.force_login(u)
    r = c.get("/admin/")
    assert r.status_code == 200
    assert "/dashboard/crawl/" in r.content.decode()


@pytest.mark.parametrize("path", [
    "core/parameter", "core/actor", "core/auditlog", "core/idempotencykey",
    "sources/site", "sources/entrypoint", "sources/discoveryrun",
    "crawl/article", "crawl/fetch", "crawl/version", "crawl/homepageappearance", "crawl/technicalfailure",
])
def test_admin_changelists(seeded, path):
    u = get_user_model().objects.create_superuser("admin", password="x")
    c = Client()
    c.force_login(u)
    assert c.get(f"/admin/{path}/").status_code == 200


def test_admin_correr_agora(seeded):
    from unittest import mock

    from sources.models import EntryPoint

    u = get_user_model().objects.create_superuser("admin", password="x")
    c = Client()
    c.force_login(u)
    ep = EntryPoint.objects.first()
    with mock.patch("sources.tasks.discover_entrypoint.apply_async") as m:
        r = c.post("/admin/sources/entrypoint/", {"action": "run_now", "_selected_action": [ep.pk]})
    assert r.status_code == 302
    m.assert_called_once_with(args=[ep.pk], queue="discovery")


@pytest.mark.django_db
def test_article_page_renders_analysis(client, seeded):
    from django.contrib.auth.models import User

    from analysis.models import Analysis
    from crawl.models import Article, Fetch, Version
    from entities.models import ArticleEntity, Entity
    from sources.models import Site

    staff = User.objects.create_user("staff2", password="x", is_staff=True)
    client.force_login(staff)
    a = Article.objects.create(site=Site.objects.get(slug="jn"), canonical_url="https://www.jn.pt/a/1",
                               title="Título <b>limpo</b>", status="active")
    f = Fetch.objects.create(article=a, url=a.canonical_url, reason="new", outcome="ok", http_status=200)
    v = Version.objects.create(article=a, number=1, fetch=f, content={"title": "T", "body": [{"kind": "p", "text": "Corpo."}]},
                               content_hash="h", text="T")
    an = Analysis.objects.create(version=v, status="done", provider="fake", model="m", piece_type="noticia",
                                 ai_indicator={"score": 12, "signals": []})
    ent = Entity.objects.create(canonical_name="André Ventura", type="pessoa")
    ArticleEntity.objects.create(analysis=an, entity=ent, name_in_text="Ventura", roles=["citado"], sentiment="negativo")
    r = client.get(f"/dashboard/articles/{a.pk}/")
    assert r.status_code == 200
    html = r.content.decode()
    assert "André Ventura" in html and "negativo" in html and "12%" in html and "Corpo." in html


@pytest.mark.django_db
def test_analysis_queue_page(client, seeded, monkeypatch):
    from django.contrib.auth.models import User

    monkeypatch.setattr("redis.Redis.llen", lambda self, q: 7)
    client.force_login(User.objects.create_user("staff3", password="x", is_staff=True))
    r = client.get("/dashboard/analysis/")
    assert r.status_code == 200
    assert "Fila de análises" in r.content.decode()
