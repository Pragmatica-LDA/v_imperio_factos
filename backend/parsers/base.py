"""Contrato comum dos parsers de sites de notícias (v2.2).

Cada site implementa um módulo `parsers/<site>.py` com:

    SITE = "<site>"            # slug do site
    BASE_URL = "https://..."   # URL base, para resolver links relativos

    def parse_homepage(html: str, base_url: str = BASE_URL) -> list[HomepageItem]: ...
    def parse_article(html: str, url: str | None = None) -> Article: ...

    # Opcionais (quando o site tiver sitemaps/feeds):
    def parse_sitemap_index(xml: str) -> list[str]: ...          # URLs dos sitemaps filhos
    def parse_sitemap(xml: str) -> list[HomepageItem]: ...
    def parse_feed(xml: str) -> list[HomepageItem]: ...          # RSS/Atom

Regras:
- Funções puras: recebem HTML, devolvem dados. Sem pedidos HTTP.
- Âmbito: só peças editoriais do jornal. Ficam de fora: conteúdo patrocinado/promocional
  (incl. promoções institucionais do próprio jornal), vídeo puro, podcasts, live blogs,
  e revistas/marcas do grupo (cada revista, se um dia entrar, é uma fonte independente).
  Opinião, entrevista, reportagem, etc. entram.
- `parse_homepage`: sem duplicados (por `site_article_id` quando existe), URLs absolutos e
  normalizados (sem query string de tracking nem fragmento). Links alternativos do mesmo artigo
  (ex.: /n<ID>, AMP) vão para `aliases`.
- `parse_article`: só conteúdo editorial (sem "leia também", publicidade, newsletters,
  relacionados, pull quotes repetidas, promos). Se o texto integral estiver disponível no
  source code (ex.: JSON-LD `articleBody` em artigos premium), usa-se o texto integral.
- **Datas sempre em UTC**, ISO 8601 (`2026-10-13T11:19:00+00:00`). Usa `to_utc_iso()`.
  Excepção: com `*_precision="date"` a data fica `AAAA-MM-DD`, sem conversão (a meia-noite de
  Lisboa em UTC daria o dia anterior).
- Exclusões auditáveis: `parse_homepage(..., include_excluded=True)` devolve também os itens fora
  de âmbito com `excluded_reason` preenchido; por omissão só devolve os que estão no âmbito.
  No artigo, `out_of_scope` diz porque o artigo deve ser descartado (ou None).
- **Premium sem texto integral fica fora**: se o site marca o artigo como premium e o texto
  integral não está no source code, `out_of_scope="premium_sem_texto_integral"`, `body_complete=False`
  e o corpo parcial não é guardado (`body=[]`). Se o premium já se detecta na homepage/sitemap
  (`access="premium"`), o crawler não vai buscar o artigo — salvo regra específica do site
  (ex.: Observador, que entrega o texto integral no HTML).
- `tags` sem duplicados (comparação sem maiúsculas/acentos), pela ordem original.
- Assinaturas colectivas (ex.: "JN/Agências", "Redação", "Observador") são aceites como Author;
  se indicarem agência, preenche também `agencies`. A assinatura tal como aparece vai para `byline_raw`.
- Afiliação entre parênteses ("Nome (TSF)") vai para `Author.affiliation`.
- Fotógrafos: vão para `Article.images[].photographers` (crédito da imagem), não para `authors`
  — excepto se a byline do artigo os listar como co-autores (aí Author.role="fotografia").
- `updated_at` fica None se não existir ou for igual a `published_at`.
- **Ligações do corpo (v2.2)**: `Block.links` tem só as ligações editoriais dentro do texto do corpo (para
  outra notícia do site, outro site, redes sociais, documentos). `Article.embeds` tem os conteúdos embebidos
  no corpo (posts de Instagram/X/Facebook/TikTok, vídeos YouTube, etc.), com o URL do post original e o
  `block_index` (posição: índice do bloco seguinte em `body`). Ficam de fora: menus, "leia também",
  relacionados, tags, partilha, newsletters, lojas de apps, publicidade e links de autor. URLs absolutos;
  links de redireccionamento (t.co, l.facebook.com…) ficam como estão: a resolução é feita no pipeline.
- **Texto sem HTML**: títulos, leads, assinaturas, legendas, tags e blocos são texto simples (sem tags nem
  entidades HTML). Os dados estruturados também trazem HTML (ex.: JSON-LD `headline` do Público com `<em>`).
  `strip_html()` limpa; o `registry` aplica `clean_item()`/`clean_article()` a todos os sites como salvaguarda.
- Campos que não existem na página ficam None / lista vazia — nunca inventar.
- Preferir dados estruturados (JSON-LD, meta og:/article:, payloads JSON embebidos) e cair para o HTML.
- `extraction_debug`: para cada campo preenchido, de onde veio (ex.: "jsonld", "meta",
  "rsc", "html:.article-body p", "url"), e notas quando houve heurística.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")

# Valores normalizados de piece_type. O valor original do site vai sempre para piece_type_raw.
PIECE_TYPES = {
    "noticia", "opiniao", "entrevista", "analise", "editorial", "reportagem",
    "factcheck", "critica", "cronica", "investigacao",
}

# Valores de access
ACCESS_FREE = "free"
ACCESS_PREMIUM = "premium"

# Agência genérica quando a página não diz qual (ex.: assinatura "JN/Agências")
AGENCY_GENERIC = "Agências"


@dataclass
class Link:
    text: str
    url: str


@dataclass
class Embed:
    """Conteúdo embebido no corpo (post de rede social, vídeo, mapa…)."""
    url: str                       # URL do conteúdo original (ex.: https://www.instagram.com/p/XYZ/)
    platform: str | None = None    # pista do parser: "instagram" | "x" | "facebook" | "youtube" | "tiktok" | ...
    text: str | None = None        # texto visível do embed (legenda/citação), se existir
    block_index: int | None = None # posição no corpo (índice do bloco que se segue ao embed)


@dataclass
class Block:
    """Bloco do corpo do artigo, por ordem."""
    kind: str                                   # "p" | "h2" | "h3" | "li" | "quote"
    text: str
    links: list[Link] = field(default_factory=list)  # links inline (pistas de fontes citadas)


@dataclass
class Author:
    name: str
    role: str | None = None   # "texto" | "fotografia" | "video" | "infografia" | ...
    url: str | None = None    # página de autor no site, se existir
    affiliation: str | None = None   # ex.: "TSF" em "Nome (TSF)"


@dataclass
class Image:
    """Imagem editorial do artigo (principal e do corpo), com créditos."""
    url: str
    caption: str | None = None
    photographers: list[str] = field(default_factory=list)   # quem tirou a fotografia
    credit_raw: str | None = None   # crédito tal como aparece (ex.: "Rui Oliveira/Global Imagens", "Lusa/EPA")
    agency: str | None = None       # agência/banco de imagens, se indicado (Lusa, EPA, Reuters, Global Imagens…)
    is_main: bool = False           # imagem principal do artigo
    is_archive: bool = False        # foto de arquivo (ex.: crédito "Nome/Arquivo")


@dataclass
class HomepageItem:
    url: str
    site_article_id: str | None = None
    aliases: list[str] = field(default_factory=list)
    title: str | None = None
    lead: str | None = None
    authors: list[Author] = field(default_factory=list)
    agencies: list[str] = field(default_factory=list)
    byline_raw: str | None = None
    section: str | None = None
    subsection: str | None = None
    published_at: str | None = None              # UTC ISO 8601 (ou AAAA-MM-DD se precision="date")
    published_at_precision: str | None = None    # "datetime" | "date" | "time"
    access: str | None = None                    # ACCESS_FREE | ACCESS_PREMIUM
    piece_type: str | None = None                # um de PIECE_TYPES
    piece_type_raw: str | None = None
    zone: str | None = None                      # zona da 1.ª aparição (slug do site; normalização entre sites: por fazer)
    zones: list[str] = field(default_factory=list)   # todas as zonas onde a peça aparece
    rank: int | None = None                      # posição na homepage (0 = topo), pela ordem do HTML
    excluded_reason: str | None = None           # só com include_excluded=True
    site_meta: dict = field(default_factory=dict)
    extraction_debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Article:
    url: str | None = None
    canonical_url: str | None = None
    aliases: list[str] = field(default_factory=list)
    site_article_id: str | None = None
    title: str | None = None
    lead: str | None = None
    body: list[Block] = field(default_factory=list)
    authors: list[Author] = field(default_factory=list)
    agencies: list[str] = field(default_factory=list)   # ["Lusa"], ["AFP"], [AGENCY_GENERIC]…
    byline_raw: str | None = None
    images: list[Image] = field(default_factory=list)   # fotografias editoriais + créditos (fotógrafo)
    embeds: list[Embed] = field(default_factory=list)   # embeds do corpo (redes sociais, vídeos) — v2.2
    published_at: str | None = None              # UTC ISO 8601
    published_at_precision: str | None = None    # "datetime" | "date"
    updated_at: str | None = None                # UTC ISO 8601
    section: str | None = None
    subsection: str | None = None
    tags: list[str] = field(default_factory=list)
    piece_type: str | None = None                # um de PIECE_TYPES
    piece_type_raw: str | None = None
    access: str | None = None                    # ACCESS_FREE | ACCESS_PREMIUM (como o site marca)
    body_complete: bool | None = None            # o corpo extraído é o texto integral?
    body_source: str | None = None               # "html" | "jsonld" | "rsc" | ...
    word_count: int | None = None                # palavras do corpo extraído
    out_of_scope: str | None = None              # motivo para descartar (patrocinado, podcast…) ou None
    site_meta: dict = field(default_factory=dict)
    extraction_debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def to_utc_iso(value: str | datetime | None, naive_tz: ZoneInfo = LISBON) -> str | None:
    """Converte ISO 8601 / RFC 1123 / datetime para ISO 8601 em UTC.

    Datas sem fuso são interpretadas como hora de Lisboa. Devolve None se não conseguir.
    """
    if value is None or value == "":
        return None
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    else:
        s = value.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(s)
            except (TypeError, ValueError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.astimezone(timezone.utc).isoformat()


_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")


def strip_html(value: str | None) -> str | None:
    """Remove tags HTML e converte entidades (`&amp;`, `&nbsp;`…) em texto. Não toca em "a < b"."""
    if value is None:
        return None
    text = html.unescape(_TAG.sub("", value)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean_authors(authors: list) -> None:
    for a in authors:
        a.name = strip_html(a.name) or a.name
        a.affiliation = strip_html(a.affiliation)


def clean_item(item: "HomepageItem") -> "HomepageItem":
    for f in ("title", "lead", "byline_raw", "section", "subsection"):
        setattr(item, f, strip_html(getattr(item, f)))
    _clean_authors(item.authors)
    return item


def clean_article(article: "Article") -> "Article":
    for f in ("title", "lead", "byline_raw", "section", "subsection"):
        setattr(article, f, strip_html(getattr(article, f)))
    _clean_authors(article.authors)
    article.tags = [t for t in (strip_html(t) for t in article.tags) if t]
    for b in article.body:
        b.text = strip_html(b.text) or ""
        for link in b.links:
            link.text = strip_html(link.text) or ""
    for e in article.embeds:
        e.text = strip_html(e.text)
    for img in article.images:
        img.caption = strip_html(img.caption)
        img.credit_raw = strip_html(img.credit_raw)
    return article
