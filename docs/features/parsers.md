# Parsers — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Funções puras que transformam o HTML/XML de cada site em dados estruturados: os links de artigos (homepage,
sitemap, feed) e o conteúdo editorial de cada artigo. Há um contrato comum (`parsers/base.py`) e um módulo por site.
Vive em `backend/parsers/` e é chamado pelo backend através de `registry.py`; os scripts PoC (`crawl_*.py`, runners por site) continuam a funcionar a partir da raiz (`sys.path`).

## Funcionalidades

### Contrato comum (v2.1)
- **O quê**: define o que cada parser devolve e as regras de âmbito, para os 3 sites produzirem dados iguais.
- **Como funciona**:
  - `parse_homepage(html, base_url, include_excluded=False) -> list[HomepageItem]` e
    `parse_article(html, url) -> Article`. Opcionais: `parse_sitemap_index`, `parse_sitemap`, `parse_feed`.
  - Datas sempre em **UTC** (`to_utc_iso()`; datas sem fuso = hora de Lisboa). Com `precision="date"` fica
    `AAAA-MM-DD`, sem conversão.
  - Preferência: dados estruturados (JSON-LD, meta, payloads JSON embebidos) e depois o HTML.
  - `extraction_debug` regista a fonte de cada campo (regra de debug do projecto).
- **Ficheiros-chave**: `backend/parsers/base.py`.
- **Adicionado/alterado em**: 2026-10-13 (v1 → v2 → v2.1, com as propostas dos 3 agentes de site).

### Regras de âmbito
- **Entram**: só peças editoriais do jornal (notícia, opinião, entrevista, análise, editorial, reportagem,
  factcheck, crítica, crónica, investigação).
- **Ficam de fora**: conteúdo patrocinado/promocional (incl. promoções institucionais do próprio jornal), vídeo puro,
  podcasts, live blogs e revistas/marcas do grupo (cada revista, se um dia entrar, é uma fonte independente).
- **Premium sem texto integral fica fora**: `out_of_scope="premium_sem_texto_integral"`, `body=[]`, sem guardar o
  corpo parcial. Se o premium se detectar antes (homepage/sitemap), o artigo nem é descarregado. Excepção: sites
  que entregam o texto integral no source code (Observador).
- **Exclusões auditáveis**: `include_excluded=True` devolve também os excluídos com `excluded_reason`.

### Campos extraídos
- **Homepage**: URL, ID interno, aliases, título, lead, autores, agências, byline, secção/subsecção, data (+ precisão),
  acesso, tipo de peça (normalizado + raw), zona/zonas, posição (rank).
- **Artigo**: URL canónico, aliases, ID, título, lead, corpo em blocos tipados (`p`/`h2`/`h3`/`li`/`quote`) com links
  inline, autores estruturados (nome, papel, URL, afiliação), agências, byline, datas, secção, tags (sem duplicados),
  tipo de peça, acesso, `body_complete`/`body_source`, `word_count`, `out_of_scope`, imagens.
- **Autores**: assinaturas colectivas ("JN/Agências", "Redação", "Agência Lusa") são aceites como autor; se indicarem
  agência, preenchem também `agencies`.
- **Imagens e fotógrafos**: `Image{url, caption, photographers, credit_raw, agency, is_main, is_archive}`. Os
  fotógrafos vão para o crédito da imagem, não para os autores (excepto quando a byline os lista como co-autores,
  com `role="fotografia"`).

### Registry (adaptador para o backend)
- **O quê**: `backend/parsers/registry.py` dá ao backend uma API única, independente do site:
  `discover(site, kind, text, url, include_excluded)`, `sitemap_index(site, text, config)` (última página de cada tipo de post
  no Observador; `latest` N) e `article(site, html, url)`.
- **Fixtures**: `backend/tests/fixtures/` (amostras reais usadas pelos testes).
- **Adicionado/alterado em**: 2026-10-13 (parsers movidos de `parsers/` para `backend/parsers/`).

