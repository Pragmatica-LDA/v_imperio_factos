"""Parser do Observador (observador.pt) — contrato v2 (parsers/base.py).

Ver docs/sites/observador.md para os padrões de URL, a estrutura da homepage, a origem de cada campo
e a estratégia de descoberta (sitemaps/RSS).

Uso:
    python3 -m parsers.observador sites/observador_homepage.html sites/observador_noticia.html \
        [--sitemap sites/observador_sitemap_post-243.xml ...] [--feed sites/observador_feed.xml]
"""

from __future__ import annotations

import difflib
import html as html_lib
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from parsers.base import (
    ACCESS_FREE,
    ACCESS_PREMIUM,
    LISBON,
    Article,
    Author,
    Block,
    Embed,
    HomepageItem,
    Image,
    Link,
    to_utc_iso,
)

SITE = "observador"
BASE_URL = "https://observador.pt/"

# ------------------------------------------------------------------------------------- configuração

# Artigos: notícias com data no path, opinião, especiais (longform) e fact checks.
# Ficam de fora: /liveblogs/, /programas/ (rádio/podcasts), /seccao/, /opiniao/autor/, /jogos/, etc.
ARTICLE_PATH_RE = re.compile(
    r"^/(?:(?P<date>\d{4}/\d{2}/\d{2})|(?P<kind>opiniao|especiais|factchecks))/(?P<slug>[^/]+)/$"
)
# Links de conteúdo fora de âmbito que se auditam com include_excluded=True.
EXCLUDABLE_PATH_RE = re.compile(r"^/(?:liveblogs/[^/]+|programas/[^/]+/[^/]+)/$")
# O permalink determina o tipo de post WordPress.
PATH_POST_TYPE = {"opiniao": "obs_opinion", "especiais": "obs_longform", "factchecks": "obs_factcheck"}
# Tipos de post editoriais (sitemaps wp-sitemap-posts-<tipo>-N.xml).
EDITORIAL_POST_TYPES = ("post", "obs_longform", "obs_opinion", "obs_factcheck")
# Classe do bloco da homepage (mod-posttype-<x>) -> tipo de post WordPress.
MOD_POST_TYPE = {"post": "post", "longform": "obs_longform", "opinion": "obs_opinion", "factcheck": "obs_factcheck"}
# Tipo de post -> piece_type. obs_longform decide-se pelo conteúdo (ver _longform_piece_type).
POST_TYPE_PIECE = {"post": "noticia", "obs_opinion": "opiniao", "obs_factcheck": "factcheck"}

# Classes de ID interno nos blocos da homepage: post-123, obs_longform-123, obs_opinion-123, ...
ID_CLASS_RE = re.compile(r"^(?:post|obs_[a-z]+)-(\d+)$")
POSTID_CLASS_RE = re.compile(r"^postid-(\d+)$")

# Âmbito (homepage): tipos de bloco que não são peças editoriais.
NOISE_MOD_CLASSES = {"mod-posttype-episode", "mod-posttype-game", "mod-posttype-liveblog"}
NOISE_ZONE_CLASSES = {"dark-mode-info", "dark-mode-switch-wrapper"}
NOISE_ZONE_TAGS = {"header", "nav", "footer"}
# Âmbito: secções/tópicos cujos itens são podcasts ou promoção dos podcasts do próprio jornal.
NOISE_TOPIC_PREFIXES = ("/seccao/podcasts/", "/programas/")
# Âmbito (feeds/sitemaps): paths que não são artigos (o feed "Últimas" mistura episódios e newsletters).
NOISE_PATH_PREFIXES = ("/programas/", "/newsletters/", "/liveblogs/", "/jogos/", "/radio/")

# Promoções inseridas no corpo, entre parênteses rectos (podcasts, newsletters, assinaturas).
PROMO_BRACKET_RE = re.compile(
    r"\[[^\[\]]*(?:Podcast|podcast|Spotify|Apple Podcasts|newsletter|Newsletter|assine|Assine|subscreva)[^\[\]]*\]"
)
# Blocos de ruído no corpo HTML (classes do próprio bloco ou de um antepassado dentro do contentor).
NOISE_BLOCK_CLASS_RE = re.compile(r"obs-ad|related|recommend|newsletter|mais-lidas|widget|embed|follow-columnist")
NOISE_BLOCK_TAGS = ["aside", "figure", "figcaption"]
# Embeds do corpo (v2.2): ficam fora dos blocos e vão para Article.embeds. Os "leia também" do WordPress
# (wp-embedded-content, para outro artigo do Observador) continuam a ser ruído, não embeds.
EMBED_NOISE_CLASS_RE = re.compile(r"obs-ad|related|recommend|newsletter|mais-lidas|widget|follow-columnist|wp-embedded")
EMBED_BLOCKQUOTE_PLATFORMS = {"twitter-tweet": "x", "twitter-video": "x", "instagram-media": "instagram",
                              "tiktok-embed": "tiktok", "fb-xfbml-parse-ignore": "facebook"}
EMBED_HOST_PLATFORMS = {"youtube.com": "youtube", "youtube-nocookie.com": "youtube", "youtu.be": "youtube",
                        "vimeo.com": "vimeo", "facebook.com": "facebook", "instagram.com": "instagram",
                        "twitter.com": "x", "x.com": "x", "tiktok.com": "tiktok", "spotify.com": "spotify",
                        "soundcloud.com": "soundcloud", "dailymotion.com": "dailymotion", "flourish.studio": "flourish",
                        "datawrapper.de": "datawrapper", "google.com": "google", "scribd.com": "scribd"}
# Iframes que não são conteúdo (tracking/publicidade).
EMBED_IFRAME_IGNORE_HOSTS = ("googletagmanager.com", "doubleclick.net", "googlesyndication.com")
TWEET_STATUS_RE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/[^/]+/status/\d+", re.I)
# Parâmetros de tracking removidos dos links inline (o resto da query fica: pode identificar o recurso).
TRACKING_PARAM_RE = re.compile(r"^(?:utm_\w+|fbclid|gclid|igshid|ref_src|ref_url|mc_cid|mc_eid)$", re.I)
# Parágrafos promocionais curtos com link (liveblog, "leia também", redes sociais, alertas).
PROMO_PARA_RE = re.compile(
    r"^(?:Acompanhe|Siga|Leia (?:também|mais|aqui)|Veja (?:também|aqui)|Ouça|Subscreva|Receba|Saiba mais)\b", re.I)
PROMO_PARA_MAX_LEN = 200
# Linhas de widgets que aparecem no articleBody do JSON-LD.
NOISE_LINES = {"As mais lidas", "Leia também", "Leia mais", "Veja também", "Ouça aqui"}
AD_SCRIPT_RE = re.compile(r"obs_ads\.queue_slot\(\{.*?\}\);", re.S)
# Fronteira de parágrafo colada no articleBody: pontuação final (após minúscula/dígito/fecho ou sigla de
# 2+ maiúsculas) ou aspas de fecho, seguidas sem espaço de maiúscula/aspas. Ex.: "sentado.“Por", "PSD.Ao".
GLUED_BREAK_RE = re.compile(
    r"(?:(?<=[a-zà-ÿ0-9\)»”%][.!?…])|(?<=[A-ZÀ-Ý]{2}[.!?…])|(?<=[a-zà-ÿ0-9\)»%][.!?…][”\"»])|(?<=[a-zà-ÿ0-9]”))"
    r"(?=[“\"«A-ZÀ-Ý])"
)
# Intertítulo recuperado do articleBody: bloco curto sem pontuação final de frase.
INTERTITLE_MAX_LEN = 120
INTERTITLE_END_RE = re.compile(r"[.!?…:;,]$|[.!?…][”\"»]$")
# Destaques (pull quotes): tamanho mínimo e fracção mínima de texto repetido noutro parágrafo.
PULL_QUOTE_MIN_LEN = 40
PULL_QUOTE_MIN_RATIO = 0.9
# Longform: sinais de reportagem (presença do jornalista no terreno) e de entrevista.
REPORTAGE_RE = re.compile(
    r"\b(reportagem|estivemos|fomos a|fomos ao|visitámos|chegámos|encontrámos|acompanhámos|percorremos)\b", re.I)
