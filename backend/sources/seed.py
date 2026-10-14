"""Fontes de arranque (Observador, JN, Público) e os seus pontos de entrada (ver docs/sites/).

Idempotente: cria o que falta, nunca altera o que existe (as cadências são editáveis pela API).
"""

from __future__ import annotations

from sources.models import EntryPoint, Site

SITES = [
    {
        "slug": "observador", "name": "Observador", "base_url": "https://observador.pt/",
        "parser_module": "observador", "min_delay_s": 1.0, "skip_premium_on_discovery": False,
        "entrypoints": [
            {"name": "sitemap-noticias", "kind": "sitemap_index", "url": "https://observador.pt/wp-sitemap.xml",
             "config": {"post_types": ["post"], "latest_per_type": 1}, "interval_s": 600},
            {"name": "sitemap-outros", "kind": "sitemap_index", "url": "https://observador.pt/wp-sitemap.xml",
             "config": {"post_types": ["obs_longform", "obs_opinion", "obs_factcheck"], "latest_per_type": 1},
             "interval_s": 1800},
            {"name": "homepage", "kind": "homepage", "url": "https://observador.pt/", "interval_s": 1200},
            {"name": "rss", "kind": "feed", "url": "https://observador.pt/feed/", "interval_s": 1800},
        ],
    },
    {
        "slug": "jn", "name": "Jornal de Notícias", "base_url": "https://www.jn.pt/",
        "parser_module": "jn", "min_delay_s": 2.0, "skip_premium_on_discovery": True,
        "entrypoints": [
            {"name": "news-sitemap", "kind": "sitemap_news", "url": "https://www.jn.pt/feed/news/sitemap.xml",
             "interval_s": 300},
            {"name": "sitemap-diario", "kind": "sitemap_daily",
             "url": "https://www.jn.pt/feed/sitemap.xml?yyyy={yyyy}&mm={mm}&dd={dd}",
             "config": {"days_back": 1}, "interval_s": 1800},
            {"name": "homepage", "kind": "homepage", "url": "https://www.jn.pt/", "interval_s": 1200},
        ],
    },
    {
        "slug": "publico", "name": "Público", "base_url": "https://www.publico.pt/",
        "parser_module": "publico", "min_delay_s": 1.0, "skip_premium_on_discovery": False,
        "entrypoints": [
            {"name": "news-sitemap", "kind": "sitemap_news", "url": "https://www.publico.pt/sitemaps/news.xml",
             "interval_s": 300},
            {"name": "homepage", "kind": "homepage", "url": "https://www.publico.pt/", "interval_s": 1200},
            {"name": "feedburner", "kind": "feed", "url": "http://feeds.feedburner.com/PublicoRSS",
             "interval_s": 1800},
        ],
    },
]


def ensure_sources() -> dict:
    created = {"sites": 0, "entrypoints": 0}
    for spec in SITES:
        spec = dict(spec)
        eps = spec.pop("entrypoints")
        site, c = Site.objects.get_or_create(slug=spec["slug"], defaults=spec)
        created["sites"] += c
        for ep in eps:
            _, c = EntryPoint.objects.get_or_create(site=site, name=ep["name"], defaults=ep)
            created["entrypoints"] += c
    _ensure_media_entities()
    return created


def _ensure_media_entities() -> None:
    """Cada meio é também uma entidade (para ligar fontes citadas 'outro meio')."""
    from entities.models import Entity, EntityAlias
    from entities.normalize import normalize

    for site in Site.objects.filter(entity__isnull=True):
        ent = Entity.objects.create(canonical_name=site.name, type="meio", is_public=True, status="active",
                                    debug={"criada_por": "seed das fontes"})
        for alias in {site.name, site.slug}:
            EntityAlias.objects.get_or_create(entity=ent, normalized=normalize(alias), defaults={"alias": alias})
        site.entity = ent
        site.save(update_fields=["entity"])
