# Público (www.publico.pt)

> Estado: ⚠️ parcial (parser v2.2 validado; descoberta por sitemap/RSS por validar)  ·  Última actualização: 2026-10-13
> Código: `backend/parsers/publico.py`  ·  Contrato: `backend/parsers/base.py` (v2.2)  ·  Área: [parsers](../features/parsers.md)

Runner (a partir de `backend/`): `python3 -m parsers.publico <homepage.html> <artigo.html> [sitemap_ou_feed.xml …]`
→ `sites/out/publico_homepage.json`, `sites/out/publico_homepage_excluded.json` (auditoria, `include_excluded=True`),
`sites/out/publico_article.json` (+ `sites/out/publico_<ficheiro>.json` por XML).

## Amostras validadas
| Ficheiro | O que é | Resultado |
|---|---|---|
| `sites/publico_homepage.html` | homepage (exemplo) | 92 artigos, 27 excluídos |
| `sites/publico_noticia.html` | 2191197, notícia aberta | 7 blocos, 475 palavras, foto José Coelho/Lusa |
| `sites/raw/publico_homepage_20261013T120356Z.html` | homepage real | 90 artigos, 27 excluídos, 0 premium marcados |
| `sites/raw/publico_article_2191168_*.html` | notícia aberta, assinatura "Lusa e PÚBLICO" | 6 blocos, `agencies=["Lusa"]`, foto de arquivo |
| `sites/raw/publico_article_2190775_*.html` | reportagem exclusiva | `out_of_scope="premium_sem_texto_integral"` |

As homepages e os artigos reais foram descarregados pelo utilizador. Os agentes Claude não fazem pedidos ao
publico.pt (ver "Descoberta").

## URLs e ID interno
- **Artigo**: `/AAAA/MM/DD/<secção>/<tipo>/<slug>-<ID>` (ex.: `/2026/10/13/ciencia/noticia/peritos-…-2191197`).
- **ID**: número no fim do slug (7 dígitos hoje). Igual em `data-article-id` (cards e `<article id="story">`),
  `publicoConfig.pageArticleId` e `cXenseParse:recs:articleid`. **O slug muda com o título; o ID não.**
- **Link curto**: `/n<ID>` (redirecciona para o URL completo) → vai para `aliases`. `/v<ID>` = vídeo (ignorado).
  A página do artigo não declara o link curto (nem `shortlink` nem AMP), por isso `Article.aliases` só fica preenchido
  quando o URL pedido difere do canónico.
- **Tipos vistos** (`<tipo>` → `piece_type`, o original fica em `piece_type_raw`): `noticia`, `entrevista`, `reportagem`,
  `investigacao`, `cronica`, `critica`, `editorial`, `opiniao`, `cronica_de_jogo` → `noticia` (relato de jogo).
  `podcast` fica de fora. Vídeos: `/AAAA/MM/DD/video/<slug>-<AAAAMMDD-HHMMSS>` (sem ID de artigo).
- Normalização: `https://www.publico.pt` + path, sem query (`?ref=…&cx=…`) nem fragmento.

## Âmbito (listas configuráveis no topo do módulo)
Fora:
- **Secções**: `estudiop` (Estúdio P, patrocinado), `edicoes-publico` (promoções institucionais), `video`.
- **Tipos**: `podcast`, `video`, `interactivo`, `directo/aovivo`, `conteudo_patrocinado`, galerias.
- **Zonas inteiras** (o ID fica excluído em toda a página): `podcasts`, `conheca-o-publico`, `estudio-p`.
  Na zona Podcasts há episódios publicados com URL `/noticia/` ou `/cronica/`.
- **Cards**: `tone--paid`, `data-article-type` `VIDEO`/`EXTERNOS`, byline com papéis de áudio ("edição de som",
  "sonoplastia", "narração"). Apanha, por exemplo, o podcast "Devida Vénia" que aparece noutras zonas com URL `/noticia/`.
- **Relacionados** com rótulo `<b>Vídeo</b>`/`Podcast`.

Dentro: P3, Fugas, Ípsilon, Ímpar, Azul e Público Brasil, que são marcas da redacção dentro de www.publico.pt.
Ficam marcados em `site_meta.brand`; com `EXCLUDE_GROUP_BRANDS = True` passam a ficar de fora.

