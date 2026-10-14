"""Testes do scoring do benchmark (sem BD)."""

import copy

import pytest

from benchmark.bench.schema import OUTPUT_SCHEMA_V1, validate
from benchmark.bench.scoring import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, norm, path_similarity, score


def entity(name, canonical, sentiment="neutro", roles=("citado",), type_="pessoa", public=True):
    return {"name": name, "canonical_name": canonical, "type": type_, "is_public": public, "roles": list(roles),
            "position_at_date": None, "sentiment": sentiment, "sentiment_reason": "—"}


BASE = {
    "piece_type": "noticia",
    "entities": [
        entity("Pureza", "José Manuel Pureza", "neutro", ("citado",)),
        entity("MAI", "Ministério da Administração Interna", "negativo", ("visado",), "governo"),
        entity("BE", "Bloco de Esquerda", "neutro", ("mencionado",), "partido"),
    ],
    "sources": [
        {"type": "oficial", "entity_name": "José Manuel Pureza", "partial_attribute": None,
         "excerpt": "afirmou aos jornalistas"},
        {"type": "agencia", "entity_name": "Lusa", "partial_attribute": None, "excerpt": "segundo a Lusa"},
    ],
    "themes": [
        {"path": ["Política", "Administração Interna"], "kind": "tema", "edition": None, "weight": 1.0, "is_new": False},
        {"path": ["Política", "Partidos"], "kind": "tema", "edition": None, "weight": 0.5, "is_new": False},
    ],
    "locations": [{"name": "Lisboa", "level": "concelho", "parent": "Lisboa"}],
    "ai_indicator": {"score": 5, "signals": []},
    "debug": {"reasoning": "—", "sources_used": [], "sources_discarded": []},
}


def run(candidate):
    return score(BASE, candidate, DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)


def test_base_is_schema_valid():
    assert validate(BASE, OUTPUT_SCHEMA_V1) == []


def test_identical_scores_one():
    metrics, total, _ = run(copy.deepcopy(BASE))
    assert total == pytest.approx(1.0)
    assert all(v == pytest.approx(1.0) for v in metrics.values() if v is not None)


def test_invalid_candidate_scores_zero():
    _, total, details = run(None)
    assert total == 0.0
    assert details["invalid"]


def test_names_match_with_accents_and_short_forms():
    cand = copy.deepcopy(BASE)
    cand["entities"][0] = entity("José Pureza", "Jose Manuel Pureza", "neutro", ("citado",))
    metrics, _, details = run(cand)
    assert metrics["entities_f1"] == pytest.approx(1.0)
    assert not details["entities"]["missing"]


def test_missing_and_extra_entities_lower_f1():
    cand = copy.deepcopy(BASE)
    cand["entities"] = cand["entities"][:2] + [entity("PSP", "Polícia de Segurança Pública", type_="instituicao")]
    metrics, _, details = run(cand)
    assert metrics["entities_f1"] == pytest.approx(2 / 3)
    assert details["entities"]["missing"] == ["Bloco de Esquerda"]
    assert details["entities"]["extra"] == ["Polícia de Segurança Pública"]


def test_sentiment_flip_costs_more_than_neutral():
    flip, neutral = copy.deepcopy(BASE), copy.deepcopy(BASE)
    flip["entities"][1]["sentiment"] = "positivo"
    neutral["entities"][1]["sentiment"] = "neutro"
    assert run(flip)[0]["entity_sentiment"] < run(neutral)[0]["entity_sentiment"] < 1.0


def test_roles_partial_credit():
    cand = copy.deepcopy(BASE)
    cand["entities"][0]["roles"] = ["citado", "fonte"]
    assert run(cand)[0]["entity_roles"] == pytest.approx((0.5 + 1 + 1) / 3)


def test_theme_parent_gets_partial_credit():
    assert path_similarity(["Política", "Partidos"], ["Política"], 80) == pytest.approx(0.5)
    assert path_similarity(["Política", "Partidos"], ["Economia"], 80) == 0.0
    cand = copy.deepcopy(BASE)
    cand["themes"] = [cand["themes"][0], {**cand["themes"][1], "path": ["Política"]}]
    assert run(cand)[0]["themes"] == pytest.approx(0.75)


def test_source_matches_by_excerpt_when_entity_missing():
    cand = copy.deepcopy(BASE)
    cand["sources"][1] = {"type": "agencia", "entity_name": None, "partial_attribute": None,
                          "excerpt": "segundo a Lusa"}
    assert run(cand)[0]["sources_f1"] == pytest.approx(1.0)


def test_source_type_mismatch():
    cand = copy.deepcopy(BASE)
    cand["sources"][0]["type"] = "especialista"
    metrics = run(cand)[0]
    assert metrics["sources_f1"] == pytest.approx(0.5)
    assert metrics["source_types"] == pytest.approx(0.5)


def test_empty_lists_on_both_sides_score_one():
    base, cand = copy.deepcopy(BASE), copy.deepcopy(BASE)
    base["locations"] = cand["locations"] = []
    assert score(base, cand, DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)[0]["locations_f1"] == 1.0


def test_schema_rejects_out_of_range_and_extra_fields():
    bad = copy.deepcopy(BASE)
    bad["themes"][0]["weight"] = 1.5
    bad["ai_indicator"]["score"] = 120
    bad["extra"] = 1
    errors = validate(bad, OUTPUT_SCHEMA_V1)
    assert any("weight" in e for e in errors)
    assert any("score" in e for e in errors)
    assert any("extra" in e for e in errors)


def test_norm():
    assert norm("  Ministério da Administração-Interna! ") == "ministerio da administracao interna"