INTERVIEW_RE = re.compile(r"\bentrevista\b", re.I)
REPORTAGE_MIN_HITS = 2

# Corpo: o JSON-LD substitui o HTML se tiver > X vezes mais texto; o HTML é "completo" se cobrir ≥ Y do JSON-LD.
BODY_TRUNCATED_RATIO = 1.1
BODY_COMPLETE_MIN_COVER = 0.9

# Agências noticiosas reconhecidas na assinatura (autor) ou no fim do texto.
AGENCIES = {"lusa": "Lusa", "agência lusa": "Lusa", "afp": "AFP", "reuters": "Reuters", "efe": "EFE",
            "associated press": "AP", "ap": "AP", "bloomberg": "Bloomberg"}
AGENCY_TAIL_RE = re.compile(r"(?:^|[\s(—–-])\(?(Lusa|AFP|Reuters|EFE)\)?\s*\.?$")
AUTHOR_ROLES = {"texto": "texto", "fotografia": "fotografia", "fotos": "fotografia", "vídeo": "video",
                "video": "video", "infografia": "infografia", "ilustração": "ilustracao"}

# Créditos fotográficos: "NOME/AGÊNCIA", "AGÊNCIA/NOME[/POOL]" no fim do texto.
CREDIT_TAIL_RE = re.compile(
    r"(?:^|(?<=[\s.]))((?:[A-ZÀ-Ý][A-ZÀ-Ý'\-]*\.?\s?)+\s*/\s*[^/]+(?:/[^/]+)*)$")
PHOTO_AGENCIES = {"LUSA": "Lusa", "EPA": "EPA", "AFP": "AFP", "REUTERS": "Reuters", "AP": "AP",
                  "GETTY IMAGES": "Getty Images", "GETTYIMAGES": "Getty Images", "OBSERVADOR": "Observador",
                  "SPUTNIK": "Sputnik", "EFE": "EFE", "GLOBAL IMAGENS": "Global Imagens", "ANADOLU": "Anadolu"}
CREDIT_NOISE = {"POOL", "KREMLIN POOL", "HANDOUT", "ARQUIVO", "ARCHIVE", "FILE"}
ARCHIVE_RE = re.compile(r"\b(arquivo|archive|file photo)\b", re.I)
NAME_PARTICLES = {"de", "da", "do", "das", "dos", "e"}

PT_MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
             "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9", "dc": "http://purl.org/dc/elements/1.1/",
      "media": "http://search.yahoo.com/mrss/"}


# --------------------------------------------------------------------------------------------- utils

def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    # Alguns títulos da homepage vêm com entidades duplamente escapadas ("&amp;nbsp;" -> "&nbsp;").
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    return text or None


def normalize_url(href: str, base_url: str = BASE_URL) -> str | None:
    """URL absoluto, https, sem query/fragmento, com barra final. None se não for do observador.pt."""
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    parts = urlsplit(urljoin(base_url, href.strip()))
    host = parts.netloc.lower().removeprefix("www.")
    if host != "observador.pt":
        return None
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", host, path, "", ""))


def _abs_url(href: str | None) -> str | None:
    """URL absoluto sem fragmento (para links inline, que podem ser externos)."""
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    return urljoin(BASE_URL, href.strip()).split("#")[0] or None