## Homepage (`parse_homepage`)
- Cada peça é um `<article class="article article--level-N … tone--<tom>" data-article-id data-article-slug data-article-type>`.
- **Zonas**: `section.block[data-collection]`, com o título em `header > h1.block__title` (ex.: Destaques, Magazine,
  Futebol, Escolha dos editores, Mais notícias, Críticas Ípsilon). Nas colunas temáticas o título vem de
  `h1.column__title` e vai para `site_meta.column`. Os blocos sem título chamam-se `marcas` (`block--brands`) e
  `categorias` (`block--categories-cta`, as colunas por secção).
- **zone/rank**: zona e posição da **1.ª aparição** na ordem do HTML. `zones` lista todas as zonas onde a peça
  aparece. `site_meta.level` (2 = manchete … 5 = lista) é o sinal de destaque mais forte.
- **Campos por card**: título (`.article__title a`), lead (`.article__lead`, só nos cards maiores), autores
  (`.article__byline address`), `byline_raw` (texto das `address`), `agencies` (ex.: "Lusa e PÚBLICO" → `["Lusa"]`),
  secção, data e tipo (estes três vêm do URL).
- **Parênteses no byline**: se forem uma função (texto, fotografia, vídeo, ilustração, edição de som…) vão para
  `Author.role`; se não, vão para `Author.affiliation` (ex. "Nome (TSF)"). Assinaturas colectivas ("Lusa",
  "PÚBLICO") ficam como `Author`.
- **Exclusões auditáveis**: `parse_homepage(html, include_excluded=True)` devolve também os 27 itens fora de âmbito,
  com `excluded_reason` (`zona:podcasts`, `tom:tone--paid`, `secção:edicoes-publico`, `card:VIDEO`,
  `byline:áudio (podcast)`…). Vídeos e interactivos sem ID de artigo saem com `site_article_id=None` e
  `site_meta.card_id`.
- **Data**: só a do URL → `published_at="AAAA-MM-DD"`, `published_at_precision="date"`. Não se converte para UTC,
  porque meia-noite de Lisboa em UTC daria o dia anterior.
- **Links `/n<ID>`**: se o artigo correspondente estiver na página, o link vai para os `aliases` dele. Caso contrário
  fica como item próprio, sem secção, data nem tipo, com uma nota em `extraction_debug.note`. O rótulo "Opinião" →
  `piece_type="opiniao"`.
- `access` fica None: a homepage estática não tem marca de exclusivo.
- Widgets por JS, vazios no HTML: "Últimas notícias" (`widget--latest`), "Opinião" (`widget--opinion`) e sliders.
- Amostra 2026-10-13: 137 cards → **92 artigos** (83 com URL completo + 9 só `/n<ID>`; 2 links curtos fundidos em `aliases`). Revisto à mão: as 22
  exclusões face a "todos os links de artigo" têm todas um motivo de âmbito.

