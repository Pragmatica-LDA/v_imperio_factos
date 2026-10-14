"""Parser do Jornal de Notícias (www.jn.pt) — contrato v2.2 (parsers/base.py).

O site é uma app Next.js (App Router). Além do HTML renderizado, cada página traz o
RSC payload (`self.__next_f.push([1, "..."])`) com os objectos de conteúdo em JSON:
- homepage: slices (`{"Title", "Config", "Contents": [artigos]}`), cada artigo com
  Id, Url, Date, Author, Categories, Layout, Headline (antetítulo), Section/SectionSlug, Abstract;
- artigo: `{"dataset": {...}}` com Id, datas, Authors, Tags, Layout, Categories, WordCount e o
  corpo (`Body`) em fragmentos HTML.

Ordem de preferência: JSON-LD/meta > RSC payload > HTML. Ver docs/sites/jn.md.

Runner: python3 -m parsers.jn <homepage.html> <artigo.html> [sitemap.xml ...] [--out out_dir]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from lxml import etree

from parsers.base import (
    ACCESS_FREE,
    ACCESS_PREMIUM,
    AGENCY_GENERIC,
    PIECE_TYPES,
    Article,
    Author,
    Block,
    Embed,
    HomepageItem,
    Image,
    Link,
    to_utc_iso,
)

SITE = "jn"
BASE_URL = "https://www.jn.pt"

# --- Configuração (nada hardcoded na lógica) -------------------------------------------

HOSTS = {"www.jn.pt", "jn.pt"}
CANONICAL_HOST = "www.jn.pt"

# /<secção>[/<subsecção>]/artigo/<slug>/<id>
ARTICLE_PATH_RE = re.compile(r"^/(?P<section>[a-z0-9-]+(?:/[a-z0-9-]+)*)/artigo/(?P<slug>[a-z0-9-]+)/(?P<id>\d+)/?$")
# /amp/<id>/<slug> (versão AMP)
AMP_PATH_RE = re.compile(r"^/amp/(?P<id>\d+)/(?P<slug>[a-z0-9-]+)/?$")

# Âmbito: só peças editoriais do JN. Cada regra tem um motivo (vai para site_meta/debug).
OUT_OF_SCOPE_SECTIONS = {
    "brands-life": "patrocinado",          # Layout NG:BrandsLife
    "iniciativas": "promocional",          # Loja JN / merchandising (autor "Marketing")
    "jn-direto": "video",                  # peças de vídeo (HasVideo=True)
    "jogos-em-direto": "live",             # acompanhamento de jogos em directo (aparece no news sitemap)
    "noticias-magazine": "revista-do-grupo",
    "evasoes": "revista-do-grupo",
    "volta-ao-mundo": "revista-do-grupo",
    "delas": "revista-do-grupo",
    "jn-kids": "revista-do-grupo",
    "apostas": "promocional",
    "casino": "promocional",
}
OUT_OF_SCOPE_LAYOUTS = {"NG:BrandsLife": "patrocinado"}
# Tags/tópicos de conteúdo de parceria. "Ciência na Europa": autores estrangeiros sem página de autor
# no JN, slice alimentada por tag — tratado como parceria (heurística, ver docs/sites/jn.md).
OUT_OF_SCOPE_TAGS = {"ciencia na europa": "parceria"}
# Zonas da homepage (slug do título da slice) cujo conteúdo está todo fora de âmbito (fallback HTML).
OUT_OF_SCOPE_ZONES = {"ciencia-na-europa": "parceria", "brand-s-life": "patrocinado", "loja-jn": "promocional"}
# Assinaturas que denunciam conteúdo promocional.
OUT_OF_SCOPE_SIGNATURES = {"marketing": "promocional", "equipa de conteudo jn": "promocional"}
# Selos dos cartões HTML (fallback sem RSC).
OUT_OF_SCOPE_CARD_SELECTORS = {
    '[class*="__Sponsored"]': "patrocinado",
    '[class*="__BrandstoryStamp"]': "patrocinado",
}

# Layout.Code -> piece_type
LAYOUT_PIECE_TYPE = {
    "NG:Article": "noticia",
    "NG:Opinião": "opiniao",
    "NG:Opiniao": "opiniao",
}
# Antetítulo (Headline/PreTitle) que indica o tipo de peça. Prefixo, sem acentos, minúsculas.
HEADLINE_PIECE_TYPE = {
    "entrevista": "entrevista",
    "reportagem": "reportagem",
    "analise": "analise",
    "editorial": "editorial",
    "cronica": "cronica",
    "critica": "critica",
    "fact check": "factcheck",
    "investigacao jn": "investigacao",
}

# Assinaturas
AGENCIES = ["Lusa", "AFP", "Reuters", "EFE", "AP", "Associated Press", "Bloomberg", "ANSA", "DPA"]
GENERIC_AGENCY_RE = re.compile(r"^ag[êe]ncias?$", re.I)
# Partes institucionais de uma assinatura mista ("JN/Agências"): não são pessoas. Sem pessoas, a
# assinatura inteira passa a Author colectivo (regra v2.1).
INSTITUTIONAL_SIGNATURES = {"jn", "redacao", "jornal de noticias", "marketing", "equipa de conteudo jn"}

# Créditos de fotografia
PHOTO_CREDIT_PREFIX_RE = re.compile(r"^\s*(fotos?|fotografias?|imagem|imagens|créditos?)\s*:\s*", re.I)
IMAGE_AGENCIES = ["Global Imagens", "Lusa", "EPA", "AFP", "Reuters", "AP", "Associated Press", "Getty Images",
                  "Bloomberg", "EFE", "Shutterstock", "Unsplash", "Pexels", "D.R.", "DR"]
# Crédito de arquivo ("Nome/Arquivo", "Arquivo Global Imagens", "foto de arquivo") -> Image.is_archive
ARCHIVE_CREDIT_RE = re.compile(r"\b(arquivo|arq\.)\b", re.I)
# Media do RSC: Flags que marcam a imagem principal; "text" = imagem inserida no texto
MAIN_IMAGE_FLAGS = {"highlight", "gallery"}
# Marca HTML do paywall (o corpo é cortado a seguir)
PAYWALL_SELECTOR = '[class*="__ArticlePaywall"]'
OUT_OF_SCOPE_PREMIUM = "premium_sem_texto_integral"
IMAGE_GUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

# Corpo
BODY_KINDS = {"p": "p", "h2": "h2", "h3": "h3", "h4": "h3", "li": "li", "blockquote": "quote"}
# Case-sensitive de propósito: "Ad" não pode apanhar "Lead"/"Head".
NOISE_CLASS_RE = re.compile(
    r"(BodyAd|gpt-ad|\bads?\b|\bad-|[Rr]elated|ReadAlso|[Ll]eia-?[Tt]ambem|[Nn]ewsletter|Topics|Share|Social|Promo)"
)
NOISE_TEXT_RE = re.compile(
    r"^\s*(leia (também|mais)|ler (também|mais)|veja (também|mais)|saiba mais|relacionad[oa]s?\b|"
    r"subscreva|assine (já|o jn)|newsletter|siga o jn|clique aqui)",
    re.I,
)
# Wrappers do CMS dentro do corpo: embeds -> Article.embeds; "Leia também" -> fora (nem bloco nem link)
EMBED_DATA_TYPES = {"embed"}
RELATED_DATA_TYPES = {"articles"}
# RSC: fragmento do Body que é só uma referência a um chunk de texto ("$19" -> linha "19:T<hex>,<texto>")
RSC_REF_RE = re.compile(r"\$([0-9a-f]+)")
# Pista de plataforma pelo host do URL do embed (sufixo do host)
EMBED_PLATFORMS = {
    "instagram.com": "instagram", "x.com": "x", "twitter.com": "x", "facebook.com": "facebook",
    "fb.watch": "facebook", "youtube.com": "youtube", "youtu.be": "youtube", "youtube-nocookie.com": "youtube",
    "tiktok.com": "tiktok", "vimeo.com": "vimeo", "spotify.com": "spotify", "soundcloud.com": "soundcloud",
    "threads.net": "threads", "bsky.app": "bluesky", "dailymotion.com": "dailymotion",
}
# Parâmetros de tracking/player removidos do URL do embed (o resto do query string fica)
EMBED_DROP_PARAMS_RE = re.compile(r"^(utm_.*|ref_src|ref_url|si|igsh|igshid|feature|t)$")
# Texto fixo dos widgets (não é legenda)
EMBED_BOILERPLATE_RE = re.compile(
    r"^(ver esta publicação no instagram|view this post on instagram|uma publicação partilhada por .*|"
    r"a post shared by .*)$",
    re.I,
)
# body_complete: corpo extraído >= este rácio do WordCount declarado pelo site.
# O WordCount do JN conta o source do corpo (markup, embeds, lead), por isso vem inflacionado e de forma
# irregular (ex.: 219 palavras reais vs 949 com um embed do Instagram). Só decide em artigos premium;
# em artigos free sem caixa de paywall o corpo é integral e o rácio fica só como nota de debug.
BODY_COMPLETE_MIN_RATIO = 0.9


# --- Utilitários --------------------------------------------------------------------------

def _fold(text: str | None) -> str:
    """Minúsculas, sem acentos, espaços normalizados (para comparar rótulos)."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def _slug(text: str | None) -> str | None:
    s = re.sub(r"[^a-z0-9]+", "-", _fold(text).replace("+", "mais-")).strip("-")
    return s or None


