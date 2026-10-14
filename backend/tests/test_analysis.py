"""Análise LLM com o provider fake: catalogação, idempotência, orçamento, drain, diff e falhas."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from analysis import llm, prompts, service
from analysis.models import Analysis, CitedSource
from core.models import Parameter
from crawl import versioning
from crawl.models import Article, Fetch, Version
from entities.models import ArticleEntity, Entity, EntityAlias
from parsers import registry
from sources.models import Site
from tests.conftest import fixture_text
from topics.models import ArticleTopic, Topic

pytestmark = pytest.mark.django_db

OBS = ("observador", "observador_article_8365764.html")
JN = ("jn", "jn_article_18136568.html")


# --- Helpers (usados também nos testes de temas e duplicados) ----------------------------------------------------

def set_param(key, value):
    Parameter.objects.update_or_create(key=key, defaults={"value": value})


def make_version(site_slug: str, fixture: str, *, article: Article | None = None, content: dict | None = None,
                 published_at: datetime | None = None, status: str = "active") -> Version:
    site = Site.objects.get(slug=site_slug)
    if content is None:
        content = registry.article(site.parser_module, fixture_text(fixture), None).to_dict()
    if article is None:
        pub = published_at or (datetime.fromisoformat(content["published_at"]) if content.get("published_at")
                               else timezone.now())
        sid = content.get("site_article_id")
        if sid and Article.objects.filter(site=site, site_article_id=sid).exists():
            sid = f"{sid}-{Article.objects.count()}"   # a mesma fixture como outra notícia
        article = Article.objects.create(
            site=site, site_article_id=sid, status=status,
            canonical_url=content.get("canonical_url") or f"https://{site.slug}.pt/x/{Article.objects.count()}",
            title=content.get("title") or "", published_at=pub, agencies=content.get("agencies") or [],
        )
    number = article.version_count + 1
    fetch = Fetch.objects.create(article=article, url=article.canonical_url, reason="new", outcome="ok")
    v = Version.objects.create(
        article=article, number=number, fetch=fetch, content=content, content_hash=versioning.content_hash(content),
        text=versioning.plain_text(content), word_count=content.get("word_count") or 0,
    )
    article.version_count = number
    article.save(update_fields=["version_count"])
    return v


def base_output(**over) -> dict:
    out = {
        "piece_type": "noticia",
        "entities": [],
        "sources": [],
        "themes": [theme(["Geral"], weight=0.5)],
        "locations": [],
        "ai_indicator": {"score": 5, "signals": []},
        "debug": {"reasoning": "teste", "sources_used": ["lead"], "sources_discarded": ["tags: genéricas"]},
    }
    out.update(over)
    return out


def ent(name, canonical=None, type_="pessoa", roles=("citado",), sentiment="neutro", position=None):
    return {"name": name, "canonical_name": canonical or name, "type": type_, "is_public": True,
            "roles": list(roles), "position_at_date": position, "sentiment": sentiment,
            "sentiment_reason": f"razão para {name}"}


def theme(path, kind="tema", edition=None, weight=1.0, is_new=False):
    return {"path": list(path), "kind": kind, "edition": edition, "weight": weight, "is_new": is_new}


@pytest.fixture
def fake(seeded, monkeypatch):
    """Provider fake + saída controlada pelo teste (`fake.output = {...}`)."""
    set_param("llm.provider", "fake")
    set_param("llm.model", "fake-1")

    class Holder:
        output = None
        calls = []

    _default = llm.fake_output

    def _out(system, user):
        Holder.calls.append((system, user))
        return copy.deepcopy(Holder.output) if Holder.output is not None else _default(system, user)

    monkeypatch.setattr(llm, "fake_output", _out)
    Holder.calls = []
    return Holder


def _rich_output():
    return base_output(
        entities=[
            ent("José Manuel Pureza", roles=("citado", "visado"), position="coordenador do BE", sentiment="neutro"),
            ent("BE", "Bloco de Esquerda", "partido", roles=("visado",)),
            ent("MAI", "Ministério da Administração Interna", "governo", roles=("visado",), sentiment="negativo"),
            ent("JN", "Jornal de Notícias", "meio_comunicacao", roles=("mencionado",)),
        ],
        sources=[
            {"type": "oficial", "entity_name": "Bloco de Esquerda", "partial_attribute": None,
             "excerpt": "falava aos jornalistas"},
            {"type": "outro_meio", "entity_name": "Observador", "partial_attribute": None, "excerpt": "segundo o Observador"},
            {"type": "anonima", "entity_name": None, "partial_attribute": "fonte do MAI", "excerpt": "fonte do MAI"},
        ],
        themes=[
            theme(["Política", "Administração Interna"], weight=0.9),
            theme(["Política", "Administração Interna", "Saída do secretário-geral do MAI"], kind="caso",
                  weight=0.7, is_new=True),
            theme(["Política", "Orçamento do Estado"], edition="OE2027", weight=0.2),
        ],
        locations=[{"name": "Lisboa", "level": "concelho", "parent": "Lisboa (distrito)"}],
    )


@pytest.fixture
def taxonomy(seeded):
    from topics.seed import ensure_taxonomy

    ensure_taxonomy()


# --- Testes -----------------------------------------------------------------------------------------------------

def test_end_to_end_creates_entities_sources_topics(fake, taxonomy):
    fake.output = _rich_output()
    v = make_version(*OBS)
    res = service.analyze(v.pk)
    assert res["status"] == "done", res
    a = Analysis.objects.get(pk=res["analysis_id"])
    assert (a.provider, a.model, a.prompt_version) == ("fake", "fake-1", prompts.PROMPT_VERSION)
    assert a.piece_type == "noticia" and a.attempts == 1 and a.usage["tokens_in"] > 0
    assert a.raw_response["entities"][0]["name"] == "José Manuel Pureza"
    assert a.debug["llm"]["sources_discarded"] == ["tags: genéricas"]
    assert a.ai_indicator == {"score": 5, "signals": []}
    assert a.diff_from_previous is None

    # Prompt: candidatos da BD no system, texto da notícia no user.
    system, user = fake.calls[-1]
    assert "- Política > Administração Interna · nenhuma" in system
    assert "Pureza" in user and "Site: observador" in user

    pureza = ArticleEntity.objects.get(analysis=a, entity__canonical_name="José Manuel Pureza")
    assert pureza.roles == ["citado", "visado"] and pureza.position_at_time == "coordenador do BE"
    assert pureza.entity.status == "por_rever"
    assert pureza.debug["position_in_text"] is True
    assert set(pureza.entity.aliases.values_list("normalized", flat=True)) == {"jose manuel pureza"}
    mai = ArticleEntity.objects.get(analysis=a, entity__canonical_name="Ministério da Administração Interna")
    assert mai.entity.type == "governo" and mai.sentiment == "negativo" and mai.evidence
    assert {"mai", "ministerio da administracao interna"} <= set(mai.entity.aliases.values_list("normalized", flat=True))

    # Meio de comunicação → Site.entity (JN como entidade; Observador como fonte "outro meio").
    jn_site = Site.objects.get(slug="jn")
    assert ArticleEntity.objects.get(analysis=a, name_in_text="JN").entity_id == jn_site.entity_id
    src = {s.type: s for s in CitedSource.objects.filter(analysis=a)}
    assert src["outro_meio"].entity_id == Site.objects.get(slug="observador").entity_id
    assert src["oficial"].entity.canonical_name == "Bloco de Esquerda"
    assert src["anonima"].partial_attribute == "fonte do MAI" and src["anonima"].entity is None

    # Local.
    lisboa = ArticleEntity.objects.get(analysis=a, is_location=True)
    assert lisboa.entity.type == "local" and lisboa.entity.place_level == "concelho"
    assert lisboa.entity.parent.canonical_name == "Lisboa (distrito)"

    # Temas: existente liga; caso novo fica por rever, pendurado no ramo; edição criada.
    links = {lt.topic.name: lt for lt in ArticleTopic.objects.filter(analysis=a).select_related("topic", "edition")}
    assert links["Administração Interna"].created_topic is False
    assert links["Administração Interna"].topic.status == "active"
    caso = links["Saída do secretário-geral do MAI"]
    assert caso.created_topic and caso.topic.status == "por_rever" and caso.topic.kind == "caso"
    assert caso.topic.parent == links["Administração Interna"].topic
    assert links["Orçamento do Estado"].edition.label == "OE2027"
    assert links["Administração Interna"].weight == 0.9

    # Cadência recalculada a partir dos temas.
    v.article.refresh_from_db()
    assert v.article.revisit_reason


def test_idempotent(fake, taxonomy):
    fake.output = _rich_output()
    v = make_version(*OBS)
    r1 = service.analyze(v.pk)
    n_entities = Entity.objects.count()
    r2 = service.analyze(v.pk)
    assert r2["analysis_id"] == r1["analysis_id"] and r2["skipped"]
    assert Analysis.objects.filter(version=v).count() == 1
    assert Entity.objects.count() == n_entities
    assert len(fake.calls) == 1


def test_alias_reuse_on_second_article(fake, taxonomy):
    fake.output = _rich_output()
    v1 = make_version(*OBS)
    service.analyze(v1.pk)
    n_entities = Entity.objects.count()
    pureza = Entity.objects.get(canonical_name="José Manuel Pureza")
    pureza.status = "active"
    pureza.save()

    out = _rich_output()
    out["entities"][0] = ent("Pureza", "José Manuel Pureza")      # nome curto, canonical igual
    out["entities"][1] = ent("Bloco de Esquerda", "Bloco de Esquerda", "partido")
    fake.output = out
    v2 = make_version(*JN)
    a2 = Analysis.objects.get(pk=service.analyze(v2.pk)["analysis_id"])
    assert Entity.objects.count() == n_entities                      # nenhuma entidade nova
    assert ArticleEntity.objects.get(analysis=a2, name_in_text="Pureza").entity_id == pureza.pk
    # Aprendeu o alias curto ("Pureza") a partir do canonical.
    assert EntityAlias.objects.filter(entity=pureza, normalized="pureza").exists()
    # O tema novo criado na 1.ª análise é reutilizado (match pelo caminho), não duplicado.
    assert Topic.objects.filter(name="Saída do secretário-geral do MAI").count() == 1
    assert not ArticleTopic.objects.filter(analysis=a2, created_topic=True).exists()


def test_ambiguous_creates_placeholder_and_reuses_it(fake):
    for full in ("António Costa", "Alberto Costa"):
        e = Entity.objects.create(canonical_name=full, type="pessoa", status="active")
        EntityAlias.objects.create(entity=e, alias="Costa", normalized="costa")
    fake.output = base_output(entities=[ent("Costa", "Costa")])
    a1 = Analysis.objects.get(pk=service.analyze(make_version(*OBS).pk)["analysis_id"])
    ae = ArticleEntity.objects.get(analysis=a1)
    assert ae.entity.status == "por_rever"
    assert ae.entity.debug["reason"] == "ambíguo"
    assert {c["name"] for c in ae.entity.debug["candidates"]} == {"António Costa", "Alberto Costa"}
    assert "ambíguo" in ae.debug["resolution"]["decision"]

    a2 = Analysis.objects.get(pk=service.analyze(make_version(*JN).pk)["analysis_id"])
    assert ArticleEntity.objects.get(analysis=a2).entity_id == ae.entity_id   # não cria outra provisória
    assert Entity.objects.filter(canonical_name="Costa").count() == 1


def test_unique_canonical_beats_ambiguous_name(fake):
    costa = Entity.objects.create(canonical_name="António Costa", type="pessoa", status="active")
    EntityAlias.objects.create(entity=costa, alias="António Costa", normalized="antonio costa")
    other = Entity.objects.create(canonical_name="Alberto Costa", type="pessoa", status="active")
    for e in (costa, other):
        EntityAlias.objects.create(entity=e, alias="Costa", normalized="costa")
    fake.output = base_output(entities=[ent("Costa", "António Costa")])
    a = Analysis.objects.get(pk=service.analyze(make_version(*OBS).pk)["analysis_id"])
    assert ArticleEntity.objects.get(analysis=a).entity_id == costa.pk


def test_new_topic_without_taxonomy_is_por_rever(fake):
    fake.output = base_output(themes=[theme(["Ambiente", "Seca"], is_new=True, weight=0.6)])
    a = Analysis.objects.get(pk=service.analyze(make_version(*OBS).pk)["analysis_id"])
    link = ArticleTopic.objects.get(analysis=a)
    assert link.created_topic and link.topic.status == "por_rever" and link.topic.parent.name == "Ambiente"
    assert link.topic.parent.status == "por_rever"
    assert link.topic.debug["created_by_analysis"] == a.pk


def test_budget_exhausted_then_drain(fake):
    set_param("analysis.daily_limit", 1)
    fake.output = base_output()
    v1, v2 = make_version(*OBS), make_version(*JN)
    assert service.analyze(v1.pk)["status"] == "done"
    r2 = service.analyze(v2.pk)
    assert r2["status"] == "skipped_budget"
    assert service.drain(inline=True) == 0                     # orçamento esgotado: não retoma
    assert Analysis.objects.get(pk=r2["analysis_id"]).status == "skipped_budget"

    set_param("analysis.daily_limit", 5)
    assert service.drain(inline=True) == 1
    a2 = Analysis.objects.get(pk=r2["analysis_id"])            # a mesma linha, agora feita
    assert a2.status == "done" and a2.attempts == 1
    assert Analysis.objects.filter(version=v2).count() == 1
    assert service.drain(inline=True) == 0


def test_drain_enqueues_by_default(fake, monkeypatch):
    set_param("analysis.daily_limit", 0)
    fake.output = base_output()
    v = make_version(*OBS)
    service.analyze(v.pk)
    set_param("analysis.daily_limit", 10)
    sent = []
    monkeypatch.setattr("analysis.tasks.analyze_version.apply_async", lambda args, queue: sent.append((args, queue)))
    assert service.drain() == 1 and sent == [([v.pk], "analysis")]


def test_invalid_output_fails_and_retries(fake):
    set_param("analysis.max_attempts", 2)
    fake.output = {"piece_type": "noticia"}                   # falha o schema (com reparação incluída)
    v = make_version(*OBS)
    r = service.analyze(v.pk)
    a = Analysis.objects.get(pk=r["analysis_id"])
    assert a.status == "failed" and a.attempts == 1 and "resposta inválida" in a.error
    assert a.usage["repairs"] == 1 and len(fake.calls) == 2
    assert "não passou a validação" in fake.calls[1][1]

    fake.output = base_output()
    assert service.drain(inline=True) == 1
    a.refresh_from_db()
    assert a.status == "done" and a.attempts == 2

    # Tentativas esgotadas: o drain já não pega.
    fake.output = {"x": 1}
    v2 = make_version(*JN)
    service.analyze(v2.pk)
    service.drain(inline=True)
    a2 = Analysis.objects.get(version=v2)
    assert a2.status == "failed" and a2.attempts == 2
    assert service.drain(inline=True) == 0


def test_provider_error_is_recorded(fake, monkeypatch):
    def boom(self, system, user, schema):
        raise llm.ProviderError("HTTP 529: overloaded")

    monkeypatch.setattr(llm.FakeProvider, "analyse", boom)
    r = service.analyze(make_version(*OBS).pk)
    a = Analysis.objects.get(pk=r["analysis_id"])
    assert a.status == "failed" and a.error == "HTTP 529: overloaded"


def test_inactive_or_empty_is_skipped(fake):
    v = make_version(*OBS, status="out_of_scope")
    assert service.analyze(v.pk)["status"] == "skipped"
    content = registry.article("jn", fixture_text(JN[1]), None).to_dict()
    content["body"] = []
    v2 = make_version("jn", "", content=content)
    r = service.analyze(v2.pk)
    assert r["status"] == "skipped" and r["reason"] == "corpo vazio"
    assert not fake.calls


def test_skipped_does_not_count_for_budget(fake):
    set_param("analysis.daily_limit", 1)
    service.analyze(make_version(*OBS, status="deleted").pk)
    fake.output = base_output()
    assert service.analyze(make_version(*JN).pk)["status"] == "done"


def test_diff_from_previous(fake):
    fake.output = base_output(
        entities=[ent("Ana Silva"), ent("Rui Costa", sentiment="positivo")],
        sources=[{"type": "agencia", "entity_name": "Agência Lusa", "partial_attribute": None, "excerpt": "Lusa"}],
        themes=[theme(["Política", "Governo"])],
    )
    v1 = make_version(*OBS)
    service.analyze(v1.pk)

    content = copy.deepcopy(v1.content)
    content["body"].append({"kind": "p", "text": "Parágrafo acrescentado na revisita.", "links": []})
    v2 = make_version("observador", "", article=v1.article, content=content)
    fake.output = base_output(
        piece_type="analise",
        entities=[ent("Rui Costa", sentiment="negativo"), ent("Marta Reis")],
        sources=[{"type": "oficial", "entity_name": None, "partial_attribute": None, "excerpt": "comunicado"}],
        themes=[theme(["Política", "Governo"]), theme(["Economia"])],
    )
    a2 = Analysis.objects.get(pk=service.analyze(v2.pk)["analysis_id"])
    d = a2.diff_from_previous
    assert d["previous_version"] == 1 and d["changed"]
    assert [e["name"] for e in d["entities_added"]] == ["Marta Reis"]
    assert [e["name"] for e in d["entities_removed"]] == ["Ana Silva"]
    assert d["sentiment_changed"] == [{"id": d["sentiment_changed"][0]["id"], "name": "Rui Costa",
                                       "before": "positivo", "after": "negativo"}]
    assert [t["name"] for t in d["topics_added"]] == ["Economia"] and d["topics_removed"] == []
    assert d["sources_added"] == [{"type": "oficial", "name": ""}]
    assert d["sources_removed"] == [{"type": "agencia", "name": "agencia lusa"}]
    assert d["piece_type"] == {"before": "noticia", "after": "analise"}


def test_default_fake_output_is_schema_valid(fake):
    fake.output = None   # usa a saída determinística do provider fake
    r = service.analyze(make_version(*JN).pk)
    assert r["status"] == "done"
    a = Analysis.objects.get(pk=r["analysis_id"])
    assert a.raw_response["entities"] and a.raw_response["themes"]
    assert a.entities.exists() and a.topics.exists()


def test_load_config_never_sends_temperature_to_anthropic(seeded):
    from core.parameters import DEFAULTS

    set_param("llm.provider", "anthropic")
    set_param("llm.params", {"effort": "low"})
    cfg = llm.load_config()
    assert "temperature" not in cfg.params and cfg.params["effort"] == "low"
    assert cfg.params["max_tokens"] == DEFAULTS["llm.max_output_tokens"][0] and cfg.model_id == "claude-haiku-5-5"
    set_param("llm.provider", "ollama")
    assert llm.load_config().params["temperature"] == 0.0


def test_budget_window_is_utc_day(fake):
    set_param("analysis.daily_limit", 1)
    fake.output = base_output()
    v = make_version(*OBS)
    service.analyze(v.pk)
    Analysis.objects.update(started_at=service.today_start() - timedelta(minutes=1))   # foi "ontem"
    assert service.analyze(make_version(*JN).pk)["status"] == "done"


def test_empty_stub_is_repaired_once(fake, monkeypatch):
    """Resposta "stub" (listas vazias) num artigo longo: inválida, 1 reparação com os erros, e só depois failed."""
    stub = base_output(themes=[], debug={"reasoning": "x", "sources_used": [], "sources_discarded": []})
    good = base_output(entities=[ent("José Manuel Pureza")])
    outputs = [stub, good]
    monkeypatch.setattr(llm, "fake_output", lambda system, user: (fake.calls.append((system, user)), outputs.pop(0))[1])
    a = Analysis.objects.get(pk=service.analyze(make_version(*OBS).pk)["analysis_id"])
    assert a.status == "done" and a.usage["repairs"] == 1
    assert "resposta vazia" in a.debug["attempts"][0]["errors"][0] and a.debug["attempts"][1]["errors"] == []
    assert "resposta vazia" in fake.calls[1][1]

    fake.calls.clear()
    outputs[:] = [stub, stub]
    a2 = Analysis.objects.get(pk=service.analyze(make_version(*JN).pk)["analysis_id"])
    assert a2.status == "failed" and "resposta vazia" in a2.error and len(a2.debug["attempts"]) == 2


def test_empty_output_ok_for_short_article(fake):
    set_param("analysis.min_words_expect_entities", 100_000)
    fake.output = base_output(themes=[])
    assert service.analyze(make_version(*OBS).pk)["status"] == "done"