def _strip_tracking(url: str) -> str:
    """Remove parâmetros de tracking (utm_*, fbclid, ref_src…) mantendo o resto da query."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAM_RE.match(k)]
    return urlunsplit(parts._replace(query=urlencode(q)))


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().split(":")[0].removeprefix("www.")


def _platform(url: str) -> str | None:
    host = _host(url)
    return next((p for h, p in EMBED_HOST_PLATFORMS.items() if host == h or host.endswith("." + h)), None)


def _article_path_match(url: str) -> re.Match | None:
    return ARTICLE_PATH_RE.match(urlsplit(url).path)


def _post_type_from_url(url: str) -> str | None:
    m = _article_path_match(url)
    if not m:
        return None
    return "post" if m.group("date") else PATH_POST_TYPE[m.group("kind")]


def _utc(value: str | None) -> str | None:
    """UTC ISO 8601. A homepage tem um '}' perdido no fim do datetime."""
    value = _clean(value)
    return to_utc_iso(value.rstrip("}").strip()) if value else None


def _classes(tag: Tag) -> list[str]:
    return tag.get("class") or []


def _slugify(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _section_names(soup: BeautifulSoup) -> dict[str, str]:
    """slug -> nome, a partir dos links de secção de topo (/seccao/<slug>/) presentes na página."""
    names: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        parts = [p for p in urlsplit(urljoin(BASE_URL, a["href"])).path.split("/") if p]
        text = _clean(a.get_text(" "))
        if len(parts) == 2 and parts[0] == "seccao" and text and parts[1] not in names and len(text) < 40:
            names[parts[1]] = text
    return names


def _topic_path(box: Tag | None) -> str | None:
    topic = box.select_one("a.topic") if box else None
    return urlsplit(urljoin(BASE_URL, topic["href"])).path if topic and topic.get("href") else None


# ------------------------------------------------------------------------------------------ homepage

def _noise_reason(a: Tag, url: str) -> str | None:
    """Motivo de exclusão (fora de âmbito) de uma ocorrência de link, ou None se é peça editorial."""
    path = urlsplit(url).path
    if path.startswith("/liveblogs/"):
        return "live blog"
    if path.startswith("/programas/"):
        return "podcast/rádio (episódio)"
    for p in a.parents:
        if not isinstance(p, Tag):
            continue
        if p.name in NOISE_ZONE_TAGS:
            return "navegação (header/nav/footer)"
        cls = set(_classes(p))
        if cls & NOISE_ZONE_CLASSES:
            return "promoção institucional (dark mode)"
        if "mod-posttype-episode" in cls:
            return "podcast/rádio (episódio)"
        if "mod-posttype-game" in cls:
            return "jogo"
        if "mod-posttype-liveblog" in cls:
            return "live blog"
    tp = _topic_path(_container(a))
    if tp and tp.startswith(NOISE_TOPIC_PREFIXES):
        return f"podcast / promoção dos podcasts do jornal (a.topic {tp})"
    return None


def _container(a: Tag) -> Tag | None:
    """Bloco do artigo: .mod, artigo do widget "três artigos" ou <li> das listas (últimas, populares)."""
    for p in a.parents:
        if not isinstance(p, Tag) or p.name in ("body", "main"):
            return None
        cls = set(_classes(p))
        if "mod" in cls or "widgettype-tres-artigos-article" in cls or p.name == "li":
            return p
        if cls & {"fbg-row", "fbg-col-4"}:
            return None
    return None


def _zone(a: Tag, first_row: Tag | None) -> str:
    """Zona da homepage: widget com nome próprio, título da linha da grelha, ou "destaque"/"grelha"."""
    for p in a.parents:
        if not isinstance(p, Tag):
            continue
        cls = " ".join(_classes(p))
        if "mod-widgettype-latest" in cls:
            return "ultimas"
        if "mod-widgettype-populares" in cls:
            return "mais-populares"
        if "opinion-list-container" in cls:
            return "opiniao"
        if "fbg-row" in _classes(p) and p.find_parent(class_="fbg-row") is None:
            if p is first_row:
                return "destaque"
            title = p.select_one(".generic-title, .widget-title")
            t = _clean(title.get_text(" ")) if title else None
            return _slugify(t.rstrip("→ ").strip()) if t else "grelha"
    return "grelha"


def _hhmm_with_url_date(url: str, hhmm: str) -> str | None:
    """Lista "Últimas": só mostra HH:MM; a data vem do permalink (hora de Lisboa)."""
    m = _article_path_match(url)
    t = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm or "")
    if not (m and m.group("date") and t):
        return None
    y, mo, d = map(int, m.group("date").split("/"))
    return to_utc_iso(datetime(y, mo, d, int(t.group(1)), int(t.group(2)), tzinfo=LISBON))


def _item_from(a: Tag, url: str, sections: dict[str, str]) -> HomepageItem:
    box = _container(a)
    dbg: dict[str, str] = {}
    item = HomepageItem(url=url)

    # Título: na lista "Últimas" o link contém a hora (<span class="date">) e o título (<h1 class="title">).
    inner = a.select_one(".title")
    item.title = _clean((inner or a).get_text(" "))
    if item.title:
        dbg["title"] = "html:a .title" if inner else "html:a"
    elif _clean(a.get("aria-label")):
        item.title, dbg["title"] = _clean(a.get("aria-label")), "html:a[aria-label]"

    post_type = _post_type_from_url(url)
    if post_type:
        item.piece_type_raw, dbg["piece_type_raw"] = post_type, "url (permalink do tipo de post)"

    if box is not None:
        if not item.title:
            t = box.select_one(".title a, h1 a, h2 a, h3 a")
            if t and _clean(t.get_text(" ")):
                item.title, dbg["title"] = _clean(t.get_text(" ")), "html:.title a"
        cls = _classes(box)
        for c in cls:
            m = ID_CLASS_RE.match(c)
            if m:
                item.site_article_id, dbg["site_article_id"] = m.group(1), "html:.mod class (post-N/obs_<tipo>-N)"
                break
        mod_type = next((c.removeprefix("mod-posttype-") for c in cls if c.startswith("mod-posttype-")), None)
        if mod_type in MOD_POST_TYPE:
            item.piece_type_raw, dbg["piece_type_raw"] = MOD_POST_TYPE[mod_type], "html:.mod-posttype-*"

        time_el = box.find("time", attrs={"datetime": True})
        date_span = box.select_one(".date")
        if time_el and _utc(time_el["datetime"]):
            item.published_at, item.published_at_precision = _utc(time_el["datetime"]), "datetime"
            dbg["published_at"] = "html:time.timeago[datetime]"
        elif date_span and _hhmm_with_url_date(url, _clean(date_span.get_text()) or ""):
            item.published_at = _hhmm_with_url_date(url, _clean(date_span.get_text()))
            item.published_at_precision = "datetime"
            dbg["published_at"] = "heurística: data do URL + hora HH:MM da lista (Europe/Lisbon)"

        lead = box.select_one(".lead") or box.select_one(".widgettype-tres-artigos-article > p")
        if lead and _clean(lead.get_text(" ")):
            item.lead, dbg["lead"] = _clean(lead.get_text(" ")), "html:.lead"

        for col in box.select(".columnist-name a"):
            name = _clean(col.get_text(" "))
            if name:
                item.authors.append(Author(name=name, url=_abs_url(col.get("href"))))
        if item.authors:
            item.byline_raw = _clean(box.select_one(".columnist-name").get_text(" "))
            dbg["authors"] = dbg["byline_raw"] = "html:.columnist-name a"

        img = box.find("img")
        if img and (img_url := _image_url(img)):
            people, agency, credit = parse_credit(img.get("alt") or "")
            item.site_meta["image"] = {"url": img_url, "credit_raw": credit, "photographers": people,
                                       "agency": agency}
            dbg["site_meta.image"] = "html:img (src original; crédito no fim do alt)" if credit \
                else "html:img (sem crédito no alt)"

        # Secção: a.topic aponta para /seccao/<topo>/<sub>/.../ — topo pelo nome no menu, sub pelo texto.
        topic = box.select_one("a.topic")
        path = _topic_path(box)
        if topic and path and path.startswith("/seccao/"):
            parts = [p for p in path.split("/") if p][1:]
            item.section = sections.get(parts[0], parts[0])
            item.site_meta["section_slug"] = parts[0]
            dbg["section"] = "html:a.topic[href] (1.º nível) + nome do menu" if parts[0] in sections \
                else "html:a.topic[href] (slug, sem nome no menu)"
            if len(parts) > 1:
                item.subsection, dbg["subsection"] = _clean(topic.get_text(" ")), "html:a.topic (texto)"

        rating = box.select_one(".rating[class*=stars-]")
        if rating:
            m = re.search(r"stars-(\d)", " ".join(_classes(rating)))
            item.site_meta["rating"] = int(m.group(1)) if m else None
        if box.select_one(".photogallery-prefix"):
            item.site_meta["photogallery"] = True
        flag = box.select_one(".flag")
        if flag and _clean(flag.get_text()):
            item.site_meta["flag"] = _clean(flag.get_text())   # ex.: "Em atualização"

    # ID nos contadores de comentários (data-link + data-id), quando o bloco não o expõe na classe.
    if not item.site_article_id:
        scope = box or a.parent
        span = scope.find(attrs={"data-link": True, "data-id": True}) if scope else None
        if span and normalize_url(span["data-link"]) == url and span["data-id"].isdigit():
            item.site_article_id, dbg["site_article_id"] = span["data-id"], "html:[data-link][data-id]"

    # piece_type: crítica (estrelas) > tipo de post; longform fica por decidir (precisa do conteúdo).
    if item.site_meta.get("rating") is not None:
        item.piece_type, dbg["piece_type"] = "critica", "html:.rating (estrelas)"
    elif item.piece_type_raw in POST_TYPE_PIECE:
        item.piece_type, dbg["piece_type"] = POST_TYPE_PIECE[item.piece_type_raw], "piece_type_raw"
    item.extraction_debug = dbg
    return item


def _merge(cur: HomepageItem, new: HomepageItem) -> None:
    for f in ("title", "site_article_id", "lead", "byline_raw", "section", "subsection", "published_at",
              "published_at_precision", "piece_type", "piece_type_raw"):
        if not getattr(cur, f) and getattr(new, f):
            setattr(cur, f, getattr(new, f))
            if f in new.extraction_debug:
                cur.extraction_debug[f] = new.extraction_debug[f]
    if not cur.authors and new.authors:
        cur.authors, cur.extraction_debug["authors"] = new.authors, new.extraction_debug.get("authors")
    for k, v in new.site_meta.items():
        cur.site_meta.setdefault(k, v)
    if new.url != cur.url and new.url not in cur.aliases:
        cur.aliases.append(new.url)
    if new.zone and new.zone not in cur.zones:
        cur.zones.append(new.zone)


def parse_homepage(html: str, base_url: str = BASE_URL, include_excluded: bool = False) -> list[HomepageItem]:
    soup = BeautifulSoup(html, "lxml")
    sections = _section_names(soup)
    first_row = soup.select_one("main .fbg-row")
    by_url: dict[str, HomepageItem] = {}
    by_id: dict[str, HomepageItem] = {}
    out: list[HomepageItem] = []
    excluded: dict[str, HomepageItem] = {}
    for a in soup.find_all("a", href=True):
        url = normalize_url(a["href"], base_url)
        if not url:
            continue
        is_article = bool(_article_path_match(url))
        if not is_article and not EXCLUDABLE_PATH_RE.match(urlsplit(url).path):
            continue
        reason = _noise_reason(a, url)
        new = _item_from(a, url, sections)
        new.zone = _zone(a, first_row)
        new.zones = [new.zone]
        if reason:
            # Uma peça excluída numa zona pode estar no âmbito noutra (decide-se no fim).
            if url not in excluded:
                new.excluded_reason = reason
                new.extraction_debug["excluded_reason"] = "regras de âmbito (_noise_reason)"
                excluded[url] = new
            else:
                _merge(excluded[url], new)
            continue
        cur = by_url.get(url) or (by_id.get(new.site_article_id) if new.site_article_id else None)
        if cur is None:
            new.rank = len(out)
            new.extraction_debug.update(zone="html:linha da grelha/widget", zones="todas as ocorrências",
                                        rank="ordem no HTML (1.ª ocorrência)")
            out.append(new)
            cur = new
        else:
            _merge(cur, new)
        by_url[url] = cur
        if cur.site_article_id:
            by_id[cur.site_article_id] = cur
    if include_excluded:
        out += [i for u, i in excluded.items() if u not in by_url]
    return out


# ------------------------------------------------------------------------------- sitemaps e RSS

def parse_sitemap(xml: str) -> list[HomepageItem]:
    """wp-sitemap-posts-<tipo>-N.xml: só <loc> e <lastmod> (= data de modificação, não de publicação).

    Para um índice (<sitemapindex>) devolve lista vazia — usar `parse_sitemap_index`.
    """
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    out: list[HomepageItem] = []
    seen: set[str] = set()
    for i, u in enumerate(root.findall("sm:url", NS)):
        loc = (u.findtext("sm:loc", default="", namespaces=NS) or "").strip()
        url = normalize_url(loc)
        if not url or url in seen or not _article_path_match(url):
            continue
        seen.add(url)
        item = HomepageItem(url=url, rank=i, piece_type_raw=_post_type_from_url(url))
        dbg = {"url": "sitemap:loc", "piece_type_raw": "url (permalink do tipo de post)",
               "rank": "posição no sitemap (ordem crescente de ID)"}
        if item.piece_type_raw in POST_TYPE_PIECE:
            item.piece_type, dbg["piece_type"] = POST_TYPE_PIECE[item.piece_type_raw], "piece_type_raw"
        lastmod = to_utc_iso(u.findtext("sm:lastmod", default="", namespaces=NS))
        if lastmod:
            item.site_meta["lastmod"], dbg["site_meta.lastmod"] = lastmod, "sitemap:lastmod (UTC)"
        m = _article_path_match(url)
        if m.group("date"):
            # Data local de publicação no permalink (só notícias): AAAA-MM-DD, sem conversão para UTC.
            item.published_at, item.published_at_precision = m.group("date").replace("/", "-"), "date"
            dbg["published_at"] = "url (/AAAA/MM/DD/)"
        item.extraction_debug = dbg
        out.append(item)
    return out


def parse_sitemap_index(xml: str, post_types: tuple[str, ...] = EDITORIAL_POST_TYPES) -> list[str]:
    """Índice wp-sitemap.xml -> URLs dos sitemaps filhos dos tipos editoriais, por tipo e página.

    Cada tipo tem páginas de 2000 URLs por ordem crescente de ID: a última página de cada tipo tem os
    artigos mais recentes. Os restantes tipos (obs_episode, obs_liveblog, obs_newsletter, taxonomias,
    utilizadores, ...) ficam de fora do âmbito.
    """
    root = ET.fromstring(xml.encode("utf-8"))
    found: list[tuple[int, int, str]] = []
    for loc in root.findall("sm:sitemap/sm:loc", NS):
        m = re.search(r"wp-sitemap-posts-([a-z_]+)-(\d+)\.xml$", loc.text or "")
        if m and m.group(1) in post_types:
            found.append((post_types.index(m.group(1)), int(m.group(2)), loc.text.strip()))
    return [u for _, _, u in sorted(found)]


def parse_feed(xml: str) -> list[HomepageItem]:
    """RSS "Últimas" (https://observador.pt/feed/): título, lead, autor, categorias e pubDate. Sem ID."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    out: list[HomepageItem] = []
    seen: set[str] = set()
    for i, it in enumerate(root.iter("item")):
        url = normalize_url((it.findtext("link") or it.findtext("guid") or "").strip())
        if not url or url in seen:
            continue
        path = urlsplit(url).path
        if path.startswith(NOISE_PATH_PREFIXES) or not _article_path_match(url):
            continue   # episódios de rádio/podcast, newsletters, live blogs
        seen.add(url)
        item = HomepageItem(url=url, rank=i, zone="rss", piece_type_raw=_post_type_from_url(url))
        dbg = {"url": "rss:link", "rank": "ordem no feed", "piece_type_raw": "url (permalink do tipo de post)"}
        if (t := _clean(it.findtext("title"))):
            item.title, dbg["title"] = t, "rss:title"
        if (d := _clean(it.findtext("description"))):
            item.lead, dbg["lead"] = d, "rss:description"
        if (p := to_utc_iso(_clean(it.findtext("pubDate")))):
            item.published_at, item.published_at_precision, dbg["published_at"] = p, "datetime", "rss:pubDate"
        creators = [c for c in (_clean(x.text) for x in it.findall("dc:creator", NS)) if c]
        if creators:
            item.byline_raw = ", ".join(creators)
            item.authors = [_author_from_name(n) for n in _split_names(item.byline_raw)]
            dbg["byline_raw"] = dbg["authors"] = "rss:dc:creator"
            item.agencies = sorted({AGENCIES[a.name.lower()] for a in item.authors if a.name.lower() in AGENCIES})
            if item.agencies:
                dbg["agencies"] = "rss:dc:creator (assinatura de agência)"
        media = it.find("media:content", NS)
        if media is not None and media.get("url"):
            people, agency, credit = parse_credit(media.findtext("media:credit", default="", namespaces=NS))
            item.site_meta["image"] = {"url": media.get("url"), "credit_raw": credit, "photographers": people,
                                       "agency": agency}
            dbg["site_meta.image"] = "rss:media:content + media:credit"
        cats = [c for c in (_clean(x.text) for x in it.findall("category")) if c]
        if cats:
            # As categorias vêm sem hierarquia; não se escolhe secção — ficam em site_meta.
            item.site_meta["categories"], dbg["site_meta.categories"] = cats, "rss:category"
        if item.piece_type_raw in POST_TYPE_PIECE:
            item.piece_type, dbg["piece_type"] = POST_TYPE_PIECE[item.piece_type_raw], "piece_type_raw"
        item.extraction_debug = dbg
        out.append(item)
    return out


# ------------------------------------------------------------------------------------------- article

def _news_article_ld(soup: BeautifulSoup) -> dict:
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") in ("NewsArticle", "Article", "OpinionNewsArticle",
                                                           "ReportageNewsArticle", "AnalysisNewsArticle"):
                return d
    return {}


