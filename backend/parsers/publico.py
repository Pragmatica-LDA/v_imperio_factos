"""Parser do Público (www.publico.pt) — contrato v2 (parsers/base.py).

Padrão de URL de artigo:  /AAAA/MM/DD/<secção>/<tipo>/<slug>-<ID>
Link curto (relacionados): /n<ID>   (redirecciona para o URL completo)
O ID interno é numérico (7 dígitos hoje) e é o mesmo em `data-article-id`, JSON-LD e `publicoConfig`.

Uso: python3 -m parsers.publico <homepage.html> <noticia.html> [sitemap_ou_feed.xml ...]
"""

from __future__ import annotations

import html as htmllib
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from parsers.base import (
    ACCESS_FREE, ACCESS_PREMIUM, AGENCY_GENERIC, Article, Author, Block, Embed, HomepageItem, Image, Link,
    to_utc_iso,
)

SITE = "publico"
BASE_URL = "https://www.publico.pt"

# --- Configuração (listas de exclusão e mapeamentos; ajustar aqui, não no código) ---------------

# Segmento <tipo> do URL que não é peça editorial de texto.
EXCLUDED_TYPES = {
    "podcast", "video", "videos", "multimedia", "fotogaleria", "galeria", "interactivo",
    "directo", "aovivo", "ao-vivo", "live", "conteudo_patrocinado",
}
# Secções fora de âmbito: Estúdio P (patrocinado), promoções institucionais, vídeo.
EXCLUDED_SECTIONS = {"estudiop", "edicoes-publico", "video"}
# Zonas da homepage cujo conteúdo é todo fora de âmbito (o ID fica excluído em toda a página).
EXCLUDED_ZONES = {"podcasts", "conheca-o-publico", "estudio-p"}
# Classes de "tom" do card que indicam conteúdo não editorial.
EXCLUDED_TONES = {"tone--paid"}
# data-article-type dos cards que não são artigos.
EXCLUDED_CARD_TYPES = {"VIDEO", "EXTERNOS"}
# Papéis no byline que denunciam um episódio de áudio publicado com URL de notícia.
AUDIO_HINTS = ("edicao de som", "sonoplastia", "narracao")
# Rótulos (<b>) dos relacionados que denunciam multimédia.
EXCLUDED_LABELS_RE = re.compile(r"^(v[íi]deo|podcast|fotogaleria|directo|ao vivo)\b", re.I)
# Marcas/suplementos do Público que vivem em www.publico.pt. Mantidos (são redacção do Público);
# pôr True para os excluir se forem tratados como revistas independentes.
GROUP_BRAND_SECTIONS = {"p3", "fugas", "culturaipsilon", "impar", "azul", "publico-brasil"}
EXCLUDE_GROUP_BRANDS = False

# Segmento <tipo> do URL -> piece_type normalizado (base.PIECE_TYPES). O original vai para piece_type_raw.
PIECE_TYPE_MAP = {
    "noticia": "noticia",
    "entrevista": "entrevista",
    "editorial": "editorial",
    "analise": "analise",
    "opiniao": "opiniao",
    "carta": "opiniao",
    "cronica": "cronica",
    "critica": "critica",
    "reportagem": "reportagem",
    "investigacao": "investigacao",
    "prova-dos-factos": "factcheck",
    "cronica_de_jogo": "noticia",  # relato de jogo: notícia com voz de autor, não opinião
}

# Autores/assinaturas que são agências (comparação sem acentos, minúsculas).
AGENCIES = {"lusa": "Lusa", "reuters": "Reuters", "afp": "AFP", "efe": "EFE", "ap": "AP",
            "associated press": "AP", "bloomberg": "Bloomberg", "agencias": AGENCY_GENERIC}

# Agências/bancos de imagem nos créditos das fotografias (chave sem acentos, minúsculas).
IMAGE_AGENCIES = {"lusa": "Lusa", "epa": "EPA", "reuters": "Reuters", "afp": "AFP", "ap": "AP",
                  "associated press": "AP", "getty images": "Getty Images", "getty": "Getty Images",
                  "global imagens": "Global Imagens", "nfactos": "NFactos", "unsplash": "Unsplash",
                  "efe": "EFE", "bloomberg": "Bloomberg", "anadolu": "Anadolu", "publico": "PÚBLICO",
                  "arquivo": "Arquivo", "dr": "DR"}
# Créditos que não são agência nem fotógrafo (ficam só em credit_raw).
NON_PHOTOGRAPHER_CREDITS = {"dr", "arquivo", "direitos reservados"}
# Partes do crédito que marcam foto de arquivo (Image.is_archive).
ARCHIVE_CREDITS = {"arquivo", "arquivo publico", "arquivo do publico", "file", "archive"}
# Marcas de paywall no HTML (só aparecem em artigos exclusivos; o .pw-container aparece em todos).
PAYWALL_HTML_MARKERS = ["#paywall-disclaimer", "article#story .kicker--exclusive"]
PARTICLES = {"de", "da", "do", "das", "dos", "e"}

# Palavras que fazem de um parênteses no byline uma função (role) e não uma afiliação.
ROLE_HINTS = ("texto", "foto", "video", "ilustr", "infograf", "som", "sonoplast", "narra", "produc",
              "revis", "guiao", "investigac", "grafismo", "montagem", "edicao", "imagem", "design")

# Papel no byline -> Author.role
ROLE_MAP = {"texto": "texto", "fotografia": "fotografia", "foto": "fotografia", "video": "video",
            "ilustracao": "ilustracao", "infografia": "infografia", "edicao de som": "audio",
            "sonoplastia": "audio", "narracao": "audio"}

# Parágrafos de ruído editorial dentro do corpo (início do texto, minúsculas).
BOILERPLATE_PREFIXES = (
    "leia também", "ler mais", "ver também", "veja também", "subscreva", "assine já",
    "receba a newsletter", "newsletter", "siga o público", "o público já está",
)

# Elementos a remover do corpo antes de extrair texto.
BODY_NOISE_SELECTORS = [
    "script", "style", "noscript", "iframe", "figure", "aside", "ad-placement",
    ".pw-container", ".ad-slot", ".story__callout", ".media", ".inline-newsletter",
    "[class*=newsletter]", "[class*=ad-slot]", ".related", ".read-more",
]
BLOCK_TAGS = {"p": "p", "h2": "h2", "h3": "h3", "h4": "h3", "li": "li", "blockquote": "quote"}

