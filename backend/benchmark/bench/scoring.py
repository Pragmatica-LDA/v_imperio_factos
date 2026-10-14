"""Pontuação de uma análise contra a baseline do mesmo artigo.

Cada métrica dá um valor 0–1; o total é a média ponderada com os pesos da ScoringConfig. Quando a baseline e
o candidato não têm itens numa lista (ex.: nenhuma fonte), a métrica vale 1. Métricas que só se aplicam a
itens emparelhados (ex.: sentimento) ficam None quando não há pares e saem da média ponderada.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from rapidfuzz import fuzz

# Valores iniciais, copiados para a BD pelo `bench_seed`. Os que contam são os da ScoringConfig activa.
DEFAULT_WEIGHTS = {
    "piece_type": 1.0,
    "entities_f1": 2.0,
    "entity_type": 0.5,
    "entity_public": 0.5,
    "entity_roles": 1.0,
    "entity_sentiment": 2.0,
    "sources_f1": 1.0,
    "source_types": 1.0,
    "themes": 1.5,
    "theme_edition": 0.25,
    "locations_f1": 1.0,
    "ai_indicator": 0.25,
}
DEFAULT_THRESHOLDS = {
    "name_match": 85,          # rapidfuzz token_set_ratio mínimo para emparelhar entidades/locais
    "excerpt_match": 70,       # partial_ratio mínimo para emparelhar fontes pelo excerto
    "theme_level_match": 80,   # ratio mínimo para dois níveis de um caminho de temas serem iguais
    "sentiment_neutral_credit": 0.5,   # crédito quando um diz neutro e o outro positivo/negativo
}


def norm(text: str | None) -> str:
    """Minúsculas, sem acentos nem pontuação, espaços colapsados."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _names(entity: dict) -> list[str]:
    return [n for n in {norm(entity.get("name")), norm(entity.get("canonical_name"))} if n]


def name_similarity(a: dict, b: dict) -> float:
    best = 0.0
    for x in _names(a):
        for y in _names(b):
            best = max(best, 100.0 if x == y else fuzz.token_set_ratio(x, y))
    return best


def greedy_match(base: list, cand: list, sim, threshold: float) -> list[tuple[int, int, float]]:
    """Emparelha por ordem decrescente de semelhança, cada item no máximo uma vez."""
    pairs = sorted(
        ((sim(b, c), i, j) for i, b in enumerate(base) for j, c in enumerate(cand)),
        reverse=True,
    )
    used_b, used_c, matches = set(), set(), []
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_b or j in used_c:
            continue
        used_b.add(i)
        used_c.add(j)
        matches.append((i, j, score))
    return matches


def f1(n_base: int, n_cand: int, matched: float) -> float:
    if n_base == 0 and n_cand == 0:
        return 1.0
    if n_base == 0 or n_cand == 0:
        return 0.0
    precision, recall = matched / n_cand, matched / n_base
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _sentiment_score(a: str, b: str, neutral_credit: float) -> float:
    if a == b:
        return 1.0
    if "neutro" in (a, b):
        return neutral_credit
    return 0.0


def score_entities(base: list, cand: list, th: dict) -> tuple[dict, dict]:
    matches = greedy_match(base, cand, name_similarity, th["name_match"])
    pairs = [(base[i], cand[j]) for i, j, _ in matches]
    metrics = {
        "entities_f1": f1(len(base), len(cand), len(matches)),
        "entity_type": _mean([float(b["type"] == c["type"]) for b, c in pairs]),
        "entity_public": _mean([float(b["is_public"] == c["is_public"]) for b, c in pairs]),
        "entity_roles": _mean([_jaccard(b["roles"], c["roles"]) for b, c in pairs]),
        "entity_sentiment": _mean([
            _sentiment_score(b["sentiment"], c["sentiment"], th["sentiment_neutral_credit"]) for b, c in pairs
        ]),
    }
    matched_b, matched_c = {i for i, _, _ in matches}, {j for _, j, _ in matches}
    details = {
        "pairs": [
            {"baseline": b["canonical_name"], "candidate": c["canonical_name"],
             "sentiment": [b["sentiment"], c["sentiment"]], "roles": [b["roles"], c["roles"]],
             "type": [b["type"], c["type"]]}
            for b, c in pairs
        ],
        "missing": [base[i]["canonical_name"] for i in range(len(base)) if i not in matched_b],
        "extra": [cand[j]["canonical_name"] for j in range(len(cand)) if j not in matched_c],
    }
    return metrics, details