def _contextual(html: str) -> dict:
    """Campos úteis do `var contextualData = {...}` (JS, não JSON): pageTargeting + post.*"""
    out: dict = {}
    m = re.search(r"pageTargeting:\s*(\{.*?\})\s*,\s*\n", html)
    if m:
        try:
            out["pageTargeting"] = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    i = html.find("var contextualData")
    blk = html[i:html.find("</script>", i)] if i >= 0 else ""
    for key, rx in {
        "postType": r"postType:\s*'([^']+)'",
        "premium": r"premium:\s*(true|false)",
        "articleIsPremium": r"articleIsPremium:\s*(true|false)",
        "contentLength": r"contentLength:\s*(\d+)",
        "sensitive": r"sensitive:\s*(\d+)",
        "isAnInitiative": r"isAnInitiative:\s*(true|false)",
        "smallTitle": r"smallTitle:\s*\"((?:[^\"\\]|\\.)*)\"",
        "mainCategory": r"mainCategory:\s*\{\s*slug:\s*\"([^\"]+)\"",
        "topLevelCategory": r"topLevelCategory:\s*\{\s*slug:\s*\"([^\"]+)\"",
    }.items():
        mm = re.search(rx, blk)
        if mm:
            v = mm.group(1)
            if v in ("true", "false"):
                v = v == "true"
            elif v.isdigit():
                v = int(v)
            elif key == "smallTitle":
                v = json.loads(f'"{v}"')
            out[key] = v
    return out


def _meta(soup: BeautifulSoup, key: str) -> str | None:
    m = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return _clean(m.get("content")) if m else None


def _norm_cmp(text: str) -> str:
    """Texto para comparar HTML vs JSON-LD (o HTML tem espaços a mais à volta das tags)."""
    return re.sub(r"\s+", "", text)


def _block_text(el: Tag) -> str | None:
    return _clean(re.sub(r"\s+([,.;:!?])", r"\1", el.get_text(" ")))


def _iframe_url(src: str) -> str:
    """URL do conteúdo original a partir do src de um iframe de embed (player → página do conteúdo)."""
    url = urljoin("https:", src.strip())
    parts, host = urlsplit(url), _host(url)
    if host in ("youtube.com", "youtube-nocookie.com") and (m := re.match(r"/embed/([\w-]{6,})", parts.path)):
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    if host == "player.vimeo.com" and (m := re.match(r"/video/(\d+)", parts.path)):
        return f"https://vimeo.com/{m.group(1)}"
    if host == "facebook.com" and parts.path.startswith("/plugins/"):
        href = parse_qs(parts.query).get("href", [None])[0]
        return unquote(href) if href else url
    if host == "open.spotify.com" and parts.path.startswith("/embed/"):
        return urlunsplit(("https", "open.spotify.com", parts.path.removeprefix("/embed"), "", ""))
    return url


