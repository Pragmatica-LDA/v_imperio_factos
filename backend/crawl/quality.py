"""Diagnóstico da extracção de cada leitura (base do dashboard de fiabilidade).

Portado do `diagnose()` de crawl_articles.py (PoC). `ok` = a extracção tem o essencial; os avisos
(imagens sem crédito, campos secundários) não contam para o `ok`.
"""

from __future__ import annotations

import re

from core import parameters

NOISE = re.compile(r"leia também|leia mais|subscrev|newsletter|assine|publicidade", re.I)

# Campos essenciais: se faltar algum, a extracção conta como falhada.
ESSENTIAL = ("title", "published_at", "canonical_url")
# Campos importantes: contam como problema, mas não como falha.
IMPORTANT = ("lead", "section", "site_article_id")


def diagnose(article: dict) -> dict:
    """`article` é o Article.to_dict() do parser."""
    min_words = int(parameters.get("quality.min_words"))
    errors: list[str] = []
    warnings: list[str] = []
    missing = [f for f in ESSENTIAL if not article.get(f)]
    missing_important = [f for f in IMPORTANT if not article.get(f)]
    errors += [f"missing:{f}" for f in missing]
    warnings += [f"missing:{f}" for f in missing_important]
    if not article.get("authors"):
        warnings.append("missing:authors")

    body = article.get("body") or []
    words = article.get("word_count") or sum(len((b.get("text") or "").split()) for b in body)
    if not article.get("out_of_scope"):
        if not body:
            errors.append("body:empty")
        elif words < min_words:
            warnings.append("body:short")
        if article.get("body_complete") is False:
            errors.append("body:incomplete")
        elif article.get("body_complete") is None:
            warnings.append("body:complete_unknown")
        noisy = [b.get("text", "")[:80] for b in body if NOISE.search(b.get("text") or "")]
        if noisy:
            warnings.append("body:noise")
        images = article.get("images") or []
        if not images:
            warnings.append("images:none")
        elif any(not (i.get("credit_raw") or i.get("photographers")) for i in images):
            warnings.append("images:no_credit")
    else:
        noisy = []
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "word_count": words,
        "noise_samples": noisy[:3],
    }