### Parsers por site
| Site | Módulo | Notas | Fonte principal |
|---|---|---|---|
| Observador | `backend/parsers/observador.py` | [observador](../sites/observador.md) | HTML + JSON-LD + `contextualData` (WordPress) |
| JN | `backend/parsers/jn.py` | [jn](../sites/jn.md) | Payload RSC do Next.js (`self.__next_f.push`) + JSON-LD |
| Público | `backend/parsers/publico.py` | [publico](../sites/publico.md) | HTML + JSON-LD + `publicoConfig` |

- **JN, corpo completo**: artigo gratuito com corpo e sem caixa de paywall → `body_complete=True`. O `WordCount` do JN conta markup e embeds (ex.: 18136675: 219 palavras reais vs 949) e não serve de critério (ver [jn](../sites/jn.md)).

Cada módulo tem um runner: `python3 -m parsers.<site> <homepage.html> <artigo.html> [xml…]`.

### Scripts de crawl (PoC)
- **O quê**: `crawl_homepages.py [site…]` descarrega as homepages e `crawl_articles.py <site> <url…>` descarrega
  artigos. Ambos guardam o HTML com data e hora em `sites/raw/`, o JSON em `sites/out/`, e imprimem um diagnóstico
  (campos em falta, corpo curto ou incompleto, imagens sem crédito, ruído).
- **Como funciona**: User-Agent `FactosBot/0.1`, 1 s entre pedidos. O Público é corrido pelo utilizador (ver
  [fontes](fontes.md#robotstxt-e-acesso)).
- **Ficheiros-chave**: `crawl_homepages.py`, `crawl_articles.py`.

### Resultados do primeiro crawl real (2026-10-13)
| | Observador | JN | Público |
|---|---|---|---|
| Artigos no âmbito (homepage) | 170 | 72 | 90 |
| Artigos testados | 2 (1 premium com texto integral) | 2 (1 premium → fora) | 2 (1 premium → fora) |
| Crédito fotográfico | HTML (`.creditos`), alt na homepage | RSC `Media[].Producer` | HTML (`span.credit`) |
| Premium visível antes de abrir | não | sim (homepage) | não |

## Modelo de dados
Dataclasses em `backend/parsers/base.py`: `HomepageItem`, `Article`, `Block`, `Link`, `Author`, `Image`. Alimentam os
modelos Django de [crawl](crawl.md) e [fontes](fontes.md) (`Version.content` = `Article.to_dict`).

## Endpoints
Não aplicável (funções puras).

## Por fazer
- Mais amostras reais por site: notícia com imagens no corpo, artigo actualizado depois de publicado, opinião no
  Público, factcheck/crítica no Observador, live blogs e podcasts do JN.
- Validar `lastmod` dos sitemaps como sinal de nova versão (no Observador já dispara revisita, ver [versoes](versoes.md)).
- JN: confirmar se "Ciência na Europa" é parceria; ver se o image sitemap (`/feed/image/sitemap.xml`) traz créditos
  fotográficos; vigiar as classes CSS com hash e o formato do payload RSC (mudam com cada deploy do Next.js).
- Propostas pendentes para o contrato: `HomepageItem.images` e `tags`, secção como slug + nome, flag
  "Em atualização", tipo de media na homepage, normalização de `zone` entre sites, se o `rank` conta os excluídos.
- Alargar os testes automáticos (já há fixtures em `backend/tests/fixtures/`) a mais amostras de `sites/`.
- Remover os scripts PoC quando deixarem de ser úteis.
- Contrato: generalizar a regra do Observador para `updated_at` anterior a `published_at` (peças agendadas) → None,
  com o valor em `site_meta` e nota no debug.

## Notas e limitações
- Os parsers dependem da estrutura actual de cada site; classes CSS com hash (JN) e payloads internos podem mudar.
- Os créditos fotográficos não existem nos dados estruturados (JSON-LD) de nenhum dos 3 sites: só no HTML ou no payload.