def _embed_from(el: Tag) -> tuple[Embed, str] | None:
    """Embed (redes sociais, vídeo, gráficos) a partir de um elemento do corpo, com a origem para o debug."""
    cls = _classes(el)
    if el.name == "blockquote" and (kind := next((c for c in cls if c in EMBED_BLOCKQUOTE_PLATFORMS), None)):
        platform = EMBED_BLOCKQUOTE_PLATFORMS[kind]
        hrefs = [a["href"] for a in el.find_all("a", href=True)]
        if platform == "x":
            # O link da data ("October 12, 2026") é o permalink do tweet; os outros são t.co/hashtags/menções.
            url = next((h for h in reversed(hrefs) if TWEET_STATUS_RE.match(h)), None)
            paras = [p for p in el.find_all("p") if not _clean(p.get_text(" ")).startswith("—")] or el.find_all("p")
            text = _clean(" ".join(p.get_text(" ") for p in paras))
        elif platform == "instagram":
            url = el.get("data-instgrm-permalink") or next((h for h in hrefs if "instagram.com/" in h), None)
            text = _clean(" ".join(p.get_text(" ") for p in el.find_all("p")))
        else:
            url = el.get("cite") or (hrefs[0] if hrefs else None)
            text = _clean(el.get_text(" "))
        if not url:
            return None
        url = _strip_tracking(url.split("#")[0])
        return Embed(url=TWEET_STATUS_RE.match(url).group(0) if platform == "x" and TWEET_STATUS_RE.match(url)
                     else url, platform=platform, text=text), f"html:blockquote.{kind}"
    if el.name == "div" and (kind := next((c for c in cls if c in ("fb-post", "fb-video")), None)) \
            and el.get("data-href"):
        return Embed(url=el["data-href"], platform="facebook"), f"html:div.{kind}[data-href]"
    if el.name == "iframe":
        src = el.get("src") or el.get("data-src") or el.get("data-lazy-src")
        if not src or src.startswith(("about:", "javascript:")):
            return None
        host = _host(urljoin("https:", src))
        if host == "observador.pt" or any(host == h or host.endswith("." + h) for h in EMBED_IFRAME_IGNORE_HOSTS):
            return None
        url = _iframe_url(src)
        return Embed(url=url, platform=_platform(url), text=_clean(el.get("title"))), "html:iframe[src]"
    return None


def _html_blocks(soup: BeautifulSoup) -> tuple[list[Block], list[tuple[Embed, int, str]]]:
    """Blocos e embeds do corpo, por ordem do documento.

    O corpo vive em `.article-body-wrapper`: vários `.article-body-content` (o artigo premium vem partido em 2:
    a parte visível e a parte "paga", que o Piano esconde no browser mas está no HTML) intercalados com
    `.article-block.block-html` (embeds de Facebook/Instagram). Os embeds (tweets, Instagram, iframes de
    YouTube/Facebook…) não entram nos blocos; saem como (Embed, índice do bloco seguinte, origem)."""
    out: list[Block] = []
    embeds: list[tuple[Embed, int, str]] = []
    kinds = {"p": "p", "h1": "h2", "h2": "h2", "h3": "h3", "h4": "h3", "blockquote": "quote", "li": "li"}
    root = soup.select_one(".article-body-wrapper") or soup
    # O texto editorial acaba em #article-end-marker; depois vêm rodapés ("Siga-me…", "Receba um alerta…").
    end = root.find(id="article-end-marker")
    after_end = {id(e) for e in end.find_all_next()} if end else set()
    inside_embed: set[int] = set()
    for el in root.find_all([*kinds, "iframe", "div"]):
        if id(el) in after_end or id(el) in inside_embed:
            continue
        cont = el.find_parent(class_=["article-body-content", "block-html"])
        if cont is None:
            continue
        in_cont = [x for x in [el, *el.parents] if x is not cont and isinstance(x, Tag) and cont in x.parents]
        if (found := _embed_from(el)) is not None:
            inside_embed.update(id(d) for d in el.find_all(True))
            if not any(EMBED_NOISE_CLASS_RE.search(" ".join(_classes(x))) for x in in_cont):
                embeds.append((found[0], len(out), found[1]))
            continue
        if el.name not in kinds or "article-body-content" not in _classes(cont):
            continue
        # Só blocos editoriais: fora de anúncios, widgets, recomendações e embeds WordPress
        # (blockquote.wp-embedded-content = "leia também" para outro artigo).
        if any(NOISE_BLOCK_CLASS_RE.search(" ".join(_classes(x))) for x in in_cont) \
                or el.find_parent(NOISE_BLOCK_TAGS):
            continue
        # Evita duplicar texto de blocos aninhados (ex.: <p> dentro de <blockquote>).
        outer = el.find_parent(["p", "blockquote", "li"])
        if outer is not None and cont in outer.parents:
            continue
        text = _block_text(el)
        if not text or text in NOISE_LINES or PROMO_BRACKET_RE.fullmatch(text):
            continue
        # Promo curta com link interno: "Acompanhe o nosso liveblog…", "Leia também…", "Siga-me…".
        if len(text) <= PROMO_PARA_MAX_LEN and PROMO_PARA_RE.match(text) and el.find("a", href=True):
            continue
        links = [Link(text=t, url=_strip_tracking(u)) for a in el.find_all("a", href=True)
                 if (t := _clean(a.get_text(" "))) and (u := _abs_url(a["href"]))]
        out.append(Block(kind=kinds[el.name], text=text, links=links))
    return out, embeds


def _split_article_body(article_body: str) -> list[str]:
    """Parte o articleBody do JSON-LD em parágrafos e remove anúncios, widgets e promoções."""
    text = AD_SCRIPT_RE.sub("\n", article_body)
    text = PROMO_BRACKET_RE.sub("\n", text)
    out: list[str] = []
    for block in text.split("\n"):
        block = _clean(block)
        if not block or block in NOISE_LINES:
            continue
        for piece in GLUED_BREAK_RE.split(block):
            piece = _clean(piece)
            if piece and piece not in NOISE_LINES:
                out.append(piece)
    return out


def _is_intertitle(text: str, is_last: bool) -> bool:
    return not is_last and len(text) <= INTERTITLE_MAX_LEN and not INTERTITLE_END_RE.search(text)