## Artigo (`parse_article`) — fonte de cada campo
| Campo | Fonte (por ordem) |
|---|---|
| `canonical_url` | `link[rel=canonical]` → JSON-LD `url` → `og:url` |
| `site_article_id` | `article#story[data-article-id]` → `publicoConfig.pageArticleId` → URL |
| `title` | JSON-LD `headline` → `og:title` → `h1` (o `meta name="name"` vem truncado) |
| `lead` | `.story__blurb` → JSON-LD `description` → `og:description` |
| `body` | JSON-LD `articleBody` se existir (não existe nos artigos abertos) → `#story-body`: blocos `p/h2/h3/li/quote` folha, com `links` inline. Remove `.pw-container` (bloqueio do Piano), `aside.story__callout` ("leia também" em iframe), `figure`, `iframe`, `.ad-slot`, `ad-placement` e newsletters |
| `authors` | nomes do JSON-LD `author[]` + `role`/`url` do `.byline address` (+ quem só esteja no byline, ex. fotógrafos) → `publicoConfig.pageAuthors` → `meta author` |
| `agencies` | autores, afiliações e `byline_raw` = Lusa/Reuters/AFP/EFE/AP/Bloomberg ("Agências" → `AGENCY_GENERIC`) |
| `byline_raw` | texto das `.byline address` |
| `images` | ver "Fotografia" |
| `published_at_precision` | `datetime` (JSON-LD tem data e hora) |
| `out_of_scope` | URL fora de âmbito → `publicoConfig.pageSponsored` → byline de áudio (podcast) → `pageType` podcast/vídeo/live |
| `published_at` / `updated_at` | JSON-LD `datePublished` / `dateModified` (RFC 1123, UTC) via `to_utc_iso` → `time.dateline[datetime]` |
| `section` | JSON-LD `articleSection` → `publicoConfig.pageSection.name`. `subsection` = None (o Público não tem) |
| `tags` | `publicoConfig.pageTags` → `meta keywords` → `.story__tags a.button--tag`; sem duplicados (comparação sem maiúsculas nem acentos; o `pageTags` repete a secção, ex. "Política") |
| `piece_type(_raw)` | `<tipo>` do URL; `body.tone--opinion` força `opiniao` |
| `access` | JSON-LD `isAccessibleForFree`; `publicoConfig.isExclusivo/isPremium/lockItem=true` → `premium` |
| `body_complete` | `True` se `free` e sem `.is-paywalled/.paywall-block`, ou se veio de `articleBody`; `False` se houver marca de truncagem; `None` se for premium sem `articleBody` (por validar) |
| `word_count` | palavras dos blocos extraídos |
| `site_meta` | `kicker` (tag principal, `.story__labels .kicker`), `page_type`, `sponsored`, `is_exclusivo`, `is_premium`, `lock_item`, `paywall_size`, `is_azul`, `tag_ids`, `author_slugs`, `section_slug`, `image` |

Notas:
- `publicoConfig.pageDate` traz a hora local marcada como GMT (+1h errada), por isso não é usado.
- No JSON-LD, `mainEntityOfPage.url` tem uma gralha no domínio (`publioco.pt`) e também não é usado.

## Ligações e embeds do corpo (v2.2)

- **`Block.links`**: `a[href]` dentro dos blocos do `#story-body` (p, h2–h4, li, blockquote), com URL absoluto. Ficam de fora:
  as caixas "leia também" (`aside.story__callout--link`, que trazem um `iframe.interactive` com `data-src=…/embed?FromApp=1`
  para outra notícia do Público), as newsletters, o paywall, os `mailto:`/`tel:`/`#` e os links para lojas de apps
  (`BODY_LINK_NOISE_HOSTS`). Um parágrafo cujos links são todos de lojas de apps é descartado (promoção da app).
  O corpo das amostras reais só tem links inline em `p` e `li`: 33 links em 9 páginas, quase todos para o próprio Público
  (notícias e páginas de tema como `/siresp`, `/conclave`) e alguns externos (vaticannews.va, people.com, thoracic.org).
- **`Article.embeds`**: o parser reconhece a marcação padrão das redes (`EMBED_BLOCK_SELECTORS`: `blockquote.instagram-media`,
  `blockquote.twitter-tweet`, `blockquote.tiktok-embed`, `div.fb-post`, …) e os iframes de plataformas conhecidas
  (`EMBED_HOST_PLATFORMS`: YouTube, Vimeo, Facebook, Instagram, X, TikTok, Spotify, Flourish, Datawrapper…, com `src` ou `data-src`).
  O URL do player é convertido no URL original (ex.: `youtube.com/embed/ID` → `watch?v=ID`) e perde a query de tracking.
  `text` é a legenda (`figcaption`), o `title` do iframe ou o texto do blockquote. `block_index` é o índice do bloco seguinte.
- **Ainda sem embed social real**: nenhuma das amostras tem embeds de redes. A captação está testada só na fixture
  sintética `backend/tests/fixtures/publico_article_2191175_embeds_sintetico.html` (HTML real com embeds injectados).
- **Lojas de apps**: o pipeline viu `play.google.com`/`apps.apple.com` em corpos do Público, mas nenhuma amostra os tem.
  Ficou o filtro defensivo; falta o ID do artigo onde apareceram para confirmar o contexto.
- Se o corpo vier do JSON-LD `articleBody` (nunca visto no Público), não há links e os embeds ficam com `block_index=None`.

