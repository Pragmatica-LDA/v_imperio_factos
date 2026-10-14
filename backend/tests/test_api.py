"""API: autenticação, auditoria, idempotência, fusões, filas (Celery sempre mockado)."""

from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from analysis.models import Analysis, CitedSource
from core import parameters
from core.models import Actor, AuditLog, IdempotencyKey
from crawl.models import Article, Fetch, TechnicalFailure, Version
from entities.models import ArticleEntity, Entity, EntityAlias
from sources.models import EntryPoint, Site
from topics.models import ArticleTopic, Edition, Topic

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    """A LocMemCache sobrevive entre testes no mesmo processo: limpa (stats, crawl-health, parâmetros)."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    u = get_user_model().objects.create_user("agente", password="x")
    Actor.objects.create(user=u, kind="agent")
    return u


@pytest.fixture
def api(user, seeded):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return c


def queued(task_id="t-1"):
    return mock.Mock(return_value=SimpleNamespace(id=task_id))


def make_article(site_slug="jn", title="Uma notícia", n_versions=1):
    site = Site.objects.get(slug=site_slug)
    a = Article.objects.create(site=site, canonical_url=f"https://www.jn.pt/x/{title.replace(' ', '-')}",
                               title=title, status="active")
    versions = []
    for n in range(1, n_versions + 1):
        f = Fetch.objects.create(article=a, url=a.canonical_url, reason="new", outcome="ok", http_status=200)
        versions.append(Version.objects.create(article=a, number=n, fetch=f, content={"title": title},
                                               content_hash=f"h{n}", text=title, word_count=100 * n,
                                               change_ratio=0.1 * (n - 1), diff={"n": n}))
    a.version_count = n_versions
    a.save()
    return a, versions


# Autenticação ---------------------------------------------------------------------------------------------------

def test_token_obrigatorio(seeded):
    r = APIClient().get("/api/sites/")
    assert r.status_code == 401


def test_schema_e_docs_sem_token(seeded):
    assert APIClient().get("/api/schema/").status_code == 200
    assert APIClient().get("/api/docs/").status_code == 200


def test_lista_sites_com_token(api):
    r = api.get("/api/sites/")
    assert r.status_code == 200
    assert {s["slug"] for s in r.json()["results"]} >= {"jn", "observador", "publico"}


# Parâmetros e auditoria -----------------------------------------------------------------------------------------

def test_patch_parametro_audita_e_invalida_cache(api, user):
    assert parameters.get("quality.success_warn") == 0.9   # fica em cache
    r = api.patch("/api/parameters/quality.success_warn/", {"value": 0.85, "reason": "teste"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["value"] == 0.85
    assert parameters.get("quality.success_warn") == 0.85
    log = AuditLog.objects.get(action="update", object_type="core.Parameter")
    assert log.actor == user
    assert log.object_id == "quality.success_warn"
    assert log.before["value"] == 0.9 and log.after["value"] == 0.85
    assert log.extra["reason"] == "teste"


def test_patch_parametro_tipo_errado(api):
    r = api.patch("/api/parameters/failures.max_attempts/", {"value": "cinco"}, format="json")
    assert r.status_code == 400
    r = api.patch("/api/parameters/revisit.on_lastmod_change/", {"value": 1}, format="json")
    assert r.status_code == 400
    r = api.patch("/api/parameters/topics.half_life_h/", {"value": 12.5}, format="json")
    assert r.status_code == 400   # int por omissão: float não passa
    r = api.patch("/api/parameters/llm.temperature/", {"value": 1}, format="json")
    assert r.status_code == 200   # float por omissão: int é aceite


def test_parametros_nao_aceitam_post_nem_delete(api):
    assert api.post("/api/parameters/", {"key": "x", "value": 1}, format="json").status_code == 405
    assert api.delete("/api/parameters/crawl.timeout_s/").status_code == 405


def test_crud_site_audita(api, user):
    r = api.post("/api/sites/", {"slug": "expresso", "name": "Expresso", "base_url": "https://expresso.pt/",
                                 "parser_module": "expresso"}, format="json")
    assert r.status_code == 201
    sid = r.json()["id"]
    r = api.patch(f"/api/sites/{sid}/", {"active": False}, format="json")
    assert r.status_code == 200
    assert api.delete(f"/api/sites/{sid}/").status_code == 204
    actions = list(AuditLog.objects.filter(object_type="sources.Site", object_id=str(sid))
                   .order_by("at").values_list("action", flat=True))
    assert actions == ["create", "update", "delete"]
    upd = AuditLog.objects.get(object_type="sources.Site", action="update")
    assert upd.before["active"] is True and upd.after["active"] is False


# Idempotência e filas -------------------------------------------------------------------------------------------

def test_entrypoint_run_poe_na_fila(api):
    ep = EntryPoint.objects.filter(site__slug="jn").first()
    with mock.patch("sources.tasks.discover_entrypoint.apply_async", queued("abc")) as m:
        r = api.post(f"/api/entrypoints/{ep.pk}/run/")
    assert r.status_code == 202
    assert r.json() == {"task_id": "abc", "queue": "discovery"}
    m.assert_called_once_with(args=[ep.pk], queue="discovery")
    assert AuditLog.objects.filter(action="run", object_id=str(ep.pk)).exists()


def test_idempotency_replay(api):
    ep = EntryPoint.objects.filter(site__slug="jn").first()
    with mock.patch("sources.tasks.discover_entrypoint.apply_async", queued("abc")) as m:
        r1 = api.post(f"/api/entrypoints/{ep.pk}/run/", HTTP_IDEMPOTENCY_KEY="k-1")
        r2 = api.post(f"/api/entrypoints/{ep.pk}/run/", HTTP_IDEMPOTENCY_KEY="k-1")
        r3 = api.post(f"/api/entrypoints/{ep.pk}/run/", HTTP_IDEMPOTENCY_KEY="k-2")
    assert m.call_count == 2   # a repetição com k-1 não volta a correr
    assert r1.status_code == r2.status_code == 202
    assert r2.json() == r1.json()
    assert r2["Idempotent-Replay"] == "true"
    assert r3.status_code == 202
    assert IdempotencyKey.objects.count() == 2
    # Mesma chave noutro caminho: conflito
    other = EntryPoint.objects.filter(site__slug="observador").first()
    r4 = api.post(f"/api/entrypoints/{other.pk}/run/", HTTP_IDEMPOTENCY_KEY="k-1")
    assert r4.status_code == 422


def test_idempotency_create_nao_duplica(api):
    body = {"canonical_name": "Fulano", "type": "pessoa"}
    r1 = api.post("/api/entities/", body, format="json", HTTP_IDEMPOTENCY_KEY="e-1")
    r2 = api.post("/api/entities/", body, format="json", HTTP_IDEMPOTENCY_KEY="e-1")
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert Entity.objects.filter(canonical_name="Fulano").count() == 1


def test_refetch_e_analyze(api):
    a, (v,) = make_article()
    with mock.patch("crawl.tasks.fetch_article.apply_async", queued("f1")) as m:
        r = api.post(f"/api/articles/{a.pk}/refetch/")
    assert r.status_code == 202 and r.json()["queue"] == "crawl"
    m.assert_called_once_with(args=[a.pk, "manual"], queue="crawl")
    with mock.patch("analysis.tasks.analyze_version.apply_async", queued("a1")) as m:
        r = api.post(f"/api/versions/{v.pk}/analyze/")
    assert r.status_code == 202
    m.assert_called_once_with(args=[v.pk], queue="analysis")


def test_ingest(api, django_capture_on_commit_callbacks):
    with mock.patch("crawl.tasks.fetch_article.apply_async", queued()) as m:
        with django_capture_on_commit_callbacks(execute=True):
            r = api.post("/api/articles/ingest/", {"url": "https://www.jn.pt/nacional/artigo/18100000",
                                                    "site": "jn"}, format="json")
        assert r.status_code == 201, r.content
        assert r.json()["created"] is True
        assert m.call_count == 1
        with django_capture_on_commit_callbacks(execute=True):
            r = api.post("/api/articles/ingest/", {"url": "https://www.jn.pt/nacional/artigo/18100000",
                                                    "site": "jn"}, format="json")
        assert r.status_code == 200 and r.json()["created"] is False
        assert m.call_count == 1
    r = api.post("/api/articles/ingest/", {"url": "https://observador.pt/x/", "site": "jn"}, format="json")
    assert r.status_code == 400


def test_failure_retry(api):
    f = TechnicalFailure.objects.create(url="https://www.jn.pt/a", kind="timeout", status="given_up")
    r = api.post(f"/api/failures/{f.pk}/retry/")
    assert r.status_code == 200
    f.refresh_from_db()
    assert f.status == "open" and f.next_retry_at is not None
    assert AuditLog.objects.filter(action="retry", object_id=str(f.pk)).exists()


# Notícias -------------------------------------------------------------------------------------------------------

def test_article_detail_e_versao(api):
    a, versions = make_article(n_versions=2)
    Analysis.objects.create(version=versions[1], status="done", summary="resumo")
    r = api.get(f"/api/articles/{a.pk}/")
    assert r.status_code == 200
    d = r.json()
    assert [v["number"] for v in d["versions"]] == [1, 2]
    assert d["latest_analysis"]["summary"] == "resumo"
    assert d["cluster"] is None
    r = api.get(f"/api/articles/{a.pk}/versions/2/")
    assert r.status_code == 200 and r.json()["diff"] == {"n": 2}
    assert api.get(f"/api/articles/{a.pk}/versions/9/").status_code == 404
    assert api.get("/api/articles/?site=jn&q=notícia").json()["count"] == 1
    assert api.get("/api/articles/?site=observador").json()["count"] == 0


# Entidades: fusão -----------------------------------------------------------------------------------------------

def _entity_with_links(name, article_versions):
    e = Entity.objects.create(canonical_name=name, type="pessoa", status="por_rever")
    EntityAlias.objects.create(entity=e, alias=name, normalized=name.lower())
    for v in article_versions:
        an = Analysis.objects.create(version=v, status="done")
        ArticleEntity.objects.create(analysis=an, entity=e, name_in_text=name)
        CitedSource.objects.create(analysis=an, type="oficial", name=name, entity=e)
    return e


def test_entity_merge_dry_run_e_real(api):
    _, vs = make_article(n_versions=2)
    src = _entity_with_links("antónio costa", vs)
    EntityAlias.objects.create(entity=src, alias="Costa", normalized="costa")
    dst = Entity.objects.create(canonical_name="António Costa", type="pessoa", status="active")
    EntityAlias.objects.create(entity=dst, alias="costa", normalized="costa")
    site = Site.objects.get(slug="jn")
    site.entity = src
    site.save()

    r = api.post(f"/api/entities/{src.pk}/merge/", {"into": dst.pk, "dry_run": True}, format="json")
    assert r.status_code == 200, r.content
    imp = r.json()["impact"]
    assert r.json()["dry_run"] is True
    assert imp["mentions"] == 2 and imp["cited_sources"] == 2 and imp["sites"] == 1
    assert imp["aliases"] == 2 and imp["aliases_duplicated"] == 1
    # dry-run não muda nada
    src.refresh_from_db()
    assert src.status == "por_rever" and ArticleEntity.objects.filter(entity=src).count() == 2
    assert not AuditLog.objects.filter(action="merge").exists()

    r = api.post(f"/api/entities/{src.pk}/merge/", {"into": dst.pk, "dry_run": False}, format="json")
    assert r.status_code == 200, r.content
    src.refresh_from_db()
    assert src.status == "merged" and src.merged_into_id == dst.pk
    assert ArticleEntity.objects.filter(entity=dst).count() == 2
    assert CitedSource.objects.filter(entity=dst).count() == 2
    assert Site.objects.get(slug="jn").entity_id == dst.pk
    assert set(EntityAlias.objects.filter(entity=dst).values_list("normalized", flat=True)) >= {
        "costa", "antónio costa", "antonio costa"}
    assert not EntityAlias.objects.filter(entity=src).exists()
    log = AuditLog.objects.get(action="merge")
    assert log.extra["into"] == dst.pk and log.after["source"]["status"] == "merged"
    # Fundir de novo: erro
    r = api.post(f"/api/entities/{src.pk}/merge/", {"into": dst.pk, "dry_run": False}, format="json")
    assert r.status_code == 400


def test_entity_review_queue_e_aliases(api):
    _, vs = make_article()
    e = _entity_with_links("Fulano", vs)
    Entity.objects.create(canonical_name="Activa", type="pessoa", status="active")
    r = api.get("/api/entities/review-queue/")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["results"]] == [e.pk]
    assert r.json()["results"][0]["mentions"] == 1
    r = api.post(f"/api/entities/{e.pk}/aliases/", {"alias": "Sr. Fulano"}, format="json")
    assert r.status_code == 201
    alias_id = r.json()["id"]
    assert api.post(f"/api/entities/{e.pk}/aliases/", {"alias": "sr fulano"}, format="json").status_code == 400
    assert api.delete(f"/api/entities/{e.pk}/aliases/{alias_id}/").status_code == 204
    assert AuditLog.objects.filter(action__in=["alias_add", "alias_remove"]).count() == 2


# Temas ----------------------------------------------------------------------------------------------------------

def test_topic_merge_e_hot(api):
    _, (v,) = make_article()
    an = Analysis.objects.create(version=v, status="done")
    src = Topic.objects.create(name="OE", slug="oe", status="por_rever", temperature=2.0)
    dst = Topic.objects.create(name="Orçamento do Estado", slug="orcamento", status="active", temperature=6.0)
    ed_src = Edition.objects.create(topic=src, label="2027")
    ed_dst = Edition.objects.create(topic=dst, label="2027")
    ArticleTopic.objects.create(analysis=an, topic=src, edition=ed_src)
    r = api.post(f"/api/topics/{src.pk}/merge/", {"into": dst.pk}, format="json")   # dry_run por omissão
    assert r.json()["dry_run"] is True and r.json()["impact"]["article_links"] == 1
    assert r.json()["impact"]["editions_merged"] == 1
    r = api.post(f"/api/topics/{src.pk}/merge/", {"into": dst.pk, "dry_run": False}, format="json")
    assert r.status_code == 200
    link = ArticleTopic.objects.get()
    assert link.topic_id == dst.pk and link.edition_id == ed_dst.pk
    assert not Edition.objects.filter(pk=ed_src.pk).exists()
    dst.refresh_from_db()
    assert dst.temperature == 8.0

    r = api.get("/api/topics/hot/")
    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [dst.pk]
    r = api.post(f"/api/topics/{dst.pk}/editions/", {"label": "2028"}, format="json")
    assert r.status_code == 201
    assert len(api.get(f"/api/topics/{dst.pk}/editions/").json()) == 2


# Estatísticas e auditoria ---------------------------------------------------------------------------------------

def test_stats(api):
    make_article()
    r = api.get("/api/stats/")
    assert r.status_code == 200
    d = r.json()
    assert d["articles_by_site_status"]["jn"]["active"] == 1
    assert len(d["daily"]["new_articles"]) == parameters.get("stats.daily_days")
    assert d["daily"]["new_articles"][-1]["n"] == 1


def test_audit_list(api):
    api.patch("/api/parameters/crawl.timeout_s/", {"value": 20}, format="json")
    r = api.get("/api/audit/?actor=agente&object_type=core.Parameter")
    assert r.status_code == 200 and r.json()["count"] == 1


# Comando create_actor -------------------------------------------------------------------------------------------

def test_create_actor(db):
    out = StringIO()
    call_command("create_actor", "bot", "--kind", "agent", stdout=out, stderr=StringIO())
    key = out.getvalue().strip()
    tok = Token.objects.get(key=key)
    assert tok.user.username == "bot" and tok.user.actor.kind == "agent"
    assert not tok.user.is_staff
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {key}")
    assert c.get("/api/audit/").status_code == 200