def _contained_ratio(short: str, long: str) -> float:
    """Fracção de `short` que aparece, por ordem, dentro de `long`."""
    sm = difflib.SequenceMatcher(None, short, long, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(short)


def _drop_pull_quotes(blocks: list[Block], min_len: int = PULL_QUOTE_MIN_LEN,
                      min_ratio: float = PULL_QUOTE_MIN_RATIO) -> tuple[list[Block], int]:
    """Remove destaques (pull quotes): blocos repetidos (por vezes ligeiramente editados) dentro de outro."""
    keys = [_norm_cmp(b.text).lower().rstrip(".!?…”\"") for b in blocks]
    out = []
    for i, b in enumerate(blocks):
        k = keys[i]
        if len(k) >= min_len and any(
            j != i and len(keys[j]) > len(k) and (k in keys[j] or _contained_ratio(k, keys[j]) >= min_ratio)
            for j in range(len(blocks))
        ):
            continue
        out.append(b)
    return out, len(blocks) - len(out)


def _agencies(authors: list[Author], blocks: list[Block]) -> tuple[list[str], str | None]:
    found = [AGENCIES[a.name.lower()] for a in authors if a.name.lower() in AGENCIES]
    if found:
        return sorted(set(found)), "autor"
    if blocks:
        m = AGENCY_TAIL_RE.search(blocks[-1].text)
        if m:
            return [AGENCIES[m.group(1).lower()]], "html/jsonld: fim do último parágrafo"
    return [], None


def _longform_piece_type(title: str, lead: str, tags: list[str], body: list[Block]) -> tuple[str, str]:
    """obs_longform (Especiais) inclui reportagens, análises, perfis e entrevistas: decide pelo conteúdo."""
    head = " ".join([title, lead] + tags)
    if INTERVIEW_RE.search(head):
        return "entrevista", "heurística: 'entrevista' no título/lead/tags"
    hits = len(REPORTAGE_RE.findall(" ".join([head] + [b.text for b in body])))
    if hits >= REPORTAGE_MIN_HITS:
        return "reportagem", f"heurística: {hits} marcas de reportagem (1.ª pessoa no terreno / 'reportagem')"
    return "analise", f"heurística: longform sem marcas de reportagem/entrevista ({hits} marcas)"


def _split_names(byline: str) -> list[str]:
    """"A, B e C" -> ["A", "B", "C"] (sem partir "(…)" de afiliações)."""
    return [n.strip() for n in re.split(r",\s*|\s+e\s+(?![^()]*\))", byline) if n.strip()]


def _author_from_name(name: str, role: str | None = None, url: str | None = None) -> Author:
    """"Nome (TSF)" -> Author(name="Nome", affiliation="TSF")."""
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", name.strip())
    if m:
        return Author(name=m.group(1).strip(), role=role, url=url, affiliation=m.group(2).strip())
    return Author(name=name.strip(), role=role, url=url)


def _fold(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold().strip()


def _dedupe_tags(tags) -> list[str]:
    """Sem duplicados (sem maiúsculas nem acentos), pela ordem original."""
    seen, out = set(), []
    for t in tags:
        if _fold(t) not in seen:
            seen.add(_fold(t))
            out.append(t)
    return out


def _title_name(name: str) -> str:
    """'ESTELA SILVA' -> 'Estela Silva' (só se vier todo em maiúsculas)."""
    name = _clean(name) or ""
    if name != name.upper():
        return name
    return " ".join(w if w.lower() not in NAME_PARTICLES else w.lower() for w in name.title().split())


def parse_credit(raw: str | None) -> tuple[list[str], str | None, str | None]:
    """Crédito fotográfico -> (fotógrafos, agência, crédito tal como aparece).

    Formatos vistos: "ESTELA SILVA/LUSA", "EPA/SHAWN THEW", "EPA/WILL OLIVER / POOL",
    "TOMÁS SILVA/OBSERVADOR", "GettyImages-2296043780". Também aceita o fim de uma legenda Lusa
    ("... 11 de outubro de 2026. ESTELA SILVA/LUSA").
    """
    raw = _clean(raw)
    if not raw:
        return [], None, None
    m = re.search(r"Getty\s*Images?(?:-\d+)?\s*$", raw, re.I)
    if m:
        return [], "Getty Images", m.group(0).strip()
    m = CREDIT_TAIL_RE.search(raw)
    if not m:
        return [], None, None
    credit = _clean(m.group(1))
    if re.search(r"HANDOUT|EDITORIAL USE", credit, re.I):
        return [], None, credit
    parts = [p.strip() for p in credit.split("/") if p.strip()]
    agency = next((PHOTO_AGENCIES[p.upper()] for p in parts if p.upper() in PHOTO_AGENCIES), None)
    if agency is None:
        # Sem agência conhecida não se distingue fotógrafo de fonte ("INE/Pordata"): só o crédito bruto.
        return [], None, credit
    people = [_title_name(p) for p in parts if p.upper() not in PHOTO_AGENCIES and p.upper() not in CREDIT_NOISE]
    return people, agency, credit


def _image_url(img: Tag) -> str | None:
    """URL original no S3 (o src passa pelo redimensionador bordalo: .../plain/<url original>)."""
    src = img.get("src") or img.get("data-src") or ""
    m = re.search(r"/plain/(https?://\S+)$", src)
    return m.group(1) if m else (_abs_url(src) if src else None)


def _article_images(soup: BeautifulSoup) -> tuple[list[Image], str]:
    out: list[Image] = []
    notes = []
    head = soup.select_one("figure.article-head-image")
    figs = ([(head, True)] if head else []) + [
        (f, False) for f in soup.select(".article-body-content figure, .article-body-content .wp-caption")]
    for fig, is_main in figs:
        img = fig.find("img")
        url = _image_url(img) if img else None
        if not url:
            continue
        cap = fig.select_one(".legenda") or fig.select_one(".wp-caption-text") or fig.select_one("figcaption")
        caption = _clean(re.sub(r"^▲\s*", "", cap.get_text(" ", strip=True))) if cap else None
        cred_el = fig.select_one(".creditos")
        src = "html:figcaption .creditos" if cred_el else "html:img[alt] (fim da legenda)"
        people, agency, credit = parse_credit(cred_el.get_text(" ") if cred_el else (img.get("alt") or ""))
        if not caption and img.get("alt"):
            caption = _clean(img["alt"])
        out.append(Image(url=url, caption=caption, photographers=people, credit_raw=credit, agency=agency,
                         is_main=is_main, is_archive=bool(credit and ARCHIVE_RE.search(credit))))
        notes.append(f"{'principal' if is_main else 'corpo'}: {src if credit else 'sem crédito'}")
    # Imagens soltas no corpo (sem <figure>): sem legenda nem crédito.
    loose = [im for im in soup.select(".article-body-content img") if not im.find_parent("figure")
             and not im.find_parent(class_=re.compile(r"obs-ad|widget|embed"))]
    if loose:
        notes.append(f"{len(loose)} imagem(ns) solta(s) no corpo sem legenda/crédito ignorada(s) (promo?)")
    return out, "; ".join(notes) + " (jsonld:image não tem crédito)"


def parse_article(html: str, url: str | None = None) -> Article:
    soup = BeautifulSoup(html, "lxml")
    ld = _news_article_ld(soup)
    ctx = _contextual(html)
    pt = ctx.get("pageTargeting", {})
    body_cls = _classes(soup.body) if soup.body else []
    art = Article(url=url)
    dbg: dict[str, str] = {}

    # URL canónico, aliases e ID interno.
    canon = soup.find("link", rel="canonical")
    if canon and canon.get("href"):
        art.canonical_url, dbg["canonical_url"] = normalize_url(canon["href"]), "html:link[rel=canonical]"
    elif _meta(soup, "og:url"):
        art.canonical_url, dbg["canonical_url"] = normalize_url(_meta(soup, "og:url")), "meta:og:url"
    for alt in (url, _meta(soup, "og:url")):
        n = normalize_url(alt) if alt else None
        if n and n != art.canonical_url and n not in art.aliases:
            art.aliases.append(n)
    if art.aliases:
        dbg["aliases"] = "url pedido / og:url diferentes do canónico"
    for c in body_cls:
        if (m := POSTID_CLASS_RE.match(c)):
            art.site_article_id, dbg["site_article_id"] = m.group(1), "html:body.postid-N"
            break
    if not art.site_article_id and (el := soup.find("article", id=re.compile(r"-\d+$"))):
        art.site_article_id, dbg["site_article_id"] = el["id"].rsplit("-", 1)[1], "html:article[id]"

    # Título e lead.
    h1 = soup.select_one(".article-head-content-headline-title") or soup.select_one("article h1")
    if _clean(ld.get("headline")):
        art.title, dbg["title"] = _clean(ld["headline"]), "jsonld:headline"
    elif _meta(soup, "og:title"):
        art.title, dbg["title"] = _meta(soup, "og:title"), "meta:og:title"
    elif h1:
        art.title, dbg["title"] = _clean(h1.get_text(" ")), "html:h1"
    lead = soup.select_one(".article-head-main-info-lead") or soup.select_one(".article-head-content-headline-lead")
    if lead and _clean(lead.get_text(" ")):
        art.lead, dbg["lead"] = _clean(lead.get_text(" ")), f"html:.{_classes(lead)[0]}"
    elif _clean(ld.get("description")):
        art.lead, dbg["lead"] = _clean(ld["description"]), "jsonld:description"

    # Autores: nomes do JSON-LD, enriquecidos com papel ("Texto") e página de perfil do HTML.
    html_auth = {}
    for li in soup.select(".article-head-authors li.author"):
        name = _clean(li.select_one(".author-name").get_text(" ")) if li.select_one(".author-name") else None
        if not name:
            continue
        credit = _clean(li.select_one(".author-credit").get_text(" ")) if li.select_one(".author-credit") else None
        a = li.find("a", href=True)
        html_auth[name] = Author(name=name, role=AUTHOR_ROLES.get((credit or "").lower(), (credit or "").lower() or None),
                                 url=_abs_url(a["href"]) if a else None)
    # Opinião: cabeça própria com colunista(s) e descrição ("Publisher e colunista do Observador").
    columnist_desc = []
    for col in soup.select(".article-head-columnnists .columnist"):
        nm = col.select_one(".columnist-info-name")
        name = _clean(nm.get_text(" ")) if nm else None
        if not name:
            continue
        a = nm.find_parent("a", href=True)
        html_auth[name] = Author(name=name, role="texto", url=_abs_url(a["href"]) if a else None)
        if (d := col.select_one(".columnist-description")) and _clean(d.get_text(" ")):
            columnist_desc.append(_clean(d.get_text(" ")))
    ld_auth = ld.get("author") or []
    ld_names = [n for n in (_clean(x.get("name") if isinstance(x, dict) else x)
                            for x in (ld_auth if isinstance(ld_auth, list) else [ld_auth])) if n]
    names = ld_names or list(html_auth) or [n.strip() for n in (_meta(soup, "author") or "").split(",") if n.strip()]
    authors = [html_auth.get(n) or _author_from_name(n) for n in names]
    byline = ", ".join(_clean(e.get_text(" ")) for e in
                       soup.select(".article-head-authors li.author .author-name, "
                                   ".article-head-columnnists .columnist-info-name") if _clean(e.get_text(" ")))
    art.byline_raw = byline or _meta(soup, "author")
    if art.byline_raw:
        dbg["byline_raw"] = "html:.author-name / .columnist-info-name" if byline else "meta:author"
    dbg_auth = "jsonld:author" if ld_names else ("html:.article-head-authors" if html_auth else "meta:author")
    if html_auth and ld_names:
        dbg_auth += " + html:.author-credit/.columnist (papel e perfil)"

    # Assinaturas colectivas ("Agência Lusa", "Observador") ficam como Author; agências vão também
    # para `agencies` (mais abaixo).
    art.authors = authors
    if art.authors:
        dbg["authors"] = dbg_auth

    # Datas (UTC).
    modified_before_publish = None
    for field_, keys in (("published_at", [("jsonld:datePublished", ld.get("datePublished")),
                                            ("meta:article:published_time", _meta(soup, "article:published_time")),
                                            ("meta:pub_date", _meta(soup, "pub_date"))]),
                         ("updated_at", [("jsonld:dateModified", ld.get("dateModified")),
                                         ("meta:article:modified_time", _meta(soup, "article:modified_time"))])):
        for src, v in keys:
            if (u := _utc(v)):
                setattr(art, field_, u)
                dbg[field_] = src
                if field_ == "published_at":
                    art.published_at_precision = "datetime"
                break
    if art.updated_at and art.updated_at == art.published_at:
        art.updated_at = None
        dbg.pop("updated_at", None)
    elif art.updated_at and art.published_at and art.updated_at < art.published_at:
        # Peças agendadas: a última edição (dateModified) é anterior à hora de publicação.
        dbg["updated_at"] = (f"descartado: dateModified ({art.updated_at}) anterior a datePublished "
                             f"(publicação agendada; última edição antes de sair)")
        modified_before_publish = art.updated_at
        art.updated_at = None

    # Secção (JSON-LD) e subsecção (categoria principal do contextualData, com o nome do link no artigo).
    if isinstance(ld.get("articleSection"), str) and _clean(ld["articleSection"]):
        art.section, dbg["section"] = _clean(ld["articleSection"]), "jsonld:articleSection"
    main_cat, top_cat = ctx.get("mainCategory") or pt.get("category"), ctx.get("topLevelCategory") or pt.get("topCategory")
    if main_cat and main_cat != top_cat:
        link = soup.select_one(f"article a[href$='/{main_cat}/'][href*='/seccao/']")
        art.subsection = _clean(link.get_text(" ")) if link else main_cat
        dbg["subsection"] = "contextualData.mainCategory + html:article a[href*=/seccao/] (nome)" if link \
            else "contextualData.mainCategory (slug)"

    # Tags (keywords vem como uma única string separada por vírgulas).
    kws = ld.get("keywords") or []
    kws = [kws] if isinstance(kws, str) else kws
    art.tags = _dedupe_tags(t for t in (_clean(x) for k in kws for x in k.split(",")) if t)
    if art.tags:
        dbg["tags"] = "jsonld:keywords"
    elif (tags := [t for t in (_clean(a.get_text(" ")) for a in soup.select("article a[href*='/seccao/']")) if t]):
        art.tags, dbg["tags"] = _dedupe_tags(tags), "html:article a[href*=/seccao/]"

    # Acesso: como o site marca.
    premium_signals = []
    if ld.get("isAccessibleForFree") in (False, "False", "false"):
        premium_signals.append("jsonld:isAccessibleForFree=false")
    if "premium-article" in body_cls:
        premium_signals.append("html:body.premium-article")
    if ctx.get("articleIsPremium"):
        premium_signals.append("contextualData.articleIsPremium")
    if premium_signals:
        art.access, dbg["access"] = ACCESS_PREMIUM, " + ".join(premium_signals)
    elif ld.get("isAccessibleForFree") in (True, "True", "true") or soup.body is not None:
        art.access, dbg["access"] = ACCESS_FREE, "sem marcas de premium (jsonld/body/contextualData)"

    # Corpo: HTML (com links inline). Nos premium o HTML traz o texto todo (o Piano só o esconde no browser);
    # se um dia vier truncado e o JSON-LD trouxer mais texto, usa-se o articleBody integral e reaproveitam-se
    # os blocos HTML coincidentes (prefixo visível).
    html_blocks, html_embeds = _html_blocks(soup)
    body, art.body_source = html_blocks, "html"
    body_note = ("html:.article-body-content (todos os contentores; p, h1.tinymceh1→h2, h2-h4, blockquote, li); "
                 "promos [..] e anúncios removidos")
    ld_body = ld.get("articleBody")
    ld_len = html_cover = None
    if isinstance(ld_body, str) and ld_body.strip():
        pieces = _split_article_body(ld_body)
        ld_len = len(_norm_cmp("".join(pieces)))
        # O articleBody inclui o texto dos embeds (ex.: tweets), que no HTML saem do corpo: conta-se para a cobertura.
        html_len = len(_norm_cmp("".join([*(b.text for b in html_blocks), *(e.text or "" for e, _, _ in html_embeds)])))
        html_cover = html_len / ld_len if ld_len else None
        if ld_len > html_len * BODY_TRUNCATED_RATIO:
            body, reused, h2s = [], 0, 0
            for i, piece in enumerate(pieces):
                if reused == i and i < len(html_blocks) and _norm_cmp(html_blocks[i].text) == _norm_cmp(piece):
                    body.append(html_blocks[i])
                    reused += 1
                elif _is_intertitle(piece, i == len(pieces) - 1):
                    body.append(Block(kind="h2", text=piece))
                    h2s += 1
                else:
                    body.append(Block(kind="p", text=piece))
            art.body_source = "jsonld"
            body_note = (f"jsonld:articleBody (split de parágrafos colados por regex); {reused} blocos iniciais "
                         f"cruzados com o HTML visível (têm links inline); restantes {len(pieces) - reused} sem "
                         f"links (o articleBody é texto simples); {h2s} intertítulos h2 por heurística "
                         f"(curto, sem pontuação final)")
    body, dropped = _drop_pull_quotes(body)
    if dropped:
        body_note += f"; {dropped} destaque(s)/pull quote(s) removido(s)"
    art.body = body
    if body:
        dbg["body"] = body_note
        art.word_count = sum(len(b.text.split()) for b in body)
        dbg["word_count"] = "contagem de palavras do corpo extraído"
    # Embeds: block_index = índice, no corpo final, do 1.º bloco HTML que se seguia ao embed e sobreviveu
    # (pull quotes removidas / corpo do JSON-LD); len(body) se o embed fecha o corpo.
    if html_embeds:
        srcs = {}
        for emb, anchor, src in html_embeds:
            emb.block_index = next((i for b in html_blocks[anchor:] for i, x in enumerate(body)
                                    if x is b or _norm_cmp(x.text) == _norm_cmp(b.text)), len(body))
            art.embeds.append(emb)
            srcs[src] = srcs.get(src, 0) + 1
        dbg["embeds"] = (", ".join(f"{n}× {s_}" for s_, n in srcs.items()) + " (dentro de .article-body-wrapper, "
                         "antes de #article-end-marker; tweets: permalink /status/, sem t.co/hashtags; "
                         "iframes: player→URL do conteúdo; block_index = bloco seguinte no corpo final)")
    if art.body_source == "jsonld":
        art.body_complete = True
        dbg["body_complete"] = "jsonld:articleBody é o texto integral"
    elif html_cover is not None:
        # O articleBody inclui destaques que o corpo não tem: cobertura ≥ BODY_COMPLETE_MIN_COVER chega.
        art.body_complete = html_cover >= BODY_COMPLETE_MIN_COVER
        dbg["body_complete"] = f"html cobre {html_cover:.0%} do texto do jsonld:articleBody"
    elif body:
        art.body_complete = art.access != ACCESS_PREMIUM
        dbg["body_complete"] = "sem articleBody para comparar: aberto→completo, premium→desconhecido (False)"

    # Premium sem texto integral no source code: fora de âmbito e sem corpo parcial (regra do contrato).
    premium_truncated = art.access == ACCESS_PREMIUM and not art.body_complete

    art.images, img_dbg = _article_images(soup)
    if art.images:
        dbg["images"] = img_dbg
    elif soup.select_one(".article-head-columnnists"):
        dbg["images"] = "sem imagem editorial: a opinião só tem a foto do colunista (também em jsonld:image/og:image)"

    art.agencies, src = _agencies(authors, body)
    if art.agencies:
        dbg["agencies"] = src

    # Tipo de peça.
    raw = next((c for c in body_cls if c in EDITORIAL_POST_TYPES + ("obs_episode", "obs_liveblog")), None) \
        or ctx.get("postType") or pt.get("postType")
    if raw:
        art.piece_type_raw, dbg["piece_type_raw"] = raw, "html:body class / contextualData.postType"
    elif (u := art.canonical_url or url) and _post_type_from_url(u):
        art.piece_type_raw, dbg["piece_type_raw"] = _post_type_from_url(u), "url"
    if art.piece_type_raw == "obs_longform":
        art.piece_type, dbg["piece_type"] = _longform_piece_type(art.title or "", art.lead or "", art.tags, body)
    elif art.piece_type_raw in POST_TYPE_PIECE:
        art.piece_type, dbg["piece_type"] = POST_TYPE_PIECE[art.piece_type_raw], "piece_type_raw"

    # Metadados do site e âmbito.
    meta = {
        "post_type": art.piece_type_raw,
        "small_title": ctx.get("smallTitle"),
        "main_category": main_cat,
        "top_category": top_cat,
        "exclusive": pt.get("exclusive"),
        "sponsored": pt.get("sponsored"),
        "is_initiative": ctx.get("isAnInitiative"),
        "sensitive": ctx.get("sensitive"),
        "jsonld_word_count": ld.get("wordCount"),
        "content_length": ctx.get("contentLength"),
        "html_blocks": len(html_blocks),
    }
    meta["modified_before_publish"] = modified_before_publish
    meta["columnist_description"] = "; ".join(columnist_desc) or None
    art.site_meta = {k: v for k, v in meta.items() if v is not None}
    # Âmbito: premium truncado, patrocinado/iniciativa comercial, podcasts e live blogs.
    if premium_truncated:
        art.out_of_scope = "premium_sem_texto_integral"
        art.body, art.embeds, art.body_complete, art.word_count = [], [], False, None
        dbg["body"] = f"descartado (premium sem texto integral); antes: {dbg.get('body')}"
        dbg.pop("word_count", None)
        dbg.pop("embeds", None)
    elif pt.get("sponsored"):
        art.out_of_scope = "patrocinado (contextualData.pageTargeting.sponsored)"
    elif ctx.get("isAnInitiative"):
        art.out_of_scope = "iniciativa/parceria comercial (contextualData.post.isAnInitiative)"
    elif art.piece_type_raw in ("obs_episode", "obs_liveblog") or (art.canonical_url or "").startswith(
            ("https://observador.pt/programas/", "https://observador.pt/liveblogs/")):
        art.out_of_scope = "podcast/rádio ou live blog"
    if art.out_of_scope:
        dbg["out_of_scope"] = "regras de âmbito (contextualData / tipo de post)"
    if art.site_meta:
        dbg["site_meta"] = "contextualData (pageTargeting + post.*), jsonld:wordCount"
    art.extraction_debug = dbg
    return art


# -------------------------------------------------------------------------------------------- runner

def _summary_items(label: str, items: list[HomepageItem], n: int = 10) -> None:
    def cnt(f):
        return sum(1 for i in items if f(i))
    print(f"== {label}: {len(items)} artigos")
    print(f"   com ID: {cnt(lambda i: i.site_article_id)} · data: {cnt(lambda i: i.published_at)} · "
          f"secção: {cnt(lambda i: i.section)} · lead: {cnt(lambda i: i.lead)} · autores: {cnt(lambda i: i.authors)} · "
          f"piece_type: {cnt(lambda i: i.piece_type)}")
    for i in items[:n]:
        print(f"   {i.rank:>3} [{i.site_article_id or '-'}] {i.published_at or '-'} | {i.zone or '-'} | "
              f"{i.section or '-'}/{i.subsection or '-'} | {i.piece_type or i.piece_type_raw or '-'} | {i.title}")


def main(argv: list[str]) -> int:
    args, sitemaps, feeds = [], [], []
    it = iter(argv)
    for a in it:
        if a == "--sitemap":
            sitemaps.append(Path(next(it)))
        elif a == "--feed":
            feeds.append(Path(next(it)))
        else:
            args.append(a)
    if len(args) != 2:
        print(__doc__.split("Uso:")[1], file=sys.stderr)
        return 2
    hp_path, art_path = map(Path, args)
    out_dir = Path(__file__).resolve().parents[2] / "sites" / "out"   # raiz do projecto, independente do cwd
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, data) -> None:
        (out_dir / f"{SITE}_{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    hp_html = hp_path.read_text(encoding="utf-8")
    items = parse_homepage(hp_html)
    dump("homepage", [i.to_dict() for i in items])
    _summary_items("Homepage", items)
    excl = [i for i in parse_homepage(hp_html, include_excluded=True) if i.excluded_reason]
    dump("homepage_excluded", [i.to_dict() for i in excl])
    reasons: dict[str, int] = {}
    for i in excl:
        reasons[i.excluded_reason] = reasons.get(i.excluded_reason, 0) + 1
    print(f"   excluídos: {len(excl)} {reasons}")

    if sitemaps:
        sm_items = [i for p in sitemaps for i in parse_sitemap(p.read_text(encoding="utf-8"))]
        dump("sitemap", [i.to_dict() for i in sm_items])
        print(f"== Sitemaps ({len(sitemaps)} ficheiros): {len(sm_items)} artigos")
    if feeds:
        fd_items = [i for p in feeds for i in parse_feed(p.read_text(encoding="utf-8"))]
        dump("feed", [i.to_dict() for i in fd_items])
        _summary_items("RSS", fd_items, n=3)

    article = parse_article(art_path.read_text(encoding="utf-8"))
    dump("article", article.to_dict())
    kinds = {k: sum(1 for b in article.body if b.kind == k) for k in {b.kind for b in article.body}}
    print("== Artigo")
    print(f"   título:     {article.title}")
    print(f"   ID:         {article.site_article_id} · tipo: {article.piece_type} ({article.piece_type_raw})")
    print(f"   acesso:     {article.access} · corpo completo: {article.body_complete} · fonte: {article.body_source}")
    print(f"   autores:    {', '.join(f'{a.name} ({a.role})' for a in article.authors) or '-'}")
    print(f"   agências:   {', '.join(article.agencies) or '-'}")
    print(f"   publicado:  {article.published_at} · actualizado: {article.updated_at}")
    print(f"   secção:     {article.section} / {article.subsection} · tags: {', '.join(article.tags) or '-'}")
    for im in article.images:
        print(f"   imagem:     {'principal' if im.is_main else 'corpo'} · {im.credit_raw} → {im.photographers} / {im.agency}")
    print(f"   âmbito:     {article.out_of_scope or 'ok'}")
    print(f"   corpo:      {len(article.body)} blocos {kinds} · {article.word_count} palavras · "
          f"{sum(len(b.links) for b in article.body)} links inline · {len(article.embeds)} embeds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