## Fotografia
- **O crédito existe no HTML**: `figcaption.caption > span.credit`, em maiúsculas por CSS, com o formato
  `FOTÓGRAFO/AGÊNCIA` (ex.: `JOSé COELHO/LUSA`). A legenda é o resto do `figcaption`.
- **Não existe no JSON-LD**: `image` só tem `url`, `width` e `height`. `og:image` também não tem crédito.
- **Imagem principal**: `#story-header figure.story__media img`, `is_main=True`. O URL vem de `data-media-viewer`
  (tamanho original), ou de `data-src` sem os parâmetros `w`/`act` do lazy-load.
- **Imagens do corpo**: `#story-body figure` com `img`, extraídas antes de limpar o corpo. Não há nenhuma na amostra;
  testado com uma figura sintética (`REUTERS/Yves Herman` → `['Yves Herman']`, `Reuters`).
- **Arquivo**: um crédito com a parte `Arquivo` dá `is_archive=True`. Ex.: `Rui Gaudêncio/Arquivo` (2191168) →
  `photographers=["Rui Gaudêncio"]`, `agency=None`.
- **Parse do crédito** (`_parse_credit`): separa por `/`. As partes que são agência (Lusa, EPA, Reuters, AFP, AP,
  Getty, Global Imagens, PÚBLICO…) vão para `agency` (`LUSA/EPA` → `Lusa/EPA`); o resto vai para `photographers`, com
  maiúsculas normalizadas (`JOSé COELHO` → `José Coelho`) e separado por "e" ou vírgula. `DR` e `Arquivo` ficam só em
  `credit_raw`.
- **Byline**: fotógrafos e videógrafos listados como co-autores ("Daniel Rocha (fotografia)") ficam também em
  `authors` com `role="fotografia"`/`"video"`.
- **Cobertura na amostra**: imagem principal 1/1 com crédito (José Coelho, Lusa); imagens do corpo 0.
  **Homepage: sem crédito** (`<img alt>` = título, sem `figcaption`). Só os cards com byline "(fotografia)" dão o
  fotógrafo, como `Author`.
- Sem crédito na página → `extraction_debug.images_credit = "FALHA: imagem sem crédito na página"`.
- Por validar: galerias, comparadores (`.media--juxtapose .credit`) e imagens embebidas em iframes.

## Paywall
- **Artigo** (validado com o crawl real do 2190775, exclusivo):
  - `access="premium"` vem de JSON-LD `isAccessibleForFree=false`, de `publicoConfig.isExclusivo/isPremium/lockItem=true`
    ou das marcas HTML `#paywall-disclaimer` e `.kicker--exclusive`. As marcas HTML só aparecem nos exclusivos.
  - O servidor **corta o corpo**: só vem o 1.º parágrafo seguido do gate Piano (`.pw-container`), e não há
    `articleBody` no JSON-LD. Por isso o artigo fica com `out_of_scope="premium_sem_texto_integral"`,
    `body_complete=False` e `body=[]`, e o tamanho do corpo parcial fica em `extraction_debug.body_complete`.
  - `.pw-container` / `#piano--content-gate` aparecem **também nos artigos abertos**, por isso não servem de sinal.
  - O `publicoConfig` não mudou de estrutura. No `site_meta` as chaves estão em snake_case: `is_exclusivo`,
    `is_premium`, `lock_item`, `paywall_size`.
- **Homepage: o premium NÃO se detecta.** Na homepage real de 2026-10-13T12:03Z, nenhum dos 139 cards tem marca: nem
  classe, nem badge, nem atributo, nem JS que a acrescente. O 2190775, que é exclusivo, aparece como um card normal
  (`tone--feature`). `HomepageItem.access` fica None, por isso o crawler tem de ir buscar o artigo para saber.
  Alternativa: a página `/exclusivos` (está no menu) pode servir de lista de IDs premium. Falta amostra.

## Descoberta: sitemaps e RSS
**robots.txt** (lido a 2026-10-13, único pedido feito ao site; daí em diante, nenhum pedido — as amostras, se
necessárias, são fornecidas pelo utilizador em `sites/`):
- `User-Agent: *`: `Disallow: /pesquisa?*`, `/assinaturas?decider_*`, `/utilizador/*`.
- Declara `Sitemap: https://www.publico.pt/sitemaps/news.xml` (Google News) e
  `https://www.publico.pt/sitemaps/sitemapindex.xml` (índice).