# Ligações do corpo (contrato v2.2). Links para estes hosts são promoção (app do Público), não referências.
BODY_LINK_NOISE_HOSTS = {"play.google.com", "apps.apple.com", "itunes.apple.com", "appgallery.huawei.com"}
# Esquemas de href que não são ligações (âncoras, scripts, contactos).
BODY_LINK_SKIP_PREFIXES = ("javascript:", "#", "mailto:", "tel:")
# Embeds no corpo que NÃO são conteúdo de terceiros: caixas "leia também" com iframe do próprio Público
# (aside.story__callout--link > iframe.interactive data-src=".../embed?FromApp=1").
EMBED_SKIP_ANCESTORS = ".story__callout, .related, .read-more, .inline-newsletter, [class*=newsletter], .pw-container"
# Blockquotes/divs de embed das redes sociais (marcação padrão dos scripts das plataformas).
EMBED_BLOCK_SELECTORS = {
    "blockquote.instagram-media": "instagram",
    "blockquote.twitter-tweet": "x",
    "blockquote.twitter-video": "x",
    "blockquote.tiktok-embed": "tiktok",
    "div.fb-post": "facebook",
    "div.fb-video": "facebook",
    "blockquote.threads-post": "threads",
    "blockquote.bluesky-embed": "bluesky",
}
# Host de iframe/URL -> plataforma (pista para o pipeline). Sufixo do host.
EMBED_HOST_PLATFORMS = {
    "youtube.com": "youtube", "youtube-nocookie.com": "youtube", "youtu.be": "youtube",
    "vimeo.com": "vimeo", "dailymotion.com": "dailymotion",
    "instagram.com": "instagram", "twitter.com": "x", "x.com": "x",
    "facebook.com": "facebook", "tiktok.com": "tiktok", "threads.net": "threads",
    "bsky.app": "bluesky", "spotify.com": "spotify", "soundcloud.com": "soundcloud",
    "flourish.studio": "flourish", "datawrapper.de": "datawrapper", "google.com/maps": "google_maps",
}

# ------------------------------------------------------------------------------------------------

ARTICLE_PATH_RE = re.compile(
    r"^/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<section>[\w-]+)/(?P<type>[\w-]+)/(?P<slug>[\w-]+?)-(?P<id>\d{5,})/?$"
)
SHORT_PATH_RE = re.compile(r"^/n(?P<id>\d{5,})/?$")
SITE_HOSTS = {"www.publico.pt", "publico.pt"}


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", htmllib.unescape(text)).strip()
    # O HTML do Público quebra linha entre </em> e a pontuação seguinte ("Leaks</em>\n:").
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)
    return text or None


