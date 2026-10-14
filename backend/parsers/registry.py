"""Adaptador entre os parsers de cada site e o pipeline.

Os módulos `parsers/<site>.py` têm assinaturas ligeiramente diferentes (o JN aceita `base_url` e
`include_excluded` no sitemap, o Observador filtra o índice por tipo de post...). O pipeline só fala
com estas funções, que dão uma interface uniforme:

    discover(site, kind, text, url)      -> list[HomepageItem]   (homepage, sitemap, feed)
    sitemap_index(site, text, config)    -> list[str]            (URLs dos sitemaps filhos a ler)
    article(site, html, url)             -> Article
"""

from __future__ import annotations

import importlib
import inspect
import re
from types import ModuleType

from parsers.base import Article, HomepageItem, clean_article, clean_item

# Tipos de ponto de entrada que devolvem itens (o índice é tratado à parte).
ITEM_KINDS = {"homepage", "sitemap", "sitemap_news", "sitemap_daily", "feed"}


class ParserNotAvailable(Exception):
    """O site não implementa a função pedida (ex.: JN não tem parse_feed)."""


def module(site: str) -> ModuleType:
    return importlib.import_module(f"parsers.{site}")


def _call(fn, *args, **kwargs):
    """Chama `fn` passando só os kwargs que a função aceita."""
    params = inspect.signature(fn).parameters
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def discover(site: str, kind: str, text: str, url: str, include_excluded: bool = False) -> list[HomepageItem]:
    mod = module(site)
    if kind == "homepage":
        items = _call(mod.parse_homepage, text, base_url=mod.BASE_URL, include_excluded=include_excluded)
        return [clean_item(i) for i in items]
    if kind in {"sitemap", "sitemap_news", "sitemap_daily"}:
        fn = getattr(mod, "parse_sitemap", None)
    elif kind == "feed":
        fn = getattr(mod, "parse_feed", None)
    else:
        raise ValueError(f"tipo de ponto de entrada sem itens: {kind}")
    if fn is None:
        raise ParserNotAvailable(f"{site} não implementa o parser para {kind}")
    return [clean_item(i) for i in _call(fn, text, base_url=mod.BASE_URL, include_excluded=include_excluded)]


def sitemap_index(site: str, text: str, config: dict | None = None) -> list[str]:
    """URLs dos sitemaps filhos a ler nesta descoberta.

    config:
      - "post_types": tipos a considerar (Observador: wp-sitemap-posts-<tipo>-N.xml).
      - "latest_per_type": N páginas mais recentes por tipo (por omissão 1).
      - "latest": N sitemaps mais recentes, pela ordem do índice (JN/Público: o mais recente primeiro).
    """
    config = config or {}
    mod = module(site)
    fn = getattr(mod, "parse_sitemap_index", None)
    if fn is None:
        raise ParserNotAvailable(f"{site} não implementa parse_sitemap_index")
    kwargs = {}
    if config.get("post_types"):
        kwargs["post_types"] = tuple(config["post_types"])
    urls = _call(fn, text, **kwargs)
    if "latest_per_type" in config or config.get("post_types"):
        n = int(config.get("latest_per_type", 1))
        by_type: dict[str, list[tuple[int, str]]] = {}
        for u in urls:
            m = re.search(r"-([a-z_]+)-(\d+)\.xml$", u)
            if m:
                by_type.setdefault(m.group(1), []).append((int(m.group(2)), u))
        out = []
        for pages in by_type.values():
            out += [u for _, u in sorted(pages)[-n:]]
        return out
    if "latest" in config:
        return urls[: int(config["latest"])]
    return urls


def article(site: str, html: str, url: str | None) -> Article:
    # Salvaguarda do contrato: texto sem HTML, seja qual for o parser.
    return clean_article(module(site).parse_article(html, url))