def normalize_url(href: str, base_url: str = BASE_URL) -> str | None:
    """URL absoluto, host canónico, sem query/fragmento nem barras duplicadas."""
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    parts = urlsplit(urljoin(base_url, href.strip()))
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc.lower()
    if host in HOSTS:
        host = CANONICAL_HOST
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit(("https", host, path, "", ""))


def match_article_url(url: str | None) -> re.Match | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.netloc not in HOSTS:
        return None
    return ARTICLE_PATH_RE.match(parts.path)


def extract_id(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    m = ARTICLE_PATH_RE.match(parts.path) or AMP_PATH_RE.match(parts.path)
    return m.group("id") if m else None


def _top_section(url: str | None) -> str | None:
    m = match_article_url(url)
    return m.group("section").split("/")[0] if m else None


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()
    return text or None


def _rsc_text(html: str) -> str:
    """Concatena as strings do RSC payload do Next.js."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)', html, re.S)
    out = []
    for c in chunks:
        try:
            out.append(json.loads(c))
        except json.JSONDecodeError:
            continue
    return "".join(out)


def _rsc_text_chunk(rsc: str, ref: str) -> str | None:
    """Resolve uma referência "$<id>" do RSC para o chunk de texto `<id>:T<len hex>,<texto>`."""
    m = re.search(rf"(?:^|\n){re.escape(ref)}:T([0-9a-f]+),", rsc)
    if not m:
        return None
    return rsc[m.end():].encode("utf-8")[: int(m.group(1), 16)].decode("utf-8", errors="ignore")


def _rsc_objects(rsc: str, start_pattern: str) -> list[dict]:
    dec = json.JSONDecoder()
    objs = []
    for m in re.finditer(start_pattern, rsc):
        try:
            obj, _ = dec.raw_decode(rsc, m.start())
        except json.JSONDecodeError:
            continue
        objs.append(obj)
    return objs


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    items = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except json.JSONDecodeError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict):
                items.extend(d["@graph"] if isinstance(d.get("@graph"), list) else [d])
    return items


def _meta(soup: BeautifulSoup, key: str) -> str | None:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return _clean(tag.get("content")) if tag else None


# --- Regras partilhadas (homepage e artigo) -----------------------------------------------

def _split_names(text: str) -> list[str]:
    """'A, B e C' -> [A, B, C]; não parte apelidos compostos ('Menezes e Sousa')."""
    names: list[str] = []
    for chunk in re.split(r"\s*,\s*", text):
        pieces = re.split(r"\s+e\s+", chunk)
        merged: list[str] = []
        for p in pieces:
            bare = re.sub(r"\([^)]*\)", "", p).strip()
            if merged and len(bare.split()) < 2:   # "Sousa (TSF)" é continuação do nome anterior
                merged[-1] = f"{merged[-1]} e {p}"
            else:
                merged.append(p)
        names.extend(merged)
    return [n for n in (_clean(n) for n in names) if n]


def parse_signature(signature: str | None) -> tuple[list[Author], list[str], list[str]]:
    """Assinatura -> (autores, agências, notas). Regras v2.1:

    'Ana Silva/Lusa'  -> [Author('Ana Silva')], ['Lusa']
    'JN/Agências'     -> [Author('JN/Agências')], [AGENCY_GENERIC]   (assinatura colectiva)
    'Redação'         -> [Author('Redação')], []
    'AFP'             -> [Author('AFP')], ['AFP']
    'A (JN) e B (TSF)' -> [Author('A', affiliation='JN'), Author('B', affiliation='TSF')]
    """
    sig = _clean(signature)
    authors: list[Author] = []
    agencies: list[str] = []
    notes: list[str] = []
    for part in (p.strip() for p in (sig or "").split("/")):
        if not part:
            continue
        agency = next((a for a in AGENCIES if _fold(part) == _fold(a)), None)
        if agency:
            agencies.append(agency)
        elif GENERIC_AGENCY_RE.match(part):
            agencies.append(AGENCY_GENERIC)
        elif _fold(part) in INSTITUTIONAL_SIGNATURES:
            continue
        else:
            for n in _split_names(part):
                m = re.match(r"^(?P<name>.*?)\s*\((?P<aff>[^)]+)\)\s*$", n)
                name, aff = (_clean(m["name"]), _clean(m["aff"])) if m else (n, None)
                if name:
                    authors.append(Author(name=name, affiliation=aff))
    if not authors and sig:
        # sem pessoas: a assinatura colectiva é o autor
        authors = [Author(name=sig)]
        notes.append(f"assinatura colectiva '{sig}'")
    return authors, list(dict.fromkeys(agencies)), notes


def _authors_from_signatures(entries: list[dict]) -> tuple[list[Author], list[str], list[str], str | None]:
    """entries: [{"signature", "url"}] -> (authors, agencies, notes, byline_raw)."""
    authors: list[Author] = []
    agencies: list[str] = []
    notes: list[str] = []
    for e in entries:
        auths, ags, ns = parse_signature(e.get("signature"))
        # a página de autor (/autor/<slug>) é da assinatura inteira: só a atribuímos se houver um único autor
        if e.get("url") and len(auths) == 1:
            auths[0].url = normalize_url(e["url"])
        authors.extend(auths)
        agencies.extend(ags)
        notes.extend(ns)
    seen: set[str] = set()
    authors = [a for a in authors if not (a.name in seen or seen.add(a.name))]
    byline = ", ".join(dict.fromkeys(_clean(e.get("signature")) for e in entries if _clean(e.get("signature"))))
    return authors, list(dict.fromkeys(agencies)), notes, byline or None


def _piece_type(layout: dict | None, headline: str | None, section: str | None) -> tuple[str | None, str | None, str]:
    """-> (piece_type, piece_type_raw, fonte)."""
    layout = layout or {}
    code = layout.get("Code")
    raw = code
    head = _fold(headline)
    if layout.get("Opinion"):
        return "opiniao", raw, "rsc:Layout.Opinion"
    for prefix, pt in HEADLINE_PIECE_TYPE.items():
        if head.startswith(prefix):
            return pt, f"{code} | antetítulo: {_clean(headline)}", "rsc:Headline (heurística antetítulo)"
    if code in LAYOUT_PIECE_TYPE:
        return LAYOUT_PIECE_TYPE[code], raw, "rsc:Layout.Code"
    if section == "opiniao":
        return "opiniao", raw or "url:/opiniao", "url"
    return None, raw, "rsc:Layout.Code (sem mapeamento)" if raw else "none"


def _access(categories: list | None, layout: dict | None) -> str | None:
    if categories is None and layout is None:
        return None
    premium = bool((layout or {}).get("Premium")) or any(
        isinstance(c, dict) and c.get("Premium") for c in categories or []
    )
    return ACCESS_PREMIUM if premium else ACCESS_FREE


def out_of_scope_reason(
    url: str | None,
    layout_code: str | None = None,
    section_slug: str | None = None,
    tags: list[str] | None = None,
    signatures: list[str] | None = None,
) -> str | None:
    """Motivo pelo qual a peça está fora de âmbito, ou None."""
    # ordem: marcas mais específicas primeiro (um patrocinado publicado numa revista é "patrocinado")
    if layout_code in OUT_OF_SCOPE_LAYOUTS:
        return f"{OUT_OF_SCOPE_LAYOUTS[layout_code]}:layout {layout_code}"
    if section_slug in OUT_OF_SCOPE_SECTIONS:
        return f"{OUT_OF_SCOPE_SECTIONS[section_slug]}:SectionSlug {section_slug}"
    top = _top_section(url)
    if top in OUT_OF_SCOPE_SECTIONS:
        return f"{OUT_OF_SCOPE_SECTIONS[top]}:secção {top}"
    for t in tags or []:
        if _fold(t) in OUT_OF_SCOPE_TAGS:
            return f"{OUT_OF_SCOPE_TAGS[_fold(t)]}:tag {t}"
    for s in signatures or []:
        if _fold(s) in OUT_OF_SCOPE_SIGNATURES:
            return f"{OUT_OF_SCOPE_SIGNATURES[_fold(s)]}:assinatura {s}"
    return None


# --- Homepage -----------------------------------------------------------------------------

def _homepage_item(obj: dict, url: str, zone: str | None, rank: int) -> HomepageItem:
    aid = extract_id(url)
    section = _top_section(url)
    sub_slug = obj.get("SectionSlug") or None
    author = obj.get("Author") or {}
    authors, agencies, notes, byline = _authors_from_signatures(
        [{"signature": author.get("Signature") or author.get("Name"), "url": author.get("Url")}] if author else []
    )
    piece, piece_raw, piece_src = _piece_type(obj.get("Layout"), obj.get("Headline"), section)
    published = to_utc_iso(obj.get("Date"))
    item = HomepageItem(
        url=url,
        site_article_id=aid,
        title=_clean(obj.get("Title")),
        lead=_clean(obj.get("Abstract")),
        authors=authors,
        agencies=agencies,
        byline_raw=byline,
        section=section,
        subsection=sub_slug if sub_slug and sub_slug != section else None,
        published_at=published,
        published_at_precision="datetime" if published else None,
        access=_access(obj.get("Categories"), obj.get("Layout")),
        piece_type=piece,
        piece_type_raw=piece_raw,
        zone=zone,
        zones=[zone] if zone else [],
        rank=rank,
        site_meta={
            "headline": _clean(obj.get("Headline")),
            "section_name": _clean(obj.get("Section")),
            "layout_code": (obj.get("Layout") or {}).get("Code"),
            "categories": [c.get("Code") for c in obj.get("Categories") or [] if isinstance(c, dict)],
            "has_video": obj.get("HasVideo"),
            "has_audio": obj.get("HasAudio"),
            "picture_guid": (obj.get("Picture") or {}).get("Guid"),
        },
    )
    debug = {
        "url": "rsc:Url (normalizado)",
        "site_article_id": "url",
        "title": "rsc:Title",
        "lead": "rsc:Abstract",
        "authors": "rsc:Author.Signature (+Author.Url)",
        "agencies": "rsc:Author.Signature",
        "byline_raw": "rsc:Author.Signature",
        "section": "url",
        "subsection": "rsc:SectionSlug",
        "published_at": "rsc:Date -> UTC",
        "published_at_precision": "rsc:Date (ISO com hora e fuso)",
        "access": "rsc:Categories[].Premium / Layout.Premium",
        "piece_type": piece_src,
        "piece_type_raw": "rsc:Layout.Code",
        "zone": "rsc:slice Config.Code/Title",
        "zones": "rsc:slices onde o Id aparece",
        "rank": "ordem de 1.ª aparição nas slices do RSC (conta também os excluídos)",
    }
    item.extraction_debug = {k: v for k, v in debug.items() if getattr(item, k) not in (None, [], "")}
    if notes:
        item.extraction_debug["notas"] = "; ".join(notes)
    return item


def parse_homepage(html: str, base_url: str = BASE_URL, include_excluded: bool = False) -> list[HomepageItem]:
    rsc = _rsc_text(html)

    # 1) RSC: slices por ordem -> (zona, artigo)
    entries: list[tuple[str | None, dict]] = []
    seen_ids: set[int] = set()
    for sl in _rsc_objects(rsc, r'\{"Title":"(?:[^"\\]|\\.)*","Page":'):
        cfg = sl.get("Config") or {}
        zone = _slug(cfg.get("Code") or sl.get("Title"))
        slice_tags = cfg.get("Tags") or []
        for obj in sl.get("Contents") or []:
            if isinstance(obj, dict) and obj.get("Type") == "Article":
                entries.append((zone, {**obj, "_slice_tags": slice_tags}))
                seen_ids.add(obj.get("Id"))
    # artigos fora de slices (não esperado, mas não se perdem)
    for obj in _rsc_objects(rsc, r'\{"Id":\d+,"Type":"Article"'):
        if obj.get("Id") not in seen_ids:
            entries.append((None, obj))
            seen_ids.add(obj.get("Id"))

    # 1.ª passagem: o que estiver fora de âmbito em qualquer slice fica fora em todas
    rejected: dict[str, str] = {}
    for _, obj in entries:
        url = normalize_url(obj.get("Url") or "", base_url)
        if not match_article_url(url):
            continue
        sig = (obj.get("Author") or {}).get("Signature")
        reason = out_of_scope_reason(
            url, (obj.get("Layout") or {}).get("Code"), obj.get("SectionSlug"),
            obj.get("_slice_tags"), [sig] if sig else None,
        )
        if reason:
            rejected.setdefault(extract_id(url), reason)

    items: dict[str, HomepageItem] = {}
    for zone, obj in entries:
        url = normalize_url(obj.get("Url") or "", base_url)
        aid = extract_id(url) if match_article_url(url) else None
        if not aid:
            continue
        if aid in items:
            if zone and zone not in items[aid].zones:
                items[aid].zones.append(zone)
            continue
        items[aid] = _homepage_item(obj, url, zone, len(items))
        if aid in rejected:
            items[aid].excluded_reason = rejected[aid]

    # 2) HTML: cartões <article> dentro de <main> que não vieram no RSC (fallback)
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup
    for a in main.select("article a[href]"):
        url = normalize_url(a["href"], base_url)
        if not match_article_url(url):
            continue
        aid = extract_id(url)
        if aid in items:
            continue
        reason = out_of_scope_reason(url)
        card = a.find_parent("article")
        for sel, why in OUT_OF_SCOPE_CARD_SELECTORS.items():
            if not reason and card.select_one(sel):
                reason = f"{why}:selo {sel}"
        sec = card.find_parent("section")
        zone_el = sec.select_one("header h2") if sec else None
        zone = _slug(zone_el.get_text(" ")) if zone_el else None
        if not reason and zone in OUT_OF_SCOPE_ZONES:
            reason = f"{OUT_OF_SCOPE_ZONES[zone]}:zona {zone}"
        h = card.find(["h2", "h3", "h4"])
        premium = card.select_one('[class*="__Exclusive"]') is not None
        items[aid] = HomepageItem(
            url=url,
            site_article_id=aid,
            title=(_clean(h.get_text(" ")) if h else None) or _clean(a.get_text(" ")),
            section=_top_section(url),
            access=ACCESS_PREMIUM if premium else None,
            piece_type="opiniao" if _top_section(url) == "opiniao" else None,
            zone=zone,
            zones=[zone] if zone else [],
            rank=len(items),
            excluded_reason=reason,
            extraction_debug={
                "url": "html:main article a[href]", "site_article_id": "url", "title": "html:article h2",
                "section": "url", "zone": "html:section header h2", "zones": "html:section header h2",
                "rank": "ordem do HTML",
                **({"access": "html:selo __Exclusive"} if premium else {}),
                **({"piece_type": "url"} if _top_section(url) == "opiniao" else {}),
            },
        )

    out = list(items.values())
    return out if include_excluded else [i for i in out if not i.excluded_reason]


# --- Sitemaps -----------------------------------------------------------------------------
# Índice:  https://www.jn.pt/feed/sitemap.xml -> um sitemap por dia (?yyyy=&mm=&dd=), desde 2004-06-01.
# Diário:  <url><loc><lastmod><changefreq> (sem título).  News: <news:publication_date>, <news:title>,
#          <news:keywords>, <news:genres>Opinion</news:genres>; janela de ~48h.

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
              "news": "http://www.google.com/schemas/sitemap-news/0.9"}
NEWS_GENRE_PIECE_TYPE = {"opinion": "opiniao", "oped": "opiniao"}


def _xml_root(xml: str | bytes):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    return etree.fromstring(data, parser)


def parse_sitemap_index(xml: str | bytes) -> list[str]:
    """URLs dos sitemaps filhos (por ordem do índice: o mais recente primeiro)."""
    root = _xml_root(xml)
    return [t.strip() for t in root.xpath("//sm:sitemap/sm:loc/text()", namespaces=SITEMAP_NS) if t.strip()]


def parse_sitemap(xml: str | bytes, base_url: str = BASE_URL, include_excluded: bool = False) -> list[HomepageItem]:
    """Sitemap diário ou news sitemap -> HomepageItem (mesmas regras de URL, ID e âmbito)."""
    root = _xml_root(xml)
    items: dict[str, HomepageItem] = {}
    for u in root.xpath("//sm:url", namespaces=SITEMAP_NS):
        loc = (u.findtext("sm:loc", namespaces=SITEMAP_NS) or "").strip()
        url = normalize_url(loc, base_url)
        if not match_article_url(url):
            continue
        aid = extract_id(url)
        if aid in items:
            continue
        news_pub = u.findtext("news:news/news:publication_date", namespaces=SITEMAP_NS)
        title = u.findtext("news:news/news:title", namespaces=SITEMAP_NS)
        keywords = u.findtext("news:news/news:keywords", namespaces=SITEMAP_NS)
        genres = u.findtext("news:news/news:genres", namespaces=SITEMAP_NS)
        lastmod = u.findtext("sm:lastmod", namespaces=SITEMAP_NS)
        section = _top_section(url)
        piece = next((NEWS_GENRE_PIECE_TYPE[g] for g in (_fold(x) for x in (genres or "").split(","))
                      if g in NEWS_GENRE_PIECE_TYPE), None)
        if not piece and section == "opiniao":
            piece = "opiniao"
        published = to_utc_iso(news_pub)
        item = HomepageItem(
            url=url,
            site_article_id=aid,
            title=_clean(title),
            section=section,
            published_at=published,
            published_at_precision="datetime" if published else None,
            piece_type=piece,
            piece_type_raw=_clean(genres),
            excluded_reason=out_of_scope_reason(url),
            site_meta={
                "keywords": [k.strip() for k in (keywords or "").split(",") if k.strip()],
                "lastmod": to_utc_iso(lastmod),
                "changefreq": _clean(u.findtext("sm:changefreq", namespaces=SITEMAP_NS)),
            },
        )
        debug = {"url": "sitemap:loc", "site_article_id": "url", "section": "url",
                 "title": "news:title", "published_at": "news:publication_date -> UTC",
                 "published_at_precision": "news:publication_date",
                 "piece_type": "news:genres" if genres else "url", "piece_type_raw": "news:genres"}
        item.extraction_debug = {k: v for k, v in debug.items() if getattr(item, k) not in (None, [], "")}
        if lastmod and not news_pub:
            item.extraction_debug["notas"] = ("lastmod em site_meta: igual à publicação (ao minuto) nos 55 "
                                              "casos cruzados com a homepage; não confirmado se muda com edições")
        items[aid] = item
    out = list(items.values())
    return out if include_excluded else [i for i in out if not i.excluded_reason]


# --- Imagens ------------------------------------------------------------------------------

def parse_photo_credit(credit: str | None) -> tuple[list[str], str | None, bool]:
    """Crédito -> (fotógrafos, agência, is_archive).

    'Foto: Rui Oliveira/Global Imagens' -> (['Rui Oliveira'], 'Global Imagens', False)
    'Lusa/EPA' -> ([], 'Lusa/EPA', False);  'Foto: Rui Oliveira/Arquivo' -> (['Rui Oliveira'], None, True)
    """
    text = _clean(PHOTO_CREDIT_PREFIX_RE.sub("", credit or ""))
    if not text:
        return [], None, False
    is_archive = bool(ARCHIVE_CREDIT_RE.search(text))
    photographers: list[str] = []
    agencies: list[str] = []
    for part in (p.strip() for p in re.split(r"\s*[/|]\s*", text)):
        part = _clean(re.sub(r"\(?\b(?:foto\s+de\s+)?(?:arquivo|arq\.)\)?", "", part, flags=re.I)) or ""
        ag = next((a for a in IMAGE_AGENCIES if _fold(part) == _fold(a)), None)
        if ag:
            agencies.append(ag)
        elif part:
            photographers.extend(_split_names(part))
    return list(dict.fromkeys(photographers)), "/".join(dict.fromkeys(agencies)) or None, is_archive


def _image(url: str, caption: str | None, credit: str | None, is_main: bool) -> Image:
    photographers, agency, is_archive = parse_photo_credit(credit)
    return Image(url=url, caption=_clean(caption), photographers=photographers, credit_raw=_clean(credit),
                 agency=agency, is_main=is_main, is_archive=is_archive)


def _guid(url: str | None) -> str | None:
    m = IMAGE_GUID_RE.search(url or "")
    return m.group(1) if m else None


def _figure_images(root: Tag) -> list[tuple[str, str | None, str | None]]:
    """(url, legenda, crédito) de cada <figure> com <img> e <figcaption> (último <p> com 'Foto:' é o crédito)."""
    out = []
    for fig in root.find_all("figure"):
        img = fig.find("img")
        if not img or not (img.get("src") or "").startswith("http"):
            continue
        cap_el = fig.find("figcaption")
        caption = credit = None
        if cap_el:
            parts = [t for t in (_clean(p.get_text(" ")) for p in cap_el.find_all(["p", "span"]) or [cap_el]) if t]
            for t in parts:
                if PHOTO_CREDIT_PREFIX_RE.match(t) and credit is None:
                    credit = t
                elif caption is None:
                    caption = t
        url = re.sub(r"&w=\d+$", "", img["src"])
        out.append((url, caption or _clean(img.get("alt")), credit))
    return out


def _images(soup: BeautifulSoup, ld: dict, ds: dict, body_root: Tag | None) -> tuple[list[Image], str | None]:
    images: list[Image] = []
    src = None
    notes: list[str] = []
    ld_img = ld.get("image")
    ld_img = ld_img[0] if isinstance(ld_img, list) and ld_img else ld_img
    ld_url = ld_img.get("url") if isinstance(ld_img, dict) else ld_img if isinstance(ld_img, str) else None

    media = [m for m in ds.get("Media") or [] if isinstance(m, dict) and m.get("MediaType") == "image" and m.get("Url")]
    if media:
        for i, m in enumerate(media):
            url = m["Url"]
            # imagem principal: preferir o JPEG do JSON-LD quando é a mesma (mesmo GUID)
            if i == 0 and ld_url and _guid(ld_url) == (m.get("Guid") or _guid(url)):
                url = ld_url
            images.append(_image(url, m.get("Caption"), m.get("Producer"), is_main=(i == 0)))
            flags = {str(f).lower() for f in m.get("Flags") or []}
            if not _clean(m.get("Producer")):
                where = "imagem inserida no texto (Flags=text)" if "text" in flags else f"Flags={sorted(flags)}"
                notes.append(f"Media[{i}] sem crédito nem legenda no RSC: {where}"
                             + ("; não desenhada no HTML (corpo cortado pelo paywall?)"
                                if m.get("Guid") and m["Guid"] not in str(soup.select_one("main") or "") else ""))
        src = "rsc:dataset.Media[] (Caption, Producer)" + (" + jsonld:image.url" if ld_url else "")
    else:
        pic = soup.select_one('main [class*="__AGPic"]')
        figs = _figure_images(pic) if pic else []
        if figs:
            url, cap, cred = figs[0]
            images.append(_image(ld_url if ld_url and _guid(ld_url) == _guid(url) else url, cap, cred, True))
            src = 'html:[class*="__AGPic"] figure/figcaption'
        elif ld_url:
            images.append(Image(url=ld_url, is_main=True))
            src = "jsonld:image.url (sem legenda/crédito)"
    # imagens do corpo
    seen = {_guid(i.url) or i.url for i in images}
    for url, cap, cred in _figure_images(body_root) if body_root is not None else []:
        if (_guid(url) or url) in seen:
            continue
        seen.add(_guid(url) or url)
        images.append(_image(url, cap, cred, False))
        src = (src + " + " if src else "") + "corpo: figure/figcaption"
        if not cred:
            notes.append(f"imagem do corpo sem crédito: {url}")
    if notes and src:
        src += " | FALHA DE CRÉDITO: " + "; ".join(notes)
    return images, src


# --- Artigo -------------------------------------------------------------------------------

def _is_noise(el: Tag) -> bool:
    for node in [el, *el.parents]:
        if not isinstance(node, Tag) or node.name in ("body", "html", "[document]"):
            break
        if node.get("data-type") in EMBED_DATA_TYPES | RELATED_DATA_TYPES:
            return True
        attrs = " ".join(node.get("class", [])) + " " + (node.get("id") or "")
        if NOISE_CLASS_RE.search(attrs) or node.has_attr("data-article-body-pub"):
            return True
        if node.name in ("aside", "nav", "figure", "figcaption", "form", "iframe", "script", "style"):
            return True
    return False


def _platform(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    return next((p for h, p in EMBED_PLATFORMS.items() if host == h or host.endswith("." + h)), None)


def _clean_embed_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, vs in parse_qs(parts.query, keep_blank_values=True).items() for v in vs
             if not EMBED_DROP_PARAMS_RE.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _embed(el: Tag) -> tuple[Embed | None, str]:
    """Embed do CMS (div[data-type=embed]) -> URL do conteúdo original, plataforma e legenda."""
    url, src, text = None, None, None
    if (ig := el.select_one("[data-instgrm-permalink]")) is not None:
        url, src = ig["data-instgrm-permalink"], "instagram:data-instgrm-permalink"
        lines = [_clean(p.get_text(" ")) for p in ig.find_all("p")]
        text = " ".join(t for t in lines if t and not EMBED_BOILERPLATE_RE.match(t)) or None
    elif (tw := el.select_one("blockquote.twitter-tweet")) is not None:
        status = [a["href"] for a in tw.find_all("a", href=True) if "/status/" in a["href"]]
        url, src = (status[-1] if status else None), "x:blockquote.twitter-tweet a[href*=/status/]"
        text = _clean(tw.p.get_text(" ")) if tw.p else None
    elif (bq := el.select_one("blockquote[cite]")) is not None:   # TikTok e outros widgets com cite
        url, src = bq["cite"], "blockquote[cite]"
    elif (fr := el.select_one("iframe[src]")) is not None:
        url, src = fr["src"], "iframe[src]"
        parts = urlsplit(urljoin(BASE_URL, url))
        host = parts.hostname or ""
        if host.endswith("facebook.com") and "/plugins/" in parts.path:
            url, src = (parse_qs(parts.query).get("href") or [url])[0], "iframe[src] facebook plugins ?href="
        elif _platform(url) == "youtube" and (m := re.match(r"/embed/([\w-]{6,})", parts.path)):
            url, src = f"https://www.youtube.com/watch?v={m.group(1)}", "iframe[src] youtube /embed/<id>"
        elif host == "player.vimeo.com" and (m := re.match(r"/video/(\d+)", parts.path)):
            url, src = f"https://vimeo.com/{m.group(1)}", "iframe[src] player.vimeo.com/video/<id>"
    elif (a := el.find("a", href=True)) is not None:
        url, src = a["href"], "a[href] (heurística)"
    if not url:
        return None, "embed sem URL"
    url = urljoin(BASE_URL, url.strip())
    if not url.startswith(("http://", "https://")):
        return None, "embed sem URL http"
    url = _clean_embed_url(url)
    return Embed(url=url, platform=_platform(url), text=text), src


def _blocks(root: Tag, embeds: list[Embed] | None = None, embed_srcs: list[str] | None = None) -> list[Block]:
    """Blocos do corpo por ordem; com `embeds`, recolhe também os embeds (block_index = bloco seguinte)."""
    out: list[Block] = []
    targets = lambda t: t.name in BODY_KINDS or t.get("data-type") in EMBED_DATA_TYPES  # noqa: E731
    for el in root.find_all(targets):
        if el.get("data-type") in EMBED_DATA_TYPES:
            if embeds is not None and el.find_parent(attrs={"data-type": list(EMBED_DATA_TYPES)}) is None:
                emb, esrc = _embed(el)
                if emb:
                    emb.block_index = len(out)
                    embeds.append(emb)
                if embed_srcs is not None:
                    embed_srcs.append(esrc)
            continue
        outer = el.find_parent(list(BODY_KINDS))   # <p> dentro de <blockquote>/<li> conta uma vez
        if outer is not None and root in outer.parents:
            continue
        if _is_noise(el):
            continue
        text = _clean(el.get_text(" "))
        if not text or NOISE_TEXT_RE.match(text):
            continue
        text = re.sub(r"\s+([,.;:!?»)])", r"\1", text)
        links = []
        for a in el.find_all("a", href=True):
            href = urljoin(BASE_URL, a["href"].strip())
            if href.startswith(("http://", "https://")) and _clean(a.get_text(" ")):
                links.append(Link(text=_clean(a.get_text(" ")), url=href))
        out.append(Block(kind=BODY_KINDS[el.name], text=text, links=links))
    return out


def _trailing_agency(blocks: list[Block]) -> str | None:
    """Agência no fecho do corpo: '(Lusa)', 'Com Lusa', '— AFP'."""
    if not blocks:
        return None
    tail = blocks[-1].text[-60:]
    for ag in AGENCIES:
        if re.search(rf"(\(|\bcom |— |- )\s*{re.escape(ag)}\)?\.?\s*$", tail, re.I):
            return ag
    return None


def parse_article(html: str, url: str | None = None) -> Article:
    soup = BeautifulSoup(html, "lxml")
    art = Article(url=normalize_url(url) if url else None)
    dbg: dict[str, str] = {}

    ld = next((d for d in _jsonld(soup) if d.get("@type") in (
        "NewsArticle", "Article", "ReportageNewsArticle", "OpinionNewsArticle", "AnalysisNewsArticle")), {})
    ds: dict = {}
    rsc = _rsc_text(html)
    for obj in _rsc_objects(rsc, r'\{"dataset":'):
        if isinstance(obj.get("dataset"), dict) and "Body" in obj["dataset"]:
            ds = obj["dataset"]
            break

    # URL / ID / aliases
    canon = soup.find("link", rel="canonical")
    for src, val in (("html:link[rel=canonical]", canon.get("href") if canon else None), ("jsonld:url", ld.get("url")),
                     ("meta:og:url", _meta(soup, "og:url")), ("rsc:Url", ds.get("Url"))):
        if val:
            art.canonical_url, dbg["canonical_url"] = normalize_url(val), src
            break
    for src, val in (("url canónico", art.canonical_url), ("url pedido", art.url)):
        if extract_id(val):
            art.site_article_id, dbg["site_article_id"] = extract_id(val), src
            break
    else:
        if ds.get("Id"):
            art.site_article_id, dbg["site_article_id"] = str(ds["Id"]), "rsc:Id"
    amp = soup.find("link", rel="amphtml")
    aliases = [normalize_url(amp.get("href"))] if amp and amp.get("href") else []
    aliases += [normalize_url(ds.get(k)) for k in ("UrlApp", "UrlAppfb") if ds.get(k)]
    if art.url and art.url != art.canonical_url:
        aliases.append(art.url)
    art.aliases = [a for a in dict.fromkeys(aliases) if a and a != art.canonical_url]
    if art.aliases:
        dbg["aliases"] = "html:link[rel=amphtml] + rsc:UrlApp/UrlAppfb"

    # Título e lead
    h1 = soup.select_one("main h1")
    for src, val in (("jsonld:headline", ld.get("headline")), ("rsc:Title", ds.get("Title")),
                     ("html:main h1", h1.get_text(" ") if h1 else None), ("meta:og:title", _meta(soup, "og:title"))):
        if _clean(val):
            art.title, dbg["title"] = _clean(val), src
            break
    lead_el = soup.select_one('main [class*="__AGLead"]')
    for src, val in (("jsonld:description", ld.get("description")), ("rsc:Abstract", ds.get("Abstract")),
                     ('html:[class*="__AGLead"]', lead_el.get_text(" ") if lead_el else None)):
        if _clean(val):
            art.lead, dbg["lead"] = _clean(val), src
            break

    # Corpo: JSON-LD articleBody (se existir) > RSC Body (fragmentos HTML) > HTML renderizado
    if _clean(ld.get("articleBody")):
        art.body = [Block(kind="p", text=t) for t in (_clean(x) for x in ld["articleBody"].split("\n")) if t]
        art.body_source, dbg["body"] = "jsonld", "jsonld:articleBody"
    body_root: Tag | None = None
    if isinstance(ds.get("Body"), list):
        frags, refs = [], 0
        for x in ds["Body"]:
            if not isinstance(x, str):
                continue
            if m := RSC_REF_RE.fullmatch(x):   # embeds longos vêm num chunk de texto à parte
                x, refs = _rsc_text_chunk(rsc, m.group(1)) or "", refs + 1
            frags.append(x)
        body_root = BeautifulSoup("<div>" + "".join(frags) + "</div>", "lxml").div
    else:
        body_root = soup.select_one('main [class*="__AGBodyContent"]')
    embeds: list[Embed] = []
    embed_srcs: list[str] = []
    if not art.body and isinstance(ds.get("Body"), list):
        art.body = _blocks(body_root, embeds, embed_srcs)
        if art.body:
            art.body_source, dbg["body"] = "rsc", "rsc:dataset.Body (sem div.ArticlePageBodyAd, embeds, \"Leia também\")"
            if embed_srcs:
                dbg["embeds"] = f"rsc:dataset.Body div[data-type=embed] ({refs} via $ref) -> " + "; ".join(embed_srcs)
    if not art.body:
        container = soup.select_one('main [class*="__AGBodyContent"]')
        if container:
            embeds, embed_srcs = [], []
            art.body = _blocks(container, embeds, embed_srcs)
            if art.body:
                art.body_source, dbg["body"] = "html", 'html:[class*="__AGBodyContent"]'
                if embed_srcs:
                    dbg["embeds"] = "html:div[data-type=embed] -> " + "; ".join(embed_srcs)
    elif art.body_source == "jsonld" and body_root is not None:
        _blocks(body_root, embeds, embed_srcs)   # articleBody não tem embeds: posição aproximada pelo RSC/HTML
        if embed_srcs:
            dbg["embeds"] = "rsc/html div[data-type=embed] (block_index aproximado: corpo do JSON-LD) -> " + "; ".join(embed_srcs)
    art.embeds = embeds
    n_links = sum(len(b.links) for b in art.body)
    if n_links:
        dbg["links"] = f"{n_links} links inline (a[href] nos blocos do corpo; fora: embeds, \"Leia também\", publicidade)"
    if art.body:
        art.word_count = sum(len(b.text.split()) for b in art.body)
        dbg["word_count"] = "contagem do corpo extraído"

    # Imagens (principal + corpo) com créditos
    art.images, isrc = _images(soup, ld, ds, body_root)
    if art.images:
        dbg["images"] = isrc

    # Autores e agências: RSC Authors (estruturado) > JSON-LD author > HTML > meta author
    entries: list[dict] = []
    src = None
    if ds.get("Authors"):
        entries = [{"signature": a.get("Signature") or a.get("Name"), "url": a.get("Url")} for a in ds["Authors"]]
        src = "rsc:Authors[].Signature"
    elif ld.get("author"):
        la = ld["author"] if isinstance(ld["author"], list) else [ld["author"]]
        entries = [{"signature": a.get("name"), "url": a.get("url")} if isinstance(a, dict) else {"signature": str(a)}
                   for a in la]
        src = "jsonld:author[].name"
    else:
        els = soup.select('main [class*="__AGAuthorLink"]')
        entries = [{"signature": _clean(e.get_text(" ")), "url": e.get("href")} for e in els]
        src = 'html:[class*="__AGAuthorLink"]'
        if not entries and _meta(soup, "author"):
            entries, src = [{"signature": _meta(soup, "author")}], "meta:author"
    authors, agencies, notes, art.byline_raw = _authors_from_signatures(entries)
    signatures = [e["signature"] for e in entries if e.get("signature")]
    art.authors = authors
    if authors:
        dbg["authors"] = src + (f" ({'; '.join(notes)})" if notes else "")
    if art.byline_raw:
        dbg["byline_raw"] = src
    tail_ag = _trailing_agency(art.body)
    if tail_ag and tail_ag not in agencies:
        agencies.append(tail_ag)
    art.agencies = agencies
    if agencies:
        dbg["agencies"] = (f"assinatura {signatures}" if any(a != tail_ag for a in agencies) else "") + \
            (" + fecho do corpo" if tail_ag else "")

    # Datas (UTC)
    pub_raw = None
    for s, v in (("jsonld:datePublished", ld.get("datePublished")),
                 ("meta:article:published_time", _meta(soup, "article:published_time")), ("rsc:Date", ds.get("Date"))):
        if to_utc_iso(v):
            art.published_at, pub_raw, dbg["published_at"] = to_utc_iso(v), v, s + " -> UTC"
            art.published_at_precision, dbg["published_at_precision"] = "datetime", s + " (ISO com hora e fuso)"
            break
    for s, v in (("jsonld:dateModified", ld.get("dateModified")),
                 ("meta:article:modified_time", _meta(soup, "article:modified_time")),
                 ("rsc:DateChanged", ds.get("DateChanged"))):
        if to_utc_iso(v):
            if to_utc_iso(v) != art.published_at:
                art.updated_at, dbg["updated_at"] = to_utc_iso(v), s + " -> UTC"
            break

    # Secção / subsecção (slugs; nomes em site_meta)
    url_for_section = art.canonical_url or art.url
    art.section = _top_section(url_for_section) or ds.get("SectionSlug")
    if art.section:
        dbg["section"] = "url" if _top_section(url_for_section) else "rsc:SectionSlug"
    sub = ds.get("SectionSlug")
    if sub and sub != art.section:
        art.subsection, dbg["subsection"] = sub, "rsc:SectionSlug"

    # Tags
    tags = [t.strip() for t in (ld.get("keywords") or "").split(",") if t.strip()]
    tsrc = "jsonld:keywords"
    if not tags:
        tags = [t.strip() for t in (_meta(soup, "news_keywords") or "").split(",") if t.strip()]
        tsrc = "meta:news_keywords"
    if not tags:
        tags = [n for n in (_clean(t.get("Name")) for t in ds.get("Tags") or []) if n]
        tsrc = "rsc:Tags[].Name"
    seen_tags: set[str] = set()
    art.tags = [t for t in tags if not (_fold(t) in seen_tags or seen_tags.add(_fold(t)))]
    if art.tags:
        dbg["tags"] = tsrc

    # Tipo de peça
    headline = ds.get("PreTitle") or ds.get("Headline")
    art.piece_type, art.piece_type_raw, psrc = _piece_type(ds.get("Layout"), headline, art.section)
    if not art.piece_type and ld.get("@type") == "OpinionNewsArticle":
        art.piece_type, psrc = "opiniao", "jsonld:@type"
    if art.piece_type and art.piece_type not in PIECE_TYPES:
        art.piece_type = None
    if art.piece_type or art.piece_type_raw:
        dbg["piece_type"] = psrc

    # Acesso (como o site marca) e completude do corpo (o que extraímos)
    access = _access(ds.get("Categories"), ds.get("Layout")) if ds else None
    asrc = "rsc:Categories[].Premium / Layout.Premium"
    if "isAccessibleForFree" in ld:
        free = ld["isAccessibleForFree"] not in (False, "False", "false")
        if not free:
            access = ACCESS_PREMIUM
        elif access is None:
            access = ACCESS_FREE
        asrc = "jsonld:isAccessibleForFree + " + asrc if ds else "jsonld:isAccessibleForFree"
    art.access = access
    if access:
        dbg["access"] = asrc
    site_wc = ds.get("WordCount") or ld.get("wordCount")
    paywall_box = soup.select_one(PAYWALL_SELECTOR) is not None
    wc_note = f"word_count {art.word_count} vs WordCount do site {site_wc} (rácio mín. {BODY_COMPLETE_MIN_RATIO})"
    if art.body and access == ACCESS_FREE and not paywall_box:
        art.body_complete = True
        dbg["body_complete"] = ("artigo free sem caixa de paywall: corpo integral"
                                + (f"; {wc_note} (só nota: o WordCount inclui markup/embeds)" if site_wc else ""))
    elif art.word_count and site_wc:
        art.body_complete = art.word_count >= BODY_COMPLETE_MIN_RATIO * int(site_wc)
        dbg["body_complete"] = wc_note
    premium_cut = access == ACCESS_PREMIUM and (art.body_complete is False or (paywall_box and not art.body_complete))
    if premium_cut:
        partial = art.word_count
        art.body, art.word_count, art.body_complete, art.body_source = [], None, False, None
        art.embeds = []
        dbg["body_complete"] = (f"premium sem texto integral: {partial or 0} palavras no source vs WordCount {site_wc}"
                                + ("; caixa de paywall no HTML" if paywall_box else "") + "; corpo parcial descartado")
        dbg.pop("body", None)
        dbg.pop("word_count", None)
        dbg.pop("embeds", None)
        dbg.pop("links", None)

    # Âmbito e metadados do site
    layout_code = (ds.get("Layout") or {}).get("Code")
    rsc_tags = [t.get("Name") for t in ds.get("Tags") or [] if isinstance(t, dict)]
    art.out_of_scope = out_of_scope_reason(url_for_section, layout_code, ds.get("SectionSlug"), art.tags + rsc_tags,
                                           signatures)
    if art.out_of_scope:
        dbg["out_of_scope"] = "regras OUT_OF_SCOPE_* (secção/SectionSlug/layout/tags/assinatura)"
    elif premium_cut:
        art.out_of_scope, dbg["out_of_scope"] = OUT_OF_SCOPE_PREMIUM, "access=premium e corpo incompleto"
    title_tag = soup.find("title")
    art.site_meta = {
        "headline": _clean(headline),
        "section_name": _clean(ld.get("articleSection") or ds.get("SectionTitle")),
        "subsection_name": _clean(ds.get("Section")) if art.subsection else None,
        "layout_code": layout_code,
        "layout_name": (ds.get("Layout") or {}).get("Name"),
        "categories": [c.get("Code") for c in ds.get("Categories") or [] if isinstance(c, dict)],
        "site_word_count": site_wc,
        "reading_minutes": ds.get("ReadingMinutes"),
        "seo_title": _clean(title_tag.get_text()) if title_tag else None,
        "has_video": ds.get("HasVideo"),
        "has_audio": ds.get("HasAudio"),
        "published_at_raw": pub_raw,
    }
    if notes:
        dbg["notas"] = "; ".join(notes)
    art.extraction_debug = dbg
    return art


# --- Runner -------------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("uso: python3 -m parsers.jn <homepage.html> <artigo.html> [sitemap.xml ...] [--out out_dir]",
              file=sys.stderr)
        return 2
    out_dir = None
    if "--out" in argv:
        i = argv.index("--out")
        out_dir, argv = Path(argv[i + 1]), argv[:i] + argv[i + 2:]
    home_path, art_path = Path(argv[0]), Path(argv[1])
    sitemap_paths = [Path(a) for a in argv[2:]]
    # por omissão, <raiz do repo>/sites/out (independente do cwd e da pasta dos inputs)
    out_dir = out_dir or Path(__file__).resolve().parents[2] / "sites" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    items = parse_homepage(home_path.read_text(encoding="utf-8"))
    excluded = [i for i in parse_homepage(home_path.read_text(encoding="utf-8"), include_excluded=True)
                if i.excluded_reason]
    article = parse_article(art_path.read_text(encoding="utf-8"))

    (out_dir / f"{SITE}_homepage.json").write_text(
        json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{SITE}_article.json").write_text(
        json.dumps(article.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Homepage: {len(items)} artigos no âmbito ({len(excluded)} excluídos: "
          f"{dict(Counter(i.excluded_reason.split(':')[0] for i in excluded))})")
    for i in items[:10]:
        who = ", ".join(a.name for a in i.authors) or "-"
        print(f"  #{i.rank:<3} [{i.site_article_id}] {i.zone or '-':<12} {i.section:<10} {i.access or '-':<7} "
              f"{i.piece_type or '-':<8} {i.published_at or '-':<25} {who[:22]:<22} {i.title}")
    print("\nArtigo:")
    print(f"  título:      {article.title}")
    print(f"  id:          {article.site_article_id}   aliases: {len(article.aliases)}")
    print(f"  autores:     {', '.join(a.name for a in article.authors) or '-'}   agências: {article.agencies}")
    print(f"  publicado:   {article.published_at}   actualizado: {article.updated_at}")
    print(f"  secção:      {article.section}/{article.subsection}  | tipo: {article.piece_type} "
          f"({article.piece_type_raw})  | acesso: {article.access}")
    print(f"  corpo:       {len(article.body)} blocos, {article.word_count} palavras, "
          f"completo={article.body_complete}, fonte={article.body_source}")
    print(f"  imagens:     {[(i.photographers, i.agency, i.is_main) for i in article.images]}")
    print(f"  fora de âmbito: {article.out_of_scope}")
    for sp in sitemap_paths:
        raw = sp.read_bytes()
        if b"<sitemapindex" in raw[:2000]:
            children = parse_sitemap_index(raw)
            print(f"\nÍndice {sp.name}: {len(children)} sitemaps ({children[0]} … {children[-1]})")
            continue
        all_items = parse_sitemap(raw, include_excluded=True)
        kept = [i for i in all_items if not i.excluded_reason]
        out = out_dir / f"{SITE}_{sp.stem.removeprefix(SITE + '_')}.json"
        out.write_text(json.dumps([i.to_dict() for i in all_items], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSitemap {sp.name}: {len(kept)} no âmbito, {len(all_items) - len(kept)} excluídos -> {out}")
    print(f"\nEscrito em {out_dir}/{SITE}_homepage.json e {out_dir}/{SITE}_article.json")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