def _fold(text: str) -> str:
    """minúsculas sem acentos, para comparações."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def _slugify(text: str | None) -> str | None:
    return re.sub(r"[^a-z0-9]+", "-", _fold(text)).strip("-") or None if text else None


def _normalize(href: str, base_url: str = BASE_URL):
    """(url_normalizado, match_completo, match_curto) se o link for do site; senão None."""
    if not href or href.strip().startswith(("javascript:", "mailto:", "#", "{{", "${")):
        return None
    parts = urlsplit(urljoin(base_url, href.strip()))
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in SITE_HOSTS:
        return None
    path = parts.path
    url = urlunsplit(("https", "www.publico.pt", path.rstrip("/") or "/", "", ""))
    return url, ARTICLE_PATH_RE.match(path), SHORT_PATH_RE.match(path)


def _scope_reason(m: re.Match) -> str | None:
    """Motivo de exclusão de um URL de artigo, ou None se estiver no âmbito."""
    if m["type"].lower() in EXCLUDED_TYPES:
        return f"tipo:{m['type']}"
    if m["section"].lower() in EXCLUDED_SECTIONS:
        return f"secção:{m['section']}"
    if EXCLUDE_GROUP_BRANDS and m["section"].lower() in GROUP_BRAND_SECTIONS:
        return f"marca:{m['section']}"
    return None


def _piece_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return PIECE_TYPE_MAP.get(raw.lower())


def _role(text: str | None) -> str | None:
    if not text:
        return None
    key = _fold(text).strip()
    return ROLE_MAP.get(key, key or None)


def _is_role(text: str) -> bool:
    key = _fold(text)
    return any(h in key for h in ROLE_HINTS)


def _parse_byline(container: Tag | None) -> tuple[list[Author], str | None]:
    """Lê `<address>` com link de autor e parênteses opcionais: 'Nome (fotografia) e', 'Nome (TSF)'.

    Parênteses com uma função (texto, fotografia, edição de som…) -> role; outros -> affiliation.
    Devolve (autores, byline_raw).
    """
    authors: list[Author] = []
    if container is None:
        return authors, None
    raw = _clean(" ".join(addr.get_text() for addr in container.find_all("address"))) or \
        _clean(container.get_text())
    for addr in container.find_all("address"):
        a = addr.find("a", href=True)
        name_tag = addr.select_one(".byline__name") or a
        text = addr.get_text()
        name = _clean(name_tag.get_text()) if name_tag else _clean(re.sub(r"\([^)]*\)|\s+e\s*$", "", text))
        if not name:
            continue
        role = affiliation = None
        for par in re.findall(r"\(([^)]+)\)", text):
            if _is_role(par):
                role = role or _role(par)
            else:
                affiliation = affiliation or _clean(par)
        url = urljoin(BASE_URL, a["href"]) if a else None
        authors.append(Author(name=name, role=role, url=url, affiliation=affiliation))
    return authors, raw


def _agencies(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        for part in re.split(r"[/,]| e ", n):
            ag = AGENCIES.get(_fold(part).strip())
            if ag and ag not in out:
                out.append(ag)
    return out


def _name_case(text: str) -> str:
    """O Público escreve os créditos em maiúsculas ('JOSé COELHO'): passa a 'José Coelho' se vier assim."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) < 0.6:
        return text
    words = text.lower().split()
    return " ".join(w if i and w in PARTICLES else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _parse_credit(raw: str | None) -> tuple[list[str], str | None]:
    """'NOME/AGÊNCIA' -> (['Nome'], 'Agência'); 'LUSA/EPA' -> ([], 'Lusa/EPA'); 'NOME' -> (['Nome'], None)."""
    if not raw:
        return [], None
    photographers, agencies = [], []
    for part in (p.strip() for p in re.split(r"\s*/\s*", raw)):
        if not part:
            continue
        key = _fold(part)
        if key in NON_PHOTOGRAPHER_CREDITS:
            continue
        if key in IMAGE_AGENCIES:
            agencies.append(IMAGE_AGENCIES[key])
        else:
            photographers.extend(_name_case(n.strip()) for n in re.split(r"\s*(?:,| e | and )\s*", part) if n.strip())
    return photographers, "/".join(dict.fromkeys(agencies)) or None


def _image_url(img: Tag) -> str | None:
    url = img.get("data-media-viewer") or img.get("data-src") or img.get("src")
    if not url or url.startswith("data:"):
        return None
    url = htmllib.unescape(url.strip())
    return re.sub(r"&(w|act)=[^&]*", "", url)  # tirar o redimensionamento do lazy-load


def _extract_images(story: Tag | None) -> list[Image]:
    """Imagem principal (figure.story__media no cabeçalho) e figuras do corpo, com crédito da legenda."""
    out: list[Image] = []
    if story is None:
        return out
    header = story.select_one("#story-header, .story__header")
    body = story.select_one("#story-body, .story__body")
    figs = ([(f, True) for f in header.select("figure.story__media")] if header else []) + \
           ([(f, False) for f in body.find_all("figure") if f.find("img")] if body else [])
    for fig, is_main in figs:
        img = fig.find("img")
        url = _image_url(img) if img else None
        if not url or any(i.url == url for i in out):
            continue
        cap = fig.find("figcaption")
        credit_tag = cap.select_one(".credit") if cap else None
        credit = _clean(credit_tag.get_text()) if credit_tag else None
        if credit_tag:
            credit_tag.extract()
        caption = _clean(cap.get_text()) if cap else None
        photographers, agency = _parse_credit(credit)
        is_archive = bool(credit) and any(_fold(p.strip()) in ARCHIVE_CREDITS for p in credit.split("/"))
        out.append(Image(url=url, caption=caption, photographers=photographers, credit_raw=credit,
                         is_archive=is_archive,
                         agency=agency, is_main=is_main and not any(i.is_main for i in out)))
    return out


# --- Homepage ------------------------------------------------------------------------------------

def _zone_of(card: Tag) -> tuple[str | None, dict]:
    """Zona = título do bloco (h1.block__title) ou da coluna temática (h1.column__title)."""
    meta: dict = {}
    col = card.find_parent(attrs={"data-collection": True})
    block = card.find_parent("section", class_="block")
    column_title = None
    if col is not None and col.name != "section":
        header = col.find_previous_sibling("header")
        t = header.select_one(".column__title") if header else None
        column_title = _clean(t.get_text()) if t else None
    block_title = None
    if block is not None:
        t = block.select_one(":scope > header .block__title")
        block_title = _clean(t.get_text()) if t else None
        meta["collection"] = block.get("data-collection")
        stack = [c for c in block.get("class") or [] if c.startswith("stack-")]
        if stack:
            meta["stack"] = stack[0]
    if column_title:
        meta["column"] = column_title
    zone = _slugify(block_title) or (stack[0].removeprefix("stack-") if block is not None and stack else None)
    if zone is None and block is not None and "block--brands" in (block.get("class") or []):
        zone = "marcas"
    if zone is None and block is not None and "block--categories-cta" in (block.get("class") or []):
        zone = "categorias"
    return zone, meta


def _audio_byline(text: str) -> bool:
    return any(h in _fold(par) for par in re.findall(r"\(([^)]+)\)", text) for h in AUDIO_HINTS)


def _card_fields(card: Tag) -> tuple[str | None, str | None, list[Author], str | None, dict, dict]:
    """(título, lead, autores, byline_raw, site_meta, debug) de um card da homepage."""
    dbg: dict = {}
    t = card.select_one(".article__title a")
    title = _clean(t.get_text()) if t else None
    if title:
        dbg["title"] = "html:.article__title a"
    lp = card.select_one(".article__lead")
    lead = _clean(lp.get_text()) if lp else None
    if lead:
        dbg["lead"] = "html:.article__lead"
    authors, byline_raw = _parse_byline(card.select_one(".article__byline"))
    if authors:
        dbg["authors"] = "html:.article__byline address (role/affiliation dos parênteses)"
    classes = card.get("class") or []
    meta = {
        "card_type": card.get("data-article-type"),
        "tone": next((c.removeprefix("tone--") for c in classes if c.startswith("tone--")), None),
        "level": next((int(c.rsplit("-", 1)[1]) for c in classes if re.fullmatch(r"article--level-\d", c)), None),
    }
    return title, lead, authors, byline_raw, meta, dbg


def parse_homepage(html: str, base_url: str = BASE_URL, include_excluded: bool = False) -> list[HomepageItem]:
    """Artigos da homepage. Com include_excluded=True devolve também os fora de âmbito, com excluded_reason."""
    soup = BeautifulSoup(html, "lxml")
    items: dict[str, HomepageItem] = {}   # chave: ID interno (ou "url:<url>" se não houver ID)
    excluded: dict[str, str] = {}         # ID -> motivo (vale para toda a página)

    # 1.ª passagem: IDs excluídos por zona/tom/tipo de card/papéis de áudio no byline.
    for card in soup.select("article[data-article-id]"):
        cid = card["data-article-id"]
        zone, _ = _zone_of(card)
        classes = set(card.get("class") or [])
        byline = " ".join(x.get_text() for x in card.select(".article__byline address"))
        if zone in EXCLUDED_ZONES:
            excluded.setdefault(cid, f"zona:{zone}")
        elif classes & EXCLUDED_TONES:
            excluded.setdefault(cid, "tom:" + ",".join(sorted(classes & EXCLUDED_TONES)))
        elif card.get("data-article-type") in EXCLUDED_CARD_TYPES:
            excluded.setdefault(cid, f"card:{card.get('data-article-type')}")
        elif _audio_byline(byline):
            excluded.setdefault(cid, "byline:áudio (podcast)")

    def add(key: str, item: HomepageItem, is_short: bool) -> None:
        prev = items.get(key)
        if prev is None:
            item.rank = len(items)
            item.zones = [item.zone] if item.zone else []
            items[key] = item
            return
        if item.zone and item.zone not in prev.zones:
            prev.zones.append(item.zone)
        if is_short:
            if item.url not in prev.aliases and item.url != prev.url:
                prev.aliases.append(item.url)
            prev.title = prev.title or item.title
            return
        if SHORT_PATH_RE.match(urlsplit(prev.url).path):
            # Tínhamos só o link curto: o URL completo passa a principal, o curto vai para aliases.
            short = prev.url
            item.rank, item.aliases = prev.rank, [short] + [a for a in prev.aliases if a != short]
            item.title = item.title or prev.title
            item.zone, item.zones = prev.zone, prev.zones  # zona/rank da 1.ª aparição
            if prev.site_meta.get("collection"):
                item.site_meta["collection"] = prev.site_meta["collection"]
            items[key] = item
            return
        for f in ("lead", "title", "byline_raw"):
            if getattr(prev, f) is None and getattr(item, f):
                setattr(prev, f, getattr(item, f))
                if f in item.extraction_debug:
                    prev.extraction_debug[f] = item.extraction_debug[f]
        if not prev.authors and item.authors:
            prev.authors, prev.agencies = item.authors, item.agencies
            prev.extraction_debug["authors"] = item.extraction_debug.get("authors")

    for a in soup.find_all("a", href=True):
        norm = _normalize(a["href"], base_url)
        if not norm:
            continue
        url, m_full, m_short = norm
        if not (m_full or m_short):
            continue
        card = a.find_parent("article")
        related = a.find_parent(class_="article__related") is not None
        art_id = (m_full or m_short)["id"]
        reason = excluded.get(art_id)
        if reason and not include_excluded:
            continue
        zone, zmeta = _zone_of(card) if card is not None else (None, {})
        dbg: dict = {"url": "html:a[href]", "site_article_id": "url"}
        lead, authors, byline_raw, site_meta = None, [], None, dict(zmeta)

        if card is not None and not related:
            # Card: o título é o do .article__title (o <a> da imagem/vídeo traz texto de fallback).
            title, lead, authors, byline_raw, cmeta, cdbg = _card_fields(card)
            site_meta.update(cmeta)
            dbg.update(cdbg)
        else:
            # Relacionados: o rótulo em <b> ("Opinião", "Vídeo") sai do título e fica como pista.
            label_tag = a.find("b")
            label = _clean(label_tag.get_text()) if label_tag else None
            if label_tag:
                label_tag.extract()
            if label and EXCLUDED_LABELS_RE.match(label):
                reason = reason or f"rótulo:{label}"
                if not include_excluded:
                    continue
            title = _clean(a.get_text())
            title = title.lstrip(". ").strip() or None if title else None
            dbg["title"] = "html:.article__related a"
            if label:
                site_meta["label"] = label
            site_meta["related_of"] = card.get("data-article-id") if card is not None else None
        agencies = _agencies([x.name for x in authors])
        if agencies:
            dbg["agencies"] = "byline"
        if byline_raw:
            dbg["byline_raw"] = "html:.article__byline"

        if m_full:
            reason = reason or _scope_reason(m_full)
            if reason and not include_excluded:
                continue
            raw = m_full["type"]
            pt = _piece_type(raw)
            if site_meta.get("tone") == "opinion" and pt in (None, "noticia"):
                pt = "opiniao"
                dbg["piece_type"] = "html:tone--opinion"
            else:
                dbg["piece_type"] = "url:<tipo>"
            dbg.update({"section": "url:<secção>", "published_at": "url:/AAAA/MM/DD/ (só data)",
                        "piece_type_raw": "url:<tipo>"})
            if m_full["section"].lower() in GROUP_BRAND_SECTIONS:
                site_meta["brand"] = m_full["section"]
            add(art_id, HomepageItem(
                url=url, site_article_id=art_id, title=title, lead=lead, authors=authors,
                agencies=agencies, byline_raw=byline_raw, section=m_full["section"],
                published_at=f"{m_full['y']}-{m_full['m']}-{m_full['d']}",
                published_at_precision="date",
                piece_type=pt, piece_type_raw=raw, zone=zone,
                site_meta=site_meta, extraction_debug=dbg, excluded_reason=reason,
            ), is_short=False)
        else:
            dbg["note"] = "link curto /n<ID>: tipo, secção e data desconhecidos (só via redirect)"
            if site_meta.get("label") and _fold(site_meta["label"]).startswith("opiniao"):
                dbg["piece_type"] = "html:rótulo <b>"
            add(art_id, HomepageItem(
                url=url, site_article_id=art_id, title=title, zone=zone,
                piece_type="opiniao" if dbg.get("piece_type") else None,
                site_meta=site_meta, extraction_debug=dbg, excluded_reason=reason,
            ), is_short=True)

    if include_excluded:
        # Cards sem URL de artigo (vídeos, interactivos, especiais externos): auditáveis, sem ID de artigo.
        for card in soup.select("article[data-article-id]"):
            t = card.select_one(".article__title a[href]")
            norm = _normalize(t["href"], base_url) if t else None
            if not norm or norm[1] or norm[2]:
                continue
            key = f"url:{norm[0]}"
            if key in items:
                continue
            title, lead, authors, byline_raw, cmeta, cdbg = _card_fields(card)
            zone, zmeta = _zone_of(card)
            reason = excluded.get(card["data-article-id"]) or "url sem padrão de artigo"
            add(key, HomepageItem(
                url=norm[0], title=title, lead=lead, authors=authors, byline_raw=byline_raw, zone=zone,
                site_meta={**zmeta, **cmeta, "card_id": card["data-article-id"]},
                extraction_debug={"url": "html:.article__title a", **cdbg}, excluded_reason=reason,
            ), is_short=False)

    return list(items.values())


# --- Sitemaps e RSS ------------------------------------------------------------------------------

def parse_sitemap_index(xml: str) -> list[str]:
    """Índice de sitemaps -> lista de URLs de sitemaps filhos."""
    soup = BeautifulSoup(xml, "xml")
    return [_clean(loc.get_text()) for sm in soup.find_all("sitemap") if (loc := sm.find("loc"))]


def _item_from_url(url: str, title: str | None, published: str | None, dbg: dict,
                   site_meta: dict) -> HomepageItem | None:
    norm = _normalize(url)
    if not norm:
        return None
    nurl, m_full, m_short = norm
    if m_full:
        if _scope_reason(m_full):
            return None
        raw = m_full["type"]
        prec = "datetime" if published else "date"
        published = published or f"{m_full['y']}-{m_full['m']}-{m_full['d']}"
        dbg.setdefault("published_at", "url:/AAAA/MM/DD/ (só data)")
        dbg.update({"section": "url:<secção>", "piece_type": "url:<tipo>", "piece_type_raw": "url:<tipo>",
                    "site_article_id": "url"})
        return HomepageItem(url=nurl, site_article_id=m_full["id"], title=title, section=m_full["section"],
                            published_at=published, published_at_precision=prec,
                            piece_type=_piece_type(raw), piece_type_raw=raw,
                            site_meta=site_meta, extraction_debug=dbg)
    if m_short:
        dbg["note"] = "link curto /n<ID>: tipo e secção desconhecidos"
        return HomepageItem(url=nurl, site_article_id=m_short["id"], title=title, published_at=published,
                            published_at_precision="datetime" if published else None,
                            site_meta=site_meta, extraction_debug=dbg)
    return None


def parse_sitemap(xml: str) -> list[HomepageItem]:
    """`urlset` (normal ou Google News) -> HomepageItem. Mesmas regras de âmbito da homepage.

    ⚠️ Escrito para o formato standard (sitemaps.org + news 0.9) sem amostra real do Público:
    o robots.txt do Público bloqueia o user-agent Claude-Code, por isso não foi descarregado.
    """
    soup = BeautifulSoup(xml, "xml")
    out: dict[str, HomepageItem] = {}
    for u in soup.find_all("url"):
        loc = u.find("loc")
        if not loc:
            continue
        news = u.find("news")
        title = _clean(news.find("title").get_text()) if news and news.find("title") else None
        pub_raw = news.find("publication_date").get_text() if news and news.find("publication_date") else None
        lastmod = u.find("lastmod")
        dbg = {"url": "sitemap:loc"}
        meta: dict = {}
        published = to_utc_iso(pub_raw) if pub_raw else None
        if published:
            dbg["published_at"] = "sitemap:news:publication_date"
        if title:
            dbg["title"] = "sitemap:news:title"
        if lastmod:
            meta["lastmod"] = to_utc_iso(lastmod.get_text())
        if news and news.find("keywords"):
            meta["keywords"] = [k.strip() for k in news.find("keywords").get_text().split(",") if k.strip()]
        item = _item_from_url(_clean(loc.get_text()), title, published, dbg, meta)
        if item and item.site_article_id not in out:
            item.rank = len(out)
            out[item.site_article_id] = item
    return list(out.values())


def parse_feed(xml: str) -> list[HomepageItem]:
    """RSS 2.0 / Atom -> HomepageItem. Mesmas regras de âmbito da homepage.

    ⚠️ Sem amostra real (ver parse_sitemap). Feedburner usa <feedburner:origLink> com o URL original.
    """
    soup = BeautifulSoup(xml, "xml")
    out: dict[str, HomepageItem] = {}
    entries = soup.find_all("item") or soup.find_all("entry")
    for e in entries:
        link = None
        for tag, src in (("origLink", "feed:feedburner:origLink"), ("link", "feed:link"), ("guid", "feed:guid")):
            t = e.find(tag)
            if t is None:
                continue
            link = _clean(t.get("href") or t.get_text())
            if link and _normalize(link):
                break
            link = None
        if not link:
            continue
        dbg = {"url": src}
        t = e.find("title")
        title = _clean(BeautifulSoup(t.get_text(), "lxml").get_text()) if t else None
        if title:
            dbg["title"] = "feed:title"
        d = e.find("pubDate") or e.find("published") or e.find("updated")
        published = to_utc_iso(d.get_text()) if d else None
        if published:
            dbg["published_at"] = f"feed:{d.name}"
        meta: dict = {}
        cats = [_clean(c.get_text() or c.get("term")) for c in e.find_all("category")]
        if any(cats):
            meta["categories"] = [c for c in cats if c]
        desc = e.find("description") or e.find("summary")
        item = _item_from_url(link, title, published, dbg, meta)
        if item is None:
            continue
        if desc:
            item.lead = _clean(BeautifulSoup(desc.get_text(), "lxml").get_text())
            if item.lead:
                item.extraction_debug["lead"] = f"feed:{desc.name}"
        creators = [_clean(c.get_text()) for c in e.find_all(["creator", "author"])]
        item.authors = [Author(name=c) for c in creators if c]
        if item.site_article_id not in out:
            item.rank = len(out)
            out[item.site_article_id] = item
    return list(out.values())


# --- Artigo --------------------------------------------------------------------------------------

def _json_ld(soup: BeautifulSoup) -> dict:
    for sc in soup.find_all("script", type="application/ld+json"):
        raw = sc.string or sc.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:  # tolerar vírgulas finais
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle",
                                                          "OpinionNewsArticle", "AnalysisNewsArticle"):
                return d
    return {}


