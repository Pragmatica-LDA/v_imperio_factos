"""Crawl de artigos individuais (PoC).

Uso: python3 crawl_articles.py <site> <url> [<url> ...]

Para cada URL: descarrega, guarda o HTML em sites/raw/<site>_article_<id>_<ts>.html,
corre parse_article, escreve sites/out/<site>_article_<id>_<ts>.json e imprime um
diagnóstico com os possíveis problemas.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import time
from datetime import datetime, timezone

from crawl_homepages import DELAY_S, OUT, RAW, ROOT, fetch


def diagnose(a) -> list[str]:
    problems = []
    for field in ("title", "lead", "published_at", "section", "site_article_id", "canonical_url"):
        if not getattr(a, field):
            problems.append(f"sem {field}")
    if not a.authors:
        problems.append("sem autores")
    if not a.body:
        problems.append("corpo vazio")
    elif (a.word_count or 0) < 120:
        problems.append(f"corpo curto ({a.word_count} palavras)")
    if a.body_complete is False:
        problems.append("corpo incompleto")
    if a.body_complete is None:
        problems.append("body_complete desconhecido")
    if not a.images:
        problems.append("sem imagens")
    elif not any(i.photographers or i.credit_raw for i in a.images):
        problems.append("imagens sem crédito")
    if a.out_of_scope:
        problems.append(f"fora de âmbito: {a.out_of_scope}")
    noise = re.compile(r"(leia também|leia mais|subscrev|newsletter|assine|publicidade)", re.I)
    noisy = [b.text[:60] for b in a.body if noise.search(b.text)]
    if noisy:
        problems.append(f"possível ruído no corpo: {noisy}")
    return problems


def crawl(site: str, url: str, ts: str) -> None:
    mod = importlib.import_module(f"parsers.{site}")
    status, final_url, html = fetch(url)
    a = mod.parse_article(html, final_url)
    aid = a.site_article_id or re.sub(r"\W+", "-", url)[-40:]
    raw_path = RAW / f"{site}_article_{aid}_{ts}.html"
    raw_path.write_text(html, encoding="utf-8")
    out_path = OUT / f"{site}_article_{aid}_{ts}.json"
    out_path.write_text(json.dumps(a.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n== {site} · {aid} ==")
    print(f"HTTP {status} {final_url}" + ("  (redirect)" if final_url != url else ""))
    print(f"título: {a.title}")
    print(f"autores: {[x.name for x in a.authors]} · agências: {a.agencies} · byline: {a.byline_raw}")
    print(f"publicado: {a.published_at} · actualizado: {a.updated_at} · secção: {a.section}/{a.subsection}")
    print(f"tipo: {a.piece_type} ({a.piece_type_raw}) · acesso: {a.access} · completo: {a.body_complete} "
          f"({a.body_source}) · blocos: {len(a.body)} · palavras: {a.word_count}")
    print(f"tags: {a.tags}")
    print(f"imagens: {[(i.photographers, i.agency, i.credit_raw) for i in a.images]}")
    problems = diagnose(a)
    print("problemas: " + ("; ".join(problems) if problems else "nenhum"))
    print(f"→ {out_path.relative_to(ROOT)}")


def main() -> None:
    site, urls = sys.argv[1], sys.argv[2:]
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n, url in enumerate(urls):
        if n:
            time.sleep(DELAY_S)
        try:
            crawl(site, url, ts)
        except Exception as exc:
            print(f"\n== {site} · {url} ==\nFALHA TÉCNICA: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