- ⚠️ Há um grupo com cerca de 150 user-agents de IA e scraping (`ClaudeBot`, `Claude-Code`, `Claude-User`, `anthropic-ai`,
  `GPTBot`, `CCBot`, `Google-Extended`, `PerplexityBot`, `Bytespider`, `Diffbot`, `FirecrawlAgent`, `Crawl4AI`…) com
  `Disallow: /`, excepto `/assinaturas`, `/nos/` e `/site/`. O `AhrefsBot` tem `Crawl-delay: 10` e `Disallow: /n1`, `/n2`.
- Por isso **não foram descarregados** sitemaps nem feeds: este agente corre como Claude Code, que está explicitamente
  bloqueado. Sem amostras `sites/publico_sitemap*.xml` nem `sites/publico_feed*.xml`.
- **RSS** conhecido: `http://feeds.feedburner.com/PublicoRSS` ("Últimas notícias", declarado no `<head>` do artigo e no
  rodapé). Não se verificou se ainda está activo, nem se há feeds por secção.

**Implementado sem amostra real** (formatos standard; testado só com XML sintético):
- `parse_sitemap_index(xml) -> list[str]`.
- `parse_sitemap(xml) -> list[HomepageItem]`: `loc`, `lastmod` (→ `site_meta`), `news:publication_date`
  (→ `published_at`, precisão `datetime`), `news:title` e `news:keywords`.
- `parse_feed(xml) -> list[HomepageItem]`: RSS 2.0 ou Atom. Usa `feedburner:origLink` → `link` → `guid`; `pubDate`;
  `description`; `dc:creator`; `category`.
- As regras de âmbito por URL são as da homepage. As regras por zona e byline não se aplicam (não há essa informação).
  Episódios de podcast com URL `/noticia/` **passam** num sitemap ou feed: só o artigo os denuncia (byline de áudio).

**Por fazer quando o utilizador fornecer amostras** em `sites/` (ver Limitações): analisar `news.xml`, o índice e o feedburner, e medir a
janela temporal, o nº de entradas, a frequência e a cobertura face à homepage.

**Estratégia recomendada (provisória)**:
1. **News sitemap** como fonte principal de descoberta: tem ID no URL, data com hora e título, e apanha as "Últimas"
   que a homepage só mostra por JS. Cadência inicial de 5–10 min (configurável).
2. **Homepage** a 15–30 min como sinal editorial (`zone`, `rank`, `site_meta.level`, `zones`) e para os links `/n<ID>`.
3. **RSS feedburner**: redundância, se estiver vivo.
4. Índice de sitemaps: só para revisitas tardias e para confirmar apagamentos.

## Decisões pendentes (utilizador)
- Marcas P3, Fugas, Ípsilon, Ímpar, Azul e Público Brasil: hoje **entram** (`EXCLUDE_GROUP_BRANDS = False`).
- "Especial Executivos": hoje entra. Confirmar se é conteúdo patrocinado.
- Acesso ao site: o robots.txt bloqueia bots de IA (ver [fontes](../features/fontes.md#robotstxt-e-acesso)).

## Limitações e casos por validar
- **Bloqueio por robots.txt**: o Público recusa bots de IA. Decidir (fase legal) se o crawler do Factos, que analisa
  com LLM, se identifica num user-agent que caia nesse grupo. Isto afecta o site inteiro, não só os sitemaps.
- Validado com 1 notícia de exemplo e 2 artigos do crawl real (2191168, aberto, Lusa/PÚBLICO; 2190775, exclusivo),
  mais a homepage real (90 artigos, 27 excluídos). Falta testar: **opinião** em `/opiniao/…`, artigo
  **actualizado**, entrevista P&R, imagens no corpo, e um exclusivo que traga `articleBody`.
- Links `/n<ID>` sem correspondente na página podem ser podcast ou vídeo sem rótulo; só se sabe ao seguir o redirect
  ou ao fazer o parse do artigo.
- "Especial Executivos" entra (redacção, com bylines de jornalistas), mas é um especial temático com interactivo
  comercial ao lado. Confirmar se é patrocinado.
- Subtítulos (`h2/h3`) entram no `body` como blocos próprios.