def _publico_config(html: str) -> dict:
    """Lê os campos simples de window.publicoConfig (objecto JS, não JSON)."""
    m = re.search(r"window\.publicoConfig\s*=\s*\{(.*?)\n\s*\};", html, re.S)
    if not m:
        return {}
    cfg: dict = {}
    for key, val in re.findall(r"^\s*(\w+)\s*:\s*(.+?),?\s*$", m.group(1), re.M):
        val = val.rstrip(",").strip()
        if val in ("true", "false"):
            cfg[key] = val == "true"
        elif val.startswith(("[", '"', "{")):
            try:
                cfg[key] = json.loads(val)
            except json.JSONDecodeError:
                pass
        elif re.fullmatch(r"\d+", val):
            cfg[key] = int(val)
    if "pageSection" not in cfg:
        ps = re.search(r'pageSection:\s*\{\s*name:\s*"([^"]*)",\s*slug:\s*"([^"]*)"', m.group(1))
        if ps:
            cfg["pageSection"] = {"name": htmllib.unescape(ps.group(1)), "slug": ps.group(2)}
    return cfg


def _meta(soup: BeautifulSoup, key: str) -> str | None:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return _clean(tag.get("content")) if tag else None


def _embed_platform(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    for key, platform in EMBED_HOST_PLATFORMS.items():
        h, _, path = key.partition("/")
        if (host == h or host.endswith("." + h)) and (not path or parts.path.startswith("/" + path)):
            return platform
    return None


def _embed_original_url(src: str) -> str:
    """URL do conteúdo original a partir do URL do player/iframe (quando a plataforma o permite)."""
    parts = urlsplit(src)
    host = (parts.hostname or "").lower().removeprefix("www.")
    qs = parse_qs(parts.query)
    if host.endswith(("youtube.com", "youtube-nocookie.com")) and parts.path.startswith("/embed/"):
        vid = parts.path.split("/")[2]
        return f"https://www.youtube.com/watch?v={vid}" if vid and vid != "videoseries" else src
    if host == "player.vimeo.com" and parts.path.startswith("/video/"):
        return f"https://vimeo.com/{parts.path.split('/')[2]}"
    if host.endswith("facebook.com") and parts.path.startswith("/plugins/") and qs.get("href"):
        return qs["href"][0]
    if host.endswith("instagram.com") and re.search(r"/embed/?(captioned/?)?$", parts.path):
        return urlunsplit(("https", "www.instagram.com", re.sub(r"embed/?(captioned/?)?$", "", parts.path), "", ""))
    if host == "platform.twitter.com" and qs.get("id"):
        return f"https://x.com/i/status/{qs['id'][0]}"
    if host.endswith("spotify.com") and parts.path.startswith("/embed/"):
        return urlunsplit(("https", "open.spotify.com", parts.path.removeprefix("/embed"), "", ""))
    return src


def _embed_from(el: Tag, base: str) -> tuple[Embed, str] | None:
    """Embed (url, plataforma, texto) de um elemento do corpo, com a origem para o debug."""
    if el.name == "iframe":
        src = (el.get("data-src") or el.get("src") or "").strip()
        if not src or src.startswith("about:"):
            return None
        src = urljoin(base, src)
        platform = _embed_platform(src)
        if platform is None:
            return None  # iframe sem plataforma conhecida (ex.: interactivo do próprio site)
        return Embed(url=_embed_original_url(src), platform=platform,
                     text=_clean(el.get("title"))), "html:#story-body iframe[src|data-src]"
    for sel, platform in EMBED_BLOCK_SELECTORS.items():
        if not el.css.match(sel):
            continue
        url = (el.get("data-instgrm-permalink") or el.get("data-href") or el.get("cite") or "").strip()
        if not url:
            hrefs = [a["href"] for a in el.find_all("a", href=True)]
            if platform == "x":
                hrefs = [h for h in hrefs if "/status/" in h] or hrefs
            url = hrefs[-1] if hrefs else ""
        if not url:
            return None
        url = urljoin(base, url.strip()).split("?")[0]  # sem tracking (?utm_source, ?ref_src…)
        return Embed(url=url, platform=platform, text=_clean(el.get_text(" "))), f"html:#story-body {sel}"
    return None


def _body_blocks(container: Tag | None, base: str) -> tuple[list[Block], list[Embed], dict]:
    """Blocos do corpo + embeds (com block_index) + estatísticas de ligações para o debug."""
    stats = {"links": 0, "noise_links": 0, "noise_blocks": 0, "embed_sources": [], "skipped_embeds": 0}
    if container is None:
        return [], [], stats
    # 1) Embeds: identificados antes de limpar o ruído (iframe/figure são removidos a seguir) e trocados
    #    por um marcador, para saber a posição no corpo.
    embeds: list[Embed] = []
    candidates = container.select("iframe, " + ", ".join(EMBED_BLOCK_SELECTORS))
    for el in candidates:
        if el.decomposed:
            continue
        if el.find_parent(lambda t: t.css.match(EMBED_SKIP_ANCESTORS)):
            stats["skipped_embeds"] += 1
            continue
        found = _embed_from(el, base)
        if found is None:
            continue
        emb, src = found
        if any(e.url == emb.url for e in embeds):
            continue
        marker = BeautifulSoup("", "lxml").new_tag("embed-marker")
        marker["data-i"] = str(len(embeds))
        # O wrapper (figure/div de embed) inteiro sai do corpo: a legenda do embed não é texto da notícia.
        target = el.find_parent("figure") or el
        caption = target.find("figcaption") if target.name == "figure" else None
        if caption is not None and _clean(caption.get_text()):
            emb.text = _clean(caption.get_text())
        target.replace_with(marker)
        embeds.append(emb)
        stats["embed_sources"].append(src)
    # 2) Ruído
    for sel in BODY_NOISE_SELECTORS:
        for el in container.select(sel):
            el.decompose()
    # 3) Blocos e links, por ordem; os marcadores dão o block_index dos embeds.
    out: list[Block] = []
    for el in container.find_all(list(BLOCK_TAGS) + ["embed-marker"]):
        if el.name == "embed-marker":
            embeds[int(el["data-i"])].block_index = len(out)
            continue
        # Só blocos "folha" (sem outro bloco lá dentro), para não duplicar texto.
        if el.find(["p", "li", "blockquote"]):
            continue
        text = _clean(el.get_text())
        if not text or _fold(text).startswith(tuple(_fold(p) for p in BOILERPLATE_PREFIXES)):
            continue
        links, noise = [], 0
        for a in el.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(BODY_LINK_SKIP_PREFIXES):
                continue
            norm = _normalize(href, base)
            abs_url = norm[0] if norm else urljoin(base, href)
            if (urlsplit(abs_url).hostname or "").lower() in BODY_LINK_NOISE_HOSTS:
                noise += 1
                continue
            links.append(Link(text=_clean(a.get_text()) or "", url=abs_url))
        stats["noise_links"] += noise
        if noise and not links:
            stats["noise_blocks"] += 1  # parágrafo só de promoção da app
            continue
        stats["links"] += len(links)
        kind = "quote" if el.find_parent("blockquote") else BLOCK_TAGS[el.name]
        out.append(Block(kind=kind, text=text, links=links))
    for e in embeds:
        if e.block_index is None:  # embed no fim do corpo
            e.block_index = len(out)
    return out, embeds, stats


def parse_article(html: str, url: str | None = None) -> Article:
    soup = BeautifulSoup(html, "lxml")
    ld = _json_ld(soup)
    cfg = _publico_config(html)
    story = soup.select_one("article#story") or soup.select_one("article.story")
    dbg: dict = {}

    # URL canónico e ID
    canonical = None
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        canonical, dbg["canonical_url"] = link["href"].strip(), "html:link[rel=canonical]"
    elif ld.get("url"):
        canonical, dbg["canonical_url"] = ld["url"], "jsonld:url"
    elif _meta(soup, "og:url"):
        canonical, dbg["canonical_url"] = _meta(soup, "og:url"), "meta:og:url"
    path_m = None
    for u in (canonical, url):
        path_m = ARTICLE_PATH_RE.match(urlsplit(u).path) if u else None
        if path_m:
            break

    art_id = None
    if story is not None and story.get("data-article-id"):
        art_id, dbg["site_article_id"] = story["data-article-id"], "html:article#story[data-article-id]"
    elif cfg.get("pageArticleId"):
        art_id, dbg["site_article_id"] = str(cfg["pageArticleId"]), "publicoConfig.pageArticleId"
    elif path_m:
        art_id, dbg["site_article_id"] = path_m["id"], "url"

    aliases = []
    if url and canonical and _normalize(url) and _normalize(url)[0] != _normalize(canonical)[0]:
        aliases.append(_normalize(url)[0])

    # Título e lead
    title = None
    if ld.get("headline"):
        title, dbg["title"] = _clean(ld["headline"]), "jsonld:headline"
    elif _meta(soup, "og:title"):
        title, dbg["title"] = _meta(soup, "og:title"), "meta:og:title"
    elif story is not None and story.select_one("h1"):
        title, dbg["title"] = _clean(story.select_one("h1").get_text()), "html:h1.story__headline"
    lead = None
    blurb = story.select_one(".story__blurb") if story is not None else None
    if blurb and _clean(blurb.get_text()):
        lead, dbg["lead"] = _clean(blurb.get_text()), "html:.story__blurb"
    elif ld.get("description"):
        lead, dbg["lead"] = _clean(ld["description"]), "jsonld:description"
    elif _meta(soup, "og:description"):
        lead, dbg["lead"] = _meta(soup, "og:description"), "meta:og:description"

    # Autores: nomes do JSON-LD; papel e URL do byline HTML
    byline, byline_raw = _parse_byline(story.select_one(".byline") if story is not None else None)
    if byline_raw:
        dbg["byline_raw"] = "html:.byline address"
    by_name = {_fold(a.name): a for a in byline}
    authors: list[Author] = []
    ld_auth = ld.get("author") or []
    for a in ld_auth if isinstance(ld_auth, list) else [ld_auth]:
        name = _clean(a.get("name") if isinstance(a, dict) else str(a))
        if name and all(x.name != name for x in authors):
            b = by_name.get(_fold(name))
            authors.append(Author(name=name, role=b.role if b else None, url=b.url if b else None,
                                  affiliation=b.affiliation if b else None))
    if authors:
        dbg["authors"] = "jsonld:author + html:.byline (role/url/affiliation)"
        for b in byline:  # fotógrafos/ilustradores que o JSON-LD omite
            if all(_fold(b.name) != _fold(x.name) for x in authors):
                authors.append(b)
    elif byline:
        authors, dbg["authors"] = byline, "html:.byline address"
    elif cfg.get("pageAuthors"):
        authors = [Author(name=n) for n in (_clean(x) for x in cfg["pageAuthors"]) if n]
        dbg["authors"] = "publicoConfig.pageAuthors"
    elif _meta(soup, "author"):
        authors, dbg["authors"] = [Author(name=_meta(soup, "author"))], "meta:author"
    agencies = _agencies([a.name for a in authors] + [a.affiliation for a in authors if a.affiliation]
                         + [x for x in cfg.get("pageAuthors") or [] if isinstance(x, str)]
                         + ([byline_raw] if byline_raw else []))
    if agencies:
        dbg["agencies"] = "autores/assinatura"

    # Datas (o pageDate do publicoConfig vem com hora local marcada como GMT — não usar)
    published = to_utc_iso(ld.get("datePublished"))
    if published:
        dbg["published_at"] = "jsonld:datePublished"
        dbg["published_at_precision"] = "jsonld (data e hora)"
    elif story is not None and story.select_one("time.dateline[datetime]"):
        published = to_utc_iso(story.select_one("time.dateline[datetime]")["datetime"])
        dbg["published_at"] = "html:time.dateline[datetime]"
    modified = to_utc_iso(ld.get("dateModified"))
    updated = modified if modified and modified != published else None
    if updated:
        dbg["updated_at"] = "jsonld:dateModified"

    # Secção e tags
    section = _clean(ld.get("articleSection"))
    if section:
        dbg["section"] = "jsonld:articleSection"
    elif isinstance(cfg.get("pageSection"), dict):
        section, dbg["section"] = _clean(cfg["pageSection"].get("name")), "publicoConfig.pageSection"
    tags = [t for t in (_clean(x) for x in (cfg.get("pageTags") or [])) if t]
    if tags:
        dbg["tags"] = "publicoConfig.pageTags"
    elif _meta(soup, "keywords"):
        tags, dbg["tags"] = [t.strip() for t in _meta(soup, "keywords").split(",") if t.strip()], "meta:keywords"
    elif story is not None:
        tags = [t for t in (_clean(x.get_text()) for x in story.select(".story__tags a.button--tag")) if t]
        if tags:
            dbg["tags"] = "html:.story__tags a.button--tag"

    seen: set[str] = set()
    tags = [t for t in tags if not (_fold(t) in seen or seen.add(_fold(t)))]  # sem duplicados

    # Tipo de peça
    raw = path_m["type"] if path_m else None
    piece_type = _piece_type(raw)
    if raw:
        dbg["piece_type_raw"] = dbg["piece_type"] = "url:<tipo>"
    body_tag = soup.find("body")
    if "tone--opinion" in (body_tag.get("class") or [] if body_tag else []) and piece_type in (None, "noticia"):
        piece_type, dbg["piece_type"] = "opiniao", "html:body.tone--opinion"

    # Acesso (o que o site diz) e corpo (o que extraímos)
    access = None
    if "isAccessibleForFree" in ld:
        free = ld["isAccessibleForFree"]
        access = ACCESS_FREE if (free is True or str(free).lower() == "true") else ACCESS_PREMIUM
        dbg["access"] = "jsonld:isAccessibleForFree"
    if cfg.get("isExclusivo") is True or cfg.get("isPremium") is True or cfg.get("lockItem") is True:
        access, dbg["access"] = ACCESS_PREMIUM, "publicoConfig.isExclusivo/isPremium/lockItem"
    elif access is None and "isExclusivo" in cfg:
        access, dbg["access"] = ACCESS_FREE, "publicoConfig.isExclusivo=false"
    paywall_markers = [sel for sel in PAYWALL_HTML_MARKERS if soup.select_one(sel)]
    if paywall_markers and access != ACCESS_PREMIUM:
        access, dbg["access"] = ACCESS_PREMIUM, "html:" + ",".join(paywall_markers)

    # Imagens (antes do corpo, que remove as figuras)
    images = _extract_images(story)
    if images:
        dbg["images"] = ("html:figure.story__media (principal) + #story-body figure; "
                         "crédito em figcaption > span.credit ('FOTÓGRAFO/AGÊNCIA'); JSON-LD image sem crédito")
    elif isinstance(ld.get("image"), dict) and ld["image"].get("url"):
        images = [Image(url=htmllib.unescape(ld["image"]["url"]), is_main=True)]
        dbg["images"] = "jsonld:image (sem crédito)"
    if images and not any(i.credit_raw for i in images):
        dbg["images_credit"] = "FALHA: imagem sem crédito na página"

    body: list[Block] = []
    body_source = None
    html_body, embeds, lstats = _body_blocks(
        story.select_one("#story-body, .story__body") if story is not None else None, canonical or url or BASE_URL)
    if ld.get("articleBody"):
        body = [Block(kind="p", text=t) for t in (_clean(p) for p in re.split(r"\n\s*\n|\r?\n", ld["articleBody"])) if t]
        body_source, dbg["body"] = "jsonld", "jsonld:articleBody"
        if body:
            for e in embeds:  # as posições do HTML não correspondem aos blocos do JSON-LD
                e.block_index = None
            dbg["body_links"] = "sem links: corpo do JSON-LD (texto simples)"
    if not body:
        body = html_body
        if body:
            body_source, dbg["body"] = "html", "html:#story-body p,h2-h4,li,blockquote (sem .pw-container/aside/figure/ad)"
            dbg["body_links"] = (f"html:#story-body a[href] nos blocos ({lstats['links']} links; "
                                 "sem aside.story__callout 'leia também', newsletter, paywall)")
    if lstats["noise_links"]:
        dbg["body_links_noise"] = (f"removidos {lstats['noise_links']} links de lojas de apps "
                                   f"(BODY_LINK_NOISE_HOSTS); {lstats['noise_blocks']} parágrafos de promoção descartados")
    if embeds:
        dbg["embeds"] = "; ".join(sorted(set(lstats["embed_sources"]))) + f" ({len(embeds)})"
    if lstats["skipped_embeds"]:
        dbg["embeds_skipped"] = (f"{lstats['skipped_embeds']} iframes em caixas 'leia também' "
                                 "(aside.story__callout) ignorados")
    truncated = bool(paywall_markers) or (
        story is not None and story.select_one(".is-paywalled, .paywall-block") is not None)
    premium_partial = False
    if body_source == "jsonld":
        body_complete, dbg["body_complete"] = True, "jsonld:articleBody"
    elif access == ACCESS_PREMIUM or truncated:
        # Premium sem texto integral no source code: o servidor corta o corpo (1.º parágrafo + gate Piano).
        premium_partial = True
        dbg["body_complete"] = (f"premium sem articleBody: HTML cortado ({len(body)} blocos, "
                                f"{sum(len(b.text.split()) for b in body)} palavras; corpo parcial descartado)")
        body, body_source, body_complete = [], None, False
        embeds = []
        for k in ("body", "body_links", "embeds"):
            dbg.pop(k, None)
    elif not body:
        body_complete = None
    else:
        body_complete = True
        dbg["body_complete"] = "access=free e sem marca de truncagem"
    word_count = sum(len(b.text.split()) for b in body) if body else None

    # Metadados do site
    site_meta: dict = {}
    kicker = story.select_one(".story__labels .kicker a") if story is not None else None
    if kicker:
        site_meta["kicker"] = _clean(kicker.get_text())
    for key, out_key in (("pageType", "page_type"), ("pageSponsored", "sponsored"), ("isExclusivo", "is_exclusivo"),
                         ("isPremium", "is_premium"), ("lockItem", "lock_item"), ("paywallSize", "paywall_size"),
                         ("isAzul", "is_azul"), ("pageTagsId", "tag_ids"), ("pageAuthorsSlug", "author_slugs")):
        if key in cfg:
            site_meta[out_key] = cfg[key]
    if isinstance(cfg.get("pageSection"), dict) and cfg["pageSection"].get("slug"):
        site_meta["section_slug"] = cfg["pageSection"]["slug"]
    if ld.get("image", {}).get("url") if isinstance(ld.get("image"), dict) else None:
        site_meta["image"] = htmllib.unescape(ld["image"]["url"])
    out_of_scope = None
    if premium_partial:
        out_of_scope, dbg["out_of_scope"] = "premium_sem_texto_integral", dbg["access"]
    elif path_m and _scope_reason(path_m):
        out_of_scope, dbg["out_of_scope"] = _scope_reason(path_m), "url"
    elif site_meta.get("sponsored") is True:
        out_of_scope, dbg["out_of_scope"] = "patrocinado", "publicoConfig.pageSponsored"
    elif byline_raw and _audio_byline(byline_raw):
        out_of_scope, dbg["out_of_scope"] = "podcast (byline de áudio)", "html:.byline"
    elif site_meta.get("page_type") and site_meta["page_type"].lower() in ("podcast", "video", "live", "liveblog"):
        out_of_scope, dbg["out_of_scope"] = site_meta["page_type"].lower(), "publicoConfig.pageType"

    return Article(
        url=url, canonical_url=canonical, aliases=aliases, site_article_id=art_id,
        title=title, lead=lead, body=body, embeds=embeds, authors=authors, agencies=agencies, byline_raw=byline_raw,
        images=images, published_at=published, published_at_precision="datetime" if published else None,
        updated_at=updated, section=section,
        subsection=None, tags=tags, piece_type=piece_type, piece_type_raw=raw,
        access=access, body_complete=body_complete, body_source=body_source, word_count=word_count,
        out_of_scope=out_of_scope, site_meta=site_meta, extraction_debug=dbg,
    )


# --- Runner --------------------------------------------------------------------------------------

def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("uso: python3 -m parsers.publico <homepage.html> <noticia.html> [sitemap_ou_feed.xml ...]",
              file=sys.stderr)
        return 2
    home_path, art_path, *xml_paths = map(Path, argv)
    out_dir = Path(__file__).resolve().parents[2] / "sites" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    items = parse_homepage(home_path.read_text(encoding="utf-8"))
    _dump(out_dir / f"{SITE}_homepage.json", [i.to_dict() for i in items])
    audit = [i for i in parse_homepage(home_path.read_text(encoding="utf-8"), include_excluded=True)
             if i.excluded_reason]
    _dump(out_dir / f"{SITE}_homepage_excluded.json", [i.to_dict() for i in audit])

    art_html = art_path.read_text(encoding="utf-8")
    canon = BeautifulSoup(art_html, "lxml").find("link", rel="canonical")
    art = parse_article(art_html, canon["href"] if canon else None)
    _dump(out_dir / f"{SITE}_article.json", art.to_dict())

    print(f"Homepage: {len(items)} artigos ({len(audit)} excluídos, ver {SITE}_homepage_excluded.json)")
    for i in items[:10]:
        print(f"  #{i.rank} [{i.site_article_id}] {i.zone or '-'} | {i.section or '-'} | "
              f"{i.piece_type or '-'} | {i.published_at or '-'} | {i.title}")
    print("\nArtigo:")
    print(f"  título:      {art.title}")
    print(f"  ID:          {art.site_article_id}")
    print(f"  autores:     {', '.join(f'{a.name} ({a.role or "-"})' for a in art.authors) or '-'}")
    print(f"  publicado:   {art.published_at}   actualizado: {art.updated_at}")
    print(f"  secção/tipo: {art.section} / {art.piece_type} ({art.piece_type_raw})")
    print(f"  acesso:      {art.access}  completo: {art.body_complete} ({art.body_source})  agências: {art.agencies}")
    for im in art.images:
        print(f"  imagem:      {'principal' if im.is_main else 'corpo'} | {im.photographers} | {im.agency} | {im.credit_raw}")
    print(f"  blocos:      {len(art.body)}  palavras: {art.word_count}  tags: {len(art.tags)}")
    print(f"  ligações:    {sum(len(b.links) for b in art.body)} no corpo  embeds: "
          f"{[(e.platform, e.block_index) for e in art.embeds]}")

    for xp in xml_paths:
        xml = xp.read_text(encoding="utf-8")
        is_feed = bool(re.search(r"<(rss|feed)[\s>]", xml[:2000]))
        parsed = parse_feed(xml) if is_feed else parse_sitemap(xml)
        _dump(out_dir / f"{SITE}_{xp.stem.removeprefix(SITE + '_')}.json", [i.to_dict() for i in parsed])
        print(f"\n{xp.name}: {len(parsed)} artigos ({'feed' if is_feed else 'sitemap'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
