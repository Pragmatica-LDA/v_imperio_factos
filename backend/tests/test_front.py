"""Front-office (/api/front/): histórias, entidades em destaque, estatísticas, detalhe e relacionadas."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from analysis import service
from api import front
from crawl.models import Article
from entities.models import Entity
from tests.test_analysis import JN, OBS, base_output, ent, fake, make_version, set_param, theme  # noqa: F401
from topics.models import Topic

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(seeded):
    u = get_user_model().objects.create_user("leitor", password="x")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=u).key}")
    return c


def analysed(fake, site, *, entities, themes, hours_ago=1, ai=5, title=None):
    fake.output = base_output(entities=entities, themes=themes, ai_indicator={"score": ai, "signals": []})
    v = make_version(*site, published_at=timezone.now() - timedelta(hours=hours_ago))
    if title:
        Article.objects.filter(pk=v.article_id).update(title=title)
    service.analyze(v.pk)
    return v.article


@pytest.fixture
def corpus(fake):
    """Duas notícias da mesma história (JN + Observador), uma de outro tema com as mesmas pessoas e uma solta."""
    pol = [theme(["Política", "Governo"])]
    a = analysed(fake, OBS, entities=[ent("Ana Costa", sentiment="positivo"), ent("Rui Lopes", sentiment="positivo")],
                 themes=pol, title="Ana e Rui no Governo")
    b = analysed(fake, JN, entities=[ent("Ana Costa"), ent("Rui Lopes", sentiment="negativo")], themes=pol,
                 hours_ago=2, ai=90, title="Rui e Ana, versão JN")
    c = analysed(fake, JN, entities=[ent("Ana Costa"), ent("Rui Lopes")], themes=[theme(["Desporto", "Futebol"])],
                 hours_ago=30, title="Ana e Rui no estádio")
    d = analysed(fake, OBS, entities=[ent("Zé Ninguém", sentiment="negativo")], themes=[theme(["Sociedade"])],
                 hours_ago=3, title="Outra coisa")
    return a, b, c, d


def test_exige_autenticacao(seeded):
    assert APIClient().get("/api/front/overview/").status_code == 401


def test_login_por_token(seeded):
    get_user_model().objects.create_user("leitor", password="segredo")
    r = APIClient().post("/api/auth/token/", {"username": "leitor", "password": "segredo"}, format="json")
    assert r.status_code == 200 and r.json()["token"]


def test_login_ignora_sessao_aberta_no_admin(seeded):
    """Com sessão do admin no browser, o login por token não pode exigir CSRF."""
    u = get_user_model().objects.create_user("leitor", password="segredo")
    c = APIClient(enforce_csrf_checks=True)
    c.force_login(u)
    r = c.post("/api/auth/token/", {"username": "leitor", "password": "segredo"}, format="json")
    assert r.status_code == 200 and r.json()["token"]
    bad = c.post("/api/auth/token/", {"username": "leitor", "password": "x"}, format="json")
    assert bad.status_code == 400


def test_historias_agrupam_por_entidades_salientes(corpus):
    a, b, c, d = corpus
    stories = front.build_stories(timezone.now(), 24)
    by_lead = {s["lead"]["id"]: s for s in stories}
    story = next(s for s in stories if {a.pk, b.pk} == {s["lead"]["id"], *[o["id"] for o in s["others"]]})
    assert story["n_articles"] == 2
    assert story["sites"] == ["jn", "observador"]
    assert {e["name"] for e in story["shared_entities"]} == {"Ana Costa", "Rui Lopes"}
    assert d.pk in by_lead                          # história própria
    assert c.pk not in {s["lead"]["id"] for s in stories}   # fora da janela de 24h


def test_minimo_de_entidades_partilhadas_configuravel(corpus):
    set_param("front.story_min_shared", 3)
    stories = front.build_stories(timezone.now(), 24)
    assert all(s["n_articles"] == 1 for s in stories)


def test_entidades_em_destaque_com_variacao(corpus):
    rows = {r["name"]: r for r in front.trending_entities(timezone.now(), 24)}
    assert rows["Ana Costa"]["n_articles"] == 2
    assert rows["Ana Costa"]["prev_articles"] == 1     # a notícia de há 30h conta na janela anterior
    assert rows["Ana Costa"]["delta"] == 1
    assert rows["Rui Lopes"]["sentiment"] == {"positivo": 1, "neutro": 0, "negativo": 1}


def test_estatisticas_tom_e_ia(corpus):
    stats = front.compute_stats(timezone.now())
    tone, ai = stats["total"]["tone"], stats["total"]["ai"]
    assert tone == {"positivo": 1, "neutro": 1, "negativo": 2}   # b: média (0 − 1)/2 = −0,5
    assert ai == {"sem_ia": 3, "com_ia": 1}
    assert stats["by_site"]["jn"]["ai"] == {"com_ia": 1, "sem_ia": 1}
    set_param("front.ai_threshold", 95)
    assert front.compute_stats(timezone.now())["total"]["ai"] == {"sem_ia": 4}


def test_overview_endpoint(api, corpus):
    r = api.get("/api/front/overview/")
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["articles_window"] == 3
    assert {b["site"] for b in body["latest_by_site"]} >= {"jn", "observador", "publico"}
    assert body["stories"] and body["entities"]


def test_detalhe_com_relacionadas_de_outro_tema(api, corpus):
    a, b, c, d = corpus
    r = api.get(f"/api/front/articles/{a.pk}/")
    assert r.status_code == 200
    body = r.json()
    assert {e["name"] for e in body["entities"]} == {"Ana Costa", "Rui Lopes"}
    same = [x["id"] for x in body["related"]["same_topic"]]
    other = [x["id"] for x in body["related"]["other_topics"]]
    assert b.pk in same and c.pk in other
    assert d.pk not in same + other
    assert {e["name"] for e in body["related"]["other_topics"][0]["shared_entities"]} == {"Ana Costa", "Rui Lopes"}


def test_entidade_tema_pesquisa_arquivo(api, corpus):
    a, b, c, d = corpus
    ana = Entity.objects.get(canonical_name="Ana Costa")
    r = api.get(f"/api/front/entities/{ana.pk}/").json()
    assert r["n_articles"] == 3
    assert {x["name"] for x in r["co_entities"]} == {"Rui Lopes"}
    governo = Topic.objects.get(name="Governo")
    t = api.get(f"/api/front/topics/{governo.pk}/").json()
    assert t["n_articles"] == 2 and t["path"][0]["name"] == "Política"
    politica = Topic.objects.get(name="Política")
    assert api.get(f"/api/front/topics/{politica.pk}/").json()["n_articles"] == 2   # inclui os subtemas
    s = api.get("/api/front/search/?q=ana").json()
    assert s["entities"][0]["name"] == "Ana Costa"
    arch = api.get(f"/api/front/articles/?entity={ana.pk}&site=jn").json()
    assert arch["count"] == 2 and {x["id"] for x in arch["results"]} == {b.pk, c.pk}
