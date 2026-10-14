"""Descoberta + leitura com HTTP simulado (respx). Nenhum pedido real."""

from datetime import timedelta
from unittest import mock

import httpx
import pytest
import respx
from django.utils import timezone

from crawl.models import Article, ArticleURL, Fetch, TechnicalFailure, Version
from sources.models import EntryPoint, Site
from tests.conftest import fixture_text

pytestmark = pytest.mark.django_db

JN_URL = "https://www.jn.pt/pais/artigo/x/18136568"


@pytest.fixture
def no_enqueue():
    with mock.patch("crawl.tasks.fetch_article.apply_async") as f, \
         mock.patch("analysis.tasks.analyze_version.apply_async") as a, \
         mock.patch("duplicates.tasks.detect_duplicates.apply_async") as d:
        yield {"fetch": f, "analysis": a, "dup": d}


def _no_age_limit():
    """As amostras são de 2026-10-13: sem o filtro de idade da descoberta."""
    from core.models import Parameter

    Parameter.objects.filter(key="discovery.max_item_age_h").update(value=10_000_000)


JN_ANY = r"https://www\.jn\.pt/.*/18136568$"


def _jn_article():
    site = Site.objects.get(slug="jn")
    a = Article.objects.create(site=site, site_article_id="18136568", canonical_url=JN_URL,
                               published_at=timezone.now())
    ArticleURL.objects.create(article=a, url=JN_URL)
    return a


def _fetch(article, reason="new"):
    from crawl.tasks import fetch_article

    return fetch_article.apply(args=[article.pk, reason]).get()


@respx.mock
def test_jn_news_sitemap_discovery(seeded, no_enqueue, django_capture_on_commit_callbacks):
    ep = EntryPoint.objects.get(site__slug="jn", name="news-sitemap")
    respx.get(ep.url).mock(return_value=httpx.Response(200, text=fixture_text("jn_sitemap_news.xml")))
    from sources.discovery import run_entrypoint

    _no_age_limit()
    with django_capture_on_commit_callbacks(execute=True):
        run = run_entrypoint(ep)
    assert run.ok, run.error
    assert run.new > 10
    assert Article.objects.filter(site__slug="jn").count() == run.new
    assert no_enqueue["fetch"].call_count == run.new
    # Segunda execução: nada novo.
    run2 = run_entrypoint(ep)
    assert run2.new == 0 and run2.updated == run.new


@respx.mock
def test_old_items_are_skipped(seeded, no_enqueue):
    ep = EntryPoint.objects.get(site__slug="jn", name="news-sitemap")
    respx.get(ep.url).mock(return_value=httpx.Response(200, text=fixture_text("jn_sitemap_news.xml")))
    from sources.discovery import run_entrypoint

    run = run_entrypoint(ep)   # amostra de 2026-10-13; filtro de 24h
    assert run.found > 0
    assert run.new + run.skipped_old + run.excluded == run.found


@respx.mock
def test_jn_homepage_premium_not_fetched(seeded, no_enqueue):
    ep = EntryPoint.objects.get(site__slug="jn", name="homepage")
    respx.get(ep.url).mock(return_value=httpx.Response(200, text=fixture_text("jn_homrpage.html")))
    from sources.discovery import run_entrypoint

    _no_age_limit()
    run = run_entrypoint(ep)
    assert run.ok, run.error
    premium = Article.objects.filter(site__slug="jn", out_of_scope_reason="premium_sem_texto_integral")
    assert premium.exists()
    assert not Fetch.objects.exists()


@respx.mock
def test_fetch_creates_version_then_unchanged(seeded, no_enqueue, django_capture_on_commit_callbacks):
    a = _jn_article()
    respx.get(url__regex=JN_ANY).mock(return_value=httpx.Response(200, text=fixture_text("jn_article_18136568.html")))
    with django_capture_on_commit_callbacks(execute=True):
        r = _fetch(a)
    assert r["outcome"] == "ok"
    a.refresh_from_db()
    assert a.status == "active" and a.version_count == 1 and a.title
    assert a.next_revisit_at is not None
    v = Version.objects.get(article=a)
    assert v.word_count > 50 and v.text
    assert Fetch.objects.get().quality_ok is True
    assert no_enqueue["analysis"].called and no_enqueue["dup"].called
    r2 = _fetch(a, "revisit")
    assert r2["outcome"] == "unchanged"
    assert Version.objects.filter(article=a).count() == 1