def score_sources(base: list, cand: list, th: dict) -> tuple[dict, dict]:
    def sim(b: dict, c: dict) -> float:
        if b["type"] != c["type"]:
            return 0.0
        anchor_b = norm(b.get("entity_name") or b.get("partial_attribute"))
        anchor_c = norm(c.get("entity_name") or c.get("partial_attribute"))
        anchor = fuzz.token_set_ratio(anchor_b, anchor_c) if anchor_b and anchor_c else 0.0
        excerpt = fuzz.partial_ratio(norm(b.get("excerpt")), norm(c.get("excerpt")))
        # Mesma fonte se a entidade/atributo coincide ou se o excerto é o mesmo; o maior desempata.
        if anchor >= th["name_match"] or excerpt >= th["excerpt_match"]:
            return max(anchor, excerpt)
        return 0.0

    matches = greedy_match(base, cand, sim, 1e-9)
    types_b, types_c = Counter(s["type"] for s in base), Counter(s["type"] for s in cand)
    overlap = sum((types_b & types_c).values())
    metrics = {
        "sources_f1": f1(len(base), len(cand), len(matches)),
        "source_types": f1(sum(types_b.values()), sum(types_c.values()), overlap),
    }
    details = {"types": [dict(types_b), dict(types_c)], "matched": len(matches)}
    return metrics, details


def path_similarity(a: list[str], b: list[str], level_threshold: float) -> float:
    """Fracção do caminho em comum a partir da raiz (prefixo), com fuzzy por nível."""
    if not a or not b:
        return 0.0
    common = 0
    for x, y in zip(a, b):
        if fuzz.ratio(norm(x), norm(y)) < level_threshold:
            break
        common += 1
    return common / max(len(a), len(b))


def score_themes(base: list, cand: list, th: dict) -> tuple[dict, dict]:
    def sim(b: dict, c: dict) -> float:
        return 100 * path_similarity(b["path"], c["path"], th["theme_level_match"])

    # Basta partilhar a raiz para emparelhar; o crédito é a fracção do caminho em comum.
    matches = greedy_match(base, cand, sim, 1e-9)
    soft = sum(s / 100 for _, _, s in matches)
    pairs = [(base[i], cand[j]) for i, j, _ in matches]
    with_edition = [(b, c) for b, c in pairs if b.get("edition")]
    metrics = {
        "themes": f1(len(base), len(cand), soft),
        "theme_edition": _mean([
            float(fuzz.ratio(norm(b["edition"]), norm(c.get("edition"))) >= th["theme_level_match"])
            for b, c in with_edition
        ]),
    }
    details = {
        "baseline": [" > ".join(t["path"]) for t in base],
        "candidate": [" > ".join(t["path"]) for t in cand],
    }
    return metrics, details


def score_locations(base: list, cand: list, th: dict) -> tuple[dict, dict]:
    def sim(b: dict, c: dict) -> float:
        x, y = norm(b["name"]), norm(c["name"])
        return 100.0 if x == y else fuzz.token_set_ratio(x, y)

    matches = greedy_match(base, cand, sim, th["name_match"])
    metrics = {"locations_f1": f1(len(base), len(cand), len(matches))}
    details = {"baseline": [l["name"] for l in base], "candidate": [l["name"] for l in cand]}
    return metrics, details


def score(baseline: dict, candidate: dict | None, weights: dict, thresholds: dict) -> tuple[dict, float, dict]:
    """Devolve (métricas, total, detalhes). Sem candidato válido, tudo vale 0."""
    th = {**DEFAULT_THRESHOLDS, **thresholds}
    if not candidate:
        metrics = {k: 0.0 for k in weights}
        return metrics, 0.0, {"invalid": True}

    metrics: dict[str, float | None] = {"piece_type": float(baseline["piece_type"] == candidate["piece_type"])}
    details: dict = {"piece_type": [baseline["piece_type"], candidate["piece_type"]]}
    for key, fn in (("entities", score_entities), ("sources", score_sources),
                    ("themes", score_themes), ("locations", score_locations)):
        m, d = fn(baseline[key], candidate[key], th)
        metrics.update(m)
        details[key] = d
    metrics["ai_indicator"] = 1 - min(abs(baseline["ai_indicator"]["score"] - candidate["ai_indicator"]["score"]), 100) / 100

    weighted = [(weights.get(k, 0.0), v) for k, v in metrics.items() if v is not None and weights.get(k, 0.0) > 0]
    total_weight = sum(w for w, _ in weighted)
    total = sum(w * v for w, v in weighted) / total_weight if total_weight else 0.0
    return metrics, total, details
