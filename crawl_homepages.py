"""Primeiro crawl às homepages (PoC).

Uso: python3 crawl_homepages.py [site ...]     (sem argumentos: todos)

Para cada site: descarrega a homepage, guarda o HTML em sites/raw/<site>_homepage_<ts>.html,
corre parse_homepage, escreve sites/out/<site>_homepage_<ts>.json e compara com a amostra
anterior (sites/out/<site>_homepage.json).
"""

from __future__ import annotations

import gzip
import importlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
# Os parsers vivem em backend/parsers/ (pacote partilhado com o Django).
sys.path.insert(0, str(ROOT / "backend"))
RAW = ROOT / "sites" / "raw"
OUT = ROOT / "sites" / "out"
SITES = ["observador", "jn", "publico"]
USER_AGENT = "FactosBot/0.1 (prova de conceito interna)"
DELAY_S = 1.0


def fetch(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "gzip",
        "Accept-Language": "pt-PT,pt;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.status, resp.geturl(), data.decode(charset, errors="replace")


def crawl(site: str, ts: str) -> None:
    mod = importlib.import_module(f"parsers.{site}")
    url = mod.BASE_URL
    started = time.monotonic()
    status, final_url, html = fetch(url)
    elapsed = time.monotonic() - started

    raw_path = RAW / f"{site}_homepage_{ts}.html"
    raw_path.write_text(html, encoding="utf-8")

    items = mod.parse_homepage(html, url)
    out_path = OUT / f"{site}_homepage_{ts}.json"
    out_path.write_text(json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2),
                        encoding="utf-8")

    key = lambda d: d.get("site_article_id") or d["url"]
    current = {key(i.to_dict()) for i in items}
    sample_path = OUT / f"{site}_homepage.json"
    previous = {key(d) for d in json.loads(sample_path.read_text(encoding="utf-8"))} if sample_path.exists() else set()

    print(f"\n== {site} ==")
    print(f"HTTP {status} {final_url} · {len(html) / 1024:.0f} KB · {elapsed:.1f}s")
    print(f"artigos no âmbito: {len(items)} · novos vs amostra: {len(current - previous)} · "
          f"saíram da homepage: {len(previous - current)}")
    no_title = sum(1 for i in items if not i.title)
    no_id = sum(1 for i in items if not i.site_article_id)
    no_date = sum(1 for i in items if not i.published_at)
    print(f"sem título: {no_title} · sem ID: {no_id} · sem data: {no_date}")
    for i in items[:5]:
        print(f"  [{i.zone}] {i.title}")
    print(f"→ {raw_path.relative_to(ROOT)} · {out_path.relative_to(ROOT)}")


def main() -> None:
    sites = sys.argv[1:] or SITES
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n, site in enumerate(sites):
        if n:
            time.sleep(DELAY_S)
        try:
            crawl(site, ts)
        except Exception as exc:  # falha técnica: regista e segue para o próximo site
            print(f"\n== {site} ==\nFALHA TÉCNICA: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