@respx.mock
def test_changed_content_creates_new_version(seeded, no_enqueue):
    a = _jn_article()
    html = fixture_text("jn_article_18136568.html")
    route = respx.get(url__regex=JN_ANY)
    route.mock(return_value=httpx.Response(200, text=html))
    _fetch(a)
    # Correcção editorial no corpo (o caso real BE/MAI: "acima" vs "abaixo" do valor previsto na lei).
    route.mock(return_value=httpx.Response(200, text=html.replace("acima", "abaixo")))
    assert _fetch(a, "revisit")["outcome"] == "ok"
    v2 = Version.objects.get(article=a, number=2)
    assert "body" in v2.diff and 0 < v2.change_ratio < 0.2


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
def test_gone_is_deleted(seeded, no_enqueue, status):
    a = _jn_article()
    respx.get(JN_URL).mock(return_value=httpx.Response(status))
    assert _fetch(a)["outcome"] == "deleted"
    a.refresh_from_db()
    assert a.status == "deleted" and a.next_revisit_at is None
    assert not TechnicalFailure.objects.exists()


@respx.mock
def test_redirect_to_homepage_is_deleted(seeded, no_enqueue):
    a = _jn_article()
    respx.get(JN_URL).mock(return_value=httpx.Response(301, headers={"location": "https://www.jn.pt/"}))
    respx.get("https://www.jn.pt/").mock(return_value=httpx.Response(200, text="<html></html>"))
    assert _fetch(a)["outcome"] == "deleted"
    a.refresh_from_db()
    assert a.deleted_reason.startswith("redirect_301")


@respx.mock
def test_permanent_redirect_to_article_adds_url(seeded, no_enqueue):
    a = _jn_article()
    new = "https://www.jn.pt/pais/artigo/novo-titulo/18136568"
    respx.get(JN_URL).mock(return_value=httpx.Response(301, headers={"location": new}))
    respx.get(new).mock(return_value=httpx.Response(200, text=fixture_text("jn_article_18136568.html")))
    assert _fetch(a)["outcome"] == "ok"
    assert ArticleURL.objects.filter(article=a, url=new, kind="redirect").exists()


@respx.mock
def test_429_is_technical_failure_with_backoff(seeded, no_enqueue):
    a = _jn_article()
    respx.get(JN_URL).mock(return_value=httpx.Response(429))
    assert _fetch(a)["outcome"] == "technical_failure"
    f = TechnicalFailure.objects.get()
    assert f.kind == "http_429" and f.status == "open" and f.next_retry_at > timezone.now()
    _fetch(a, "retry")
    f.refresh_from_db()
    assert f.attempts == 2


@respx.mock
def test_timeout_then_success_resolves_failure(seeded, no_enqueue):
    a = _jn_article()
    route = respx.get(JN_URL)
    route.mock(side_effect=httpx.ConnectTimeout("lento"))
    _fetch(a)
    assert TechnicalFailure.objects.get().kind == "timeout"
    route.mock(return_value=httpx.Response(200, text=fixture_text("jn_article_18136568.html")))
    _fetch(a, "retry")
    assert TechnicalFailure.objects.get().status == "resolved"


@respx.mock
def test_premium_cut_article_is_out_of_scope(seeded, no_enqueue):
    a = _jn_article()
    respx.get(JN_URL).mock(return_value=httpx.Response(200, text=fixture_text("jn_article_18135966_premium.html")))
    assert _fetch(a)["outcome"] == "out_of_scope"
    a.refresh_from_db()
    assert a.status == "out_of_scope" and not a.versions.exists()


def test_sweep_revisits_enqueues_due(seeded, no_enqueue):
    a = _jn_article()
    Article.objects.filter(pk=a.pk).update(status="active", next_revisit_at=timezone.now() - timedelta(minutes=1))
    from crawl.tasks import sweep_revisits

    assert sweep_revisits() == 1
    a.refresh_from_db()
    assert a.next_revisit_at is None
    args = no_enqueue["fetch"].call_args
    assert args.kwargs["queue"] == "revisits" and args.kwargs["args"][1] == "revisit"


def test_tick_discovery_advances_next_run(seeded):
    from sources.tasks import discover_entrypoint, tick_discovery

    with mock.patch.object(discover_entrypoint, "apply_async") as m:
        n = tick_discovery()
        assert n == EntryPoint.objects.filter(active=True).count() and m.call_count == n
        assert tick_discovery() == 0
