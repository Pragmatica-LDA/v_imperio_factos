"""Ligações do corpo das notícias: normalização, classificação (âmbito e plataforma) e registo por versão.

O parser entrega só as ligações editoriais do corpo (Block.links) e os embeds (Article.embeds) — contrato v2.2.
Aqui classifica-se: interna (mesmo site), outro meio monitorizado ou externa; e a plataforma (redes sociais,
vídeo, encurtador, documento ou site).
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Domínio (ou sufixo) → plataforma. Ordem irrelevante: compara-se pelo sufixo do domínio.
PLATFORMS = {
    "facebook.com": "facebook", "fb.com": "facebook", "fb.watch": "facebook", "m.facebook.com": "facebook",
    "instagram.com": "instagram", "instagr.am": "instagram",
    "x.com": "x", "twitter.com": "x",
    "threads.net": "threads", "threads.com": "threads", "bsky.app": "bluesky",
    "youtube.com": "youtube", "youtu.be": "youtube", "vimeo.com": "vimeo",
    "tiktok.com": "tiktok", "linkedin.com": "linkedin", "lnkd.in": "linkedin",
    "t.me": "telegram", "telegram.me": "telegram", "wa.me": "whatsapp", "whatsapp.com": "whatsapp",
    "reddit.com": "reddit", "spotify.com": "spotify", "soundcloud.com": "soundcloud",
    "wikipedia.org": "wikipedia",
}
SHORTENERS = {"t.co", "bit.ly", "tinyurl.com", "ow.ly", "buff.ly", "goo.gl", "l.facebook.com", "lm.facebook.com",
              "l.instagram.com", "shorturl.at", "rebrand.ly", "is.gd"}
DOCUMENT_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".odt")
TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src", "ref_url", "s", "t", "si")


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def normalize(url: str) -> str:
    """Sem fragmento nem parâmetros de tracking; host em minúsculas."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not any(k == t or (t.endswith("_") and k.startswith(t)) for t in TRACKING)]
    return urlunsplit((parts.scheme.lower() or "https", (parts.netloc or "").lower(), parts.path or "/",
                       urlencode(query), ""))


def platform_of(url: str) -> tuple[str, bool]:
    """(plataforma, é documento)."""
    host = domain_of(url)
    path = urlsplit(url).path.lower()
    is_doc = path.endswith(DOCUMENT_EXT)
    if host in SHORTENERS:
        return "encurtador", is_doc
    for suffix, name in PLATFORMS.items():
        if _matches(host, suffix):
            return name, is_doc
    return ("documento" if is_doc else "site"), is_doc


def site_for_domain(host: str, sites: list) -> object | None:
    for site in sites:
        if _matches(host, domain_of(site.base_url)):
            return site
    return None


def classify(url: str, own_site, sites: list) -> dict:
    host = domain_of(url)
    platform, is_doc = platform_of(url)
    target_site = site_for_domain(host, sites)
    if target_site is not None and target_site.pk == own_site.pk:
        scope = "internal"
    elif target_site is not None:
        scope = "media"
    else:
        scope = "external"
    return {"domain": host, "platform": platform, "is_document": is_doc, "scope": scope, "target_site": target_site}


def iter_links(content: dict):
    """(kind, url, texto, block_index) pela ordem do corpo; embeds intercalados pelo block_index."""
    out = []
    for i, block in enumerate(content.get("body") or []):
        for link in block.get("links") or []:
            if link.get("url"):
                out.append((i, 1, "inline", link["url"], link.get("text") or ""))
    for e in content.get("embeds") or []:
        if e.get("url"):
            bi = e.get("block_index")
            out.append((bi if bi is not None else 10**6, 0, "embed", e["url"], e.get("text") or ""))
    out.sort(key=lambda x: (x[0], x[1]))
    for bi, _, kind, url, text in out:
        yield kind, url, text, (bi if bi != 10**6 else None)


def record(version) -> int:
    """(Re)cria as ligações de uma versão e liga-as às notícias que já conhecemos. Idempotente."""
    from crawl.models import ArticleLink, ArticleURL
    from sources.models import Site

    article = version.article
    sites = list(Site.objects.all())
    ArticleLink.objects.filter(version=version).delete()
    rows, seen = [], set()
    for kind, url, text, block_index in iter_links(version.content or {}):
        if not url.lower().startswith(("http://", "https://")):
            continue   # mailto:, tel:, âncoras
        norm = normalize(url)
        if (kind, norm) in seen:
            continue
        seen.add((kind, norm))
        info = classify(url, article.site, sites)
        rows.append(ArticleLink(version=version, article=article, kind=kind, position=len(rows),
                                block_index=block_index, url=url[:2000], normalized_url=norm[:2000],
                                text=text[:2000], **info))
    if not rows:
        return 0
    targets = dict(ArticleURL.objects.filter(url__in=[r.url for r in rows if r.scope != "external"]
                                             + [r.normalized_url for r in rows if r.scope != "external"])
                   .values_list("url", "article_id"))
    for r in rows:
        tid = targets.get(r.url) or targets.get(r.normalized_url)
        if tid and tid != article.pk:
            r.target_article_id = tid
    ArticleLink.objects.bulk_create(rows)
    return len(rows)
