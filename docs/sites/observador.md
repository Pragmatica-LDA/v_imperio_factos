# Observador — Parser

> Estado: ⚠️ parcial (PoC), contrato v2.2 (validado com 2 homepages, 3 artigos — longform premium, notícia Lusa, opinião premium —, 8 artigos com embeds, 4 sitemaps e o RSS)  ·  Última actualização: 2026-10-13

Parser: [`backend/parsers/observador.py`](../../backend/parsers/observador.py) · Contrato: [`backend/parsers/base.py`](../../backend/parsers/base.py)

```
cd backend && python3 -m parsers.observador ../sites/observador_homepage.html ../sites/observador_noticia.html \
  --sitemap ../sites/observador_sitemap_post-243.xml --sitemap ../sites/observador_sitemap_obs_longform-12.xml \
  --sitemap ../sites/observador_sitemap_obs_opinion-21.xml --sitemap ../sites/observador_sitemap_obs_factcheck-3.xml \
  --feed ../sites/observador_feed.xml
```
Saídas em `sites/out/` (na raiz, seja qual for o cwd): `observador_homepage.json`, `observador_homepage_excluded.json` (auditoria),
`observador_article.json`, `observador_sitemap.json`, `observador_feed.json`.

Funções: `parse_homepage(html, include_excluded=False)`, `parse_article`, `parse_sitemap_index`,
`parse_sitemap`, `parse_feed`, `parse_credit` (créditos fotográficos).

Site em WordPress (temas `observador` / `observador-child`), com tipos de post próprios.

## Padrões de URL e âmbito

| Tipo WP (`piece_type_raw`) | Padrão | `piece_type` | Entra? |
|---|---|---|---|
| `post` | `/AAAA/MM/DD/<slug>/` | `noticia` (`critica` se tiver estrelas) | ✅ |
| `obs_longform` (Especiais) | `/especiais/<slug>/` | `reportagem` / `analise` / `entrevista` (heurística no artigo; None na homepage) | ✅ |
| `obs_opinion` | `/opiniao/<slug>/` | `opiniao` | ✅ |
| `obs_factcheck` | `/factchecks/<slug>/` | `factcheck` | ✅ |
| `obs_liveblog` | `/liveblogs/<slug>/` | — | ❌ live blog |
| `obs_episode` | `/programas/<programa>/<slug>/` | — | ❌ podcast/rádio |
| outros | `/seccao/…`, `/opiniao/autor/…`, `/jogos/`, `/newsletters/`, `/radio/` | — | ❌ |

Fora de âmbito também (regra "promoções institucionais"): itens da homepage cujo `a.topic` aponta para
`/seccao/podcasts/…` (páginas "ouça aqui todos os episódios" e peças que promovem o Podcast Plus) e o post do
dark mode. No artigo: `contextualData.pageTargeting.sponsored` ou `post.isAnInitiative` → `out_of_scope`.

Normalização: `https://observador.pt` + path com barra final, sem query nem fragmento. Sem aliases no HTML
(sem AMP nem shortlink).

**ID interno** = ID do post WordPress (o URL não o contém; o slug muda com o título).
- Homepage: classe do bloco `post-<ID>` / `obs_<tipo>-<ID>`; alternativa `span[data-link][data-id]`.
- Artigo: `body.postid-<ID>`; alternativa `article#article-<tipo>-<ID>`; também `contextualData.post.id`.

## Homepage (v2)

Grelha `main .editorial-grid .fbg-row`; cada peça é `div.mod.mod-posttype-<tipo>`.

| Campo | Fonte |
|---|---|
| `title` | `h1.title a` (título curto) / `a .title` / `a[aria-label]` |
| `lead` | `.lead`, `.widgettype-tres-artigos-article > p` |
| `authors`, `byline_raw` | `.columnist-name a` (só opinião), com URL `/opiniao/autor/<user>` |
| `section` / `subsection` | `a.topic[href]` = `/seccao/<topo>/<sub>/`: topo → nome do menu se existir no HTML, senão **slug** (`site_meta.section_slug` sempre); `subsection` = texto do `a.topic` |
| `published_at` | `time.timeago[datetime]` (tem um `}` perdido); "Últimas": data do URL + `HH:MM` (Lisboa) → UTC |
| `piece_type(_raw)` | `mod-posttype-*` ou permalink; `.rating.stars-N` → `critica` |
| `zone` / `zones` / `rank` | 1.ª linha = `destaque`; widgets `ultimas`, `mais-populares`, `opiniao`; restantes = slug do título da linha (`.generic-title`) ou `grelha`; `rank` = ordem da 1.ª ocorrência |
| `site_meta` | `section_slug`, `rating`, `photogallery`, `flag` ("Em atualização" — útil para revisitas), `image` {url, credit_raw, photographers, agency} |
| `access` | ❌ sem marca por item na homepage |
| `agencies` | ❌ a homepage não mostra assinatura de agência |

Resultado: **169 peças no âmbito** (93 notícias, 4 críticas, 41 especiais, 22 opinião, 9 fact checks); 151 com
ID, 150 com data, 157 com secção. **72 excluídas** (51 episódios, 18 promo de podcasts, 2 live blogs, 1 dark
mode). Sem ID/data: widgets "três artigos", "Últimas" (sem ID) e lista de opinião — o HTML não os tem.

## Artigo (v2)

| Campo | Fonte primária | Alternativa / nota |
|---|---|---|
| `canonical_url` | `link[rel=canonical]` | `og:url` |
| `site_article_id` | `body.postid-<ID>` | `article[id]` |
| `title` | JSON-LD `headline` | `og:title`, `h1` |
| `lead` | `p.article-head-main-info-lead`; opinião: `p.article-head-content-headline-lead` | JSON-LD `description` |
| `authors` | JSON-LD `author[].name` + HTML `li.author` (`.author-credit` → `role`, `a[href=/perfil/<user>/]` → `url`); opinião: `.article-head-columnnists .columnist-info-name` (`url` = `/opiniao/autor/<user>/`, descrição em `site_meta.columnist_description`) | `meta[name=author]`; "Nome (X)" → `affiliation`. "Agência Lusa" fica como Author (`/perfil/lusa/`) e em `agencies` |
| `byline_raw` | nomes em `.article-head-authors .author-name` | `meta[name=author]` |
| `agencies` | autor "Agência Lusa"/AFP/Reuters…, ou "(Lusa)" no fim do último parágrafo | assinatura colectiva fica também em `authors` |
| `published_at` / `updated_at` | JSON-LD `datePublished` / `dateModified` → UTC | `article:*_time`, `meta[name=pub_date]`. Se `dateModified` < `datePublished` (peça **agendada**: última edição antes de sair; JSON-LD, `meta` e `contextualData.createdAt/updatedAt` concordam) → `updated_at=None`, valor em `site_meta.modified_before_publish` e nota no debug |
| `section` / `subsection` | JSON-LD `articleSection` / `contextualData.post.mainCategory` (nome via link `/seccao/…`) | — |
| `tags` | JSON-LD `keywords` (string com vírgulas), sem duplicados (sem maiúsculas/acentos) | links `/seccao/` no artigo |
| `piece_type_raw` | classe do `<body>` (`obs_longform`…) | `contextualData.postType`, URL |
| `piece_type` | tipo de post; longform: "entrevista" no título/lead/tags → `entrevista`; ≥2 marcas de reportagem (1.ª pessoa no terreno) → `reportagem`; senão `analise` | heurística, nota em `extraction_debug` |
| `access` | `premium` se JSON-LD `isAccessibleForFree=false` / `body.premium-article` / `contextualData.articleIsPremium` | |
| `body`, `body_source` | **HTML**: todos os `.article-body-content` (p, `h1.tinymceh1`→h2, h2–h4, blockquote, li) com links inline | JSON-LD `articleBody` se o HTML vier truncado (>10% menos texto) |
| `body_complete` | cobertura do HTML vs `articleBody` ≥ 90% (o texto dos embeds conta, porque o `articleBody` o inclui) | |
| `body[].links` | `a[href]` dos blocos editoriais; sem tracking (`utm_*`, `fbclid`, `ref_src`…); t.co e outros redirects ficam como estão | — |
| `embeds` | `.article-body-wrapper` antes de `#article-end-marker` (inclui os `.article-block.block-html` entre contentores): `blockquote.twitter-tweet` (permalink `/status/`, texto do tweet), `blockquote.instagram-media` (`data-instgrm-permalink`), `blockquote.tiktok-embed`, `div.fb-post`, `iframe` (YouTube→`watch?v=`, Vimeo, Facebook `plugins/*?href=`, Spotify; `title` como texto). `wp-embedded-content` continua a ser "leia também" (ruído) | — |
| `images` | `figure.article-head-image`: `img` (URL original S3 extraído do `bordalo …/plain/<url>`), `.legenda`, `.creditos` | fim do `alt` (legenda Lusa) |
| `out_of_scope` | `pageTargeting.sponsored`, `isAnInitiative`, tipo episode/liveblog | |
| `site_meta` | `contextualData`: `small_title`, `main/top_category`, `exclusive`, `sponsored`, `is_initiative`, `sensitive`, `content_length`; JSON-LD `wordCount` | |

**Payload embebido** `var contextualData = {…}` (JS, não JSON): `pageTargeting` é JSON válido
(`postType`, `category`, `topCategory`, `exclusive`, `sponsored`); o resto lê-se por regex.

**Limpeza do corpo**: só o que está antes de `#article-end-marker` (depois vêm os rodapés da opinião:
`p.follow-columnist` "Siga-me no Facebook…", `aside.follow-columnist-now` "Receba um alerta…");
`blockquote.wp-embedded-content` (embed WordPress = "leia também"); parágrafos promocionais curtos com link
(`PROMO_PARA_RE`: "Acompanhe o nosso liveblog…", "Leia também", "Siga", "Receba"…; `PROMO_PARA_MAX_LEN`); `aside`;
anúncios (`.obs-ad-*`, `obs_ads.queue_slot`), widgets, "As mais lidas", promoções entre
`[...]` (Podcast Plus, newsletters, assinaturas) e **destaques** (pull quotes repetidos, às vezes editados —
difflib, `PULL_QUOTE_MIN_LEN`/`PULL_QUOTE_MIN_RATIO`). Limiar de truncagem e de completude:
`BODY_TRUNCATED_RATIO`, `BODY_COMPLETE_MIN_COVER`. Imagens soltas no corpo sem `figure` (promo do podcast) são
ignoradas.

## Paywall

- Marcas: `body.premium-article`, JSON-LD `isAccessibleForFree:false` + `hasPart` (`.paywall-marker`,
  `.piano-toaster`, `.piano-container`), `contextualData.articleIsPremium`, `pageTargeting.exclusive`.
- **O texto integral está no HTML**: o artigo vem partido em **dois** `.article-body-content` (parte visível e
  parte "paga", que o Piano esconde no browser). O JSON-LD `articleBody` também é integral (parágrafos colados,
  com scripts de anúncios e o destaque).
- Na amostra: corpo HTML = 17 blocos (16 p + 1 h2), 1314 palavras, 1 link inline; cobre 93% do `articleBody` —
  a diferença é só o destaque. `access="premium"`, `body_complete=True`, `body_source="html"`.
- Premium detecta-se sempre no artigo (longform e opinião: `body.premium-article` + JSON-LD + `contextualData`).
  Na homepage/sitemap/RSS **não há marca de premium** → para o Observador o crawler vai sempre buscar (excepção
  prevista no contrato).
- **Se um dia vier truncado** (HTML sem a parte paga e sem `articleBody` integral): `out_of_scope=
  "premium_sem_texto_integral"`, `body=[]`, `body_complete=False` (testado simulando a truncagem nos 2 premium).
- Fallback `jsonld` (se o HTML deixar de trazer o texto; atenção que o `articleBody` também contém as promos
  e os embeds "leia também", colados sem separador): split dos parágrafos colados por regex
  (`"sentado.“Por"`, `"PSD.Ao"`), intertítulos h2 por heurística (curto, sem pontuação final) e só os blocos do
  prefixo visível ficam com links inline — fica registado em `extraction_debug.body`.

## Fotografia

- **O crédito existe.** Imagem principal: `figure.article-head-image figcaption .creditos`
  (ex.: `ESTELA SILVA/LUSA`) e `.legenda`; o `alt` repete a legenda Lusa terminando no crédito.
- JSON-LD `image` (3 recortes) **não tem crédito**; o parser usa o HTML.
- `parse_credit`: formatos `NOME/AGÊNCIA`, `AGÊNCIA/NOME[/POOL]`, `GettyImages-<n>`. Agências: Lusa, EPA, AFP,
  Reuters, AP, Getty Images, Observador, Sputnik, EFE, Global Imagens, Anadolu. Sem agência conhecida
  (ex.: `INE/Pordata`) não se separa fotógrafo: só `credit_raw`. Nomes em maiúsculas → "Estela Silva".
- `is_archive=True` quando o crédito diz "Arquivo"/"Archive"/"File photo" (não visto ainda nas amostras).
- Opinião: **sem imagem editorial** — a única imagem é a foto do colunista (também é o `jsonld:image`/`og:image`);
  `images=[]` com nota no debug.
- Imagens do corpo: nas 3 amostras não há `figure` no corpo (só uma imagem promocional solta, ignorada) — formato
  das imagens de corpo **por validar**.
- Homepage: crédito no fim do `alt` em 47/161 imagens (Lusa 20, EPA 13, Getty 12, Observador 1), em
  `site_meta.image`. RSS: `media:credit` em 29/35 itens.

## Descoberta: sitemaps e RSS

**robots.txt** (pedido em 2026-10-13): `User-agent: *` → `Disallow: /wp-admin/`, `Disallow: */embed/`;
`Sitemap: https://observador.pt/wp-sitemap.xml`. `ClaudeBot`, `anthropic-ai`, `Claude-Web`, `GPTBot`, etc.
estão num grupo com `Allow: /` (sem bloqueio). `Scrapy`, `Bytespider`, `SemrushBot`, `PetalBot`… →
`Disallow: /`. **Sem crawl-delay.** Pedidos feitos: 9, com User-Agent próprio e 1 s de intervalo.

| Fonte | URL | Formato / campos | Janela | Entradas | ID? |
|---|---|---|---|---|---|
| Índice | `/wp-sitemap.xml` | sitemapindex WP core, 370 filhos | — | — | — |
| Notícias | `/wp-sitemap-posts-post-N.xml` (N=1…243) | `loc` + `lastmod` (= modificação) | página 243: 28/09 → 13/10 | 2000/página (a 243 tinha 1653) | ❌ |
| Especiais | `…-obs_longform-N.xml` (1…12) | idem | pág. 12: jun → out | 801 | ❌ |
| Opinião | `…-obs_opinion-N.xml` (1…21) | idem | pág. 21: ago → out | 836 | ❌ |
| Fact checks | `…-obs_factcheck-N.xml` (1…3) | idem | pág. 3: out/2025 → out/2026 | 512 | ❌ |
| RSS "Últimas" | `/feed/` (self: `/rss/ultimas/`) | RSS 2.0: `title`, `description` (lead), `dc:creator`, `category` (sem hierarquia), `pubDate`, `media:content` + `media:credit` | ~4,5 h | 51 (35 artigos; 15 episódios, 1 newsletter) | ❌ |

- Sem **news sitemap** (`/news-sitemap.xml` e `/sitemap-news.xml` → 404). Sem sitemaps por data/secção.
- Feeds de secção (`/seccao/politica/feed/`) devolvem o **mesmo** feed "Últimas". REST `/wp-json/wp/v2/posts` →
  404 (desligada).
- Ordem nos sitemaps: ID crescente (= publicação); a **última página** de cada tipo tem os mais recentes; quando
  chega a 2000 aparece a página N+1 no índice. `lastmod` muda a cada edição (sinal barato de nova versão).
- O RSS **só tem `post`** (nem opinião, nem especiais, nem fact checks) e mistura episódios de rádio.
- `dc:creator` no RSS revela a assinatura "Agência Lusa" (27/35 itens) — dado que a homepage não mostra.

**Cobertura** (homepage capturada ~11:30 UTC, sitemaps/RSS ~11:50 UTC):
- Homepage ⊂ sitemaps: **169/169 (100%)**. RSS ⊂ sitemaps: 35/35.
- Sitemaps → homepage: notícias publicadas a 13/10: 51 no sitemap, 23 na homepage (45%); a 12/10: 135 vs 45
  (33%). Das 195 peças modificadas nas 24 h anteriores, 92 estavam na homepage.
- Homepage ∩ RSS: 17 (o RSS só cobre ~4,5 h e só notícias).

**Estratégia recomendada**
1. **Sitemaps como fonte principal**: a cada 10–15 min, pedir a última página dos 4 tipos editoriais (≈300 KB
   a de notícias; os outros 3 podem ir a 30–60 min). Novos URLs → fila de crawl; `lastmod` alterado → revisita
   (versão nova). Reler o índice 1×/hora para detectar a página N+1.
2. **Homepage a cada 15–30 min** só como sinal editorial (`zone`, `rank`, `zones`, flag "Em atualização"),
   não para descoberta.
3. **RSS opcional** (a cada 30–60 min): não descobre nada que o sitemap não tenha, mas dá `byline` Lusa,
   `lead` e crédito da foto sem abrir o artigo.

## Limitações e casos por validar

- Amostras: longform premium, notícia Lusa aberta (8365764), opinião premium agendada (8364379). Por validar:
  fact check, crítica, imagens no corpo, galeria, embeds de redes sociais/vídeo, "atualizado às" visível no HTML.
- Sitemaps: numa peça agendada o `lastmod` pode ser anterior à publicação — não usar `lastmod` como data de
  publicação.
- Secção na homepage: o menu de secções não vem no HTML → `sociedade`, `saude`, `observador` ficam em slug
  (o artigo usa o nome do JSON-LD). Normalizar por `site_meta.section_slug` / `top_category`.
- `piece_type` de longform é heurístico (ex.: "estivemos" dentro de uma citação conta como marca de reportagem;
  daí o limiar 2).
- Sitemaps sem data de publicação: só `lastmod`; notícias têm a data local no URL (`precision="date"`).
- Lista "Últimas": hora sem data → data do URL + hora (heurística registada em `extraction_debug`).
- Itens da linha "Podcast Plus para assinantes" sem `a.topic` de podcast (ex.: longform sobre Silva Pais)
  ficam no âmbito — fronteira com "promoção institucional" por decidir.

## Por fazer
- Amostras de fact check, crítica, fotogaleria, artigo com imagens/embeds no corpo e notícia actualizada
  depois de publicada.
- Confirmar `lastmod` dos sitemaps como sinal de nova versão (e o caso das peças agendadas).
- Decidir a fronteira das peças da linha "Podcast Plus" sem `a.topic` de podcast.
- Afinar a heurística `reportagem`/`analise` dos especiais com mais amostras.
- Propostas ao contrato (pendentes): `HomepageItem.images`, secção como slug + nome, flag "Em atualização",
  tipo de media na homepage.

## Histórico
- 2026-10-13 — Ronda 1: parser v1 (homepage + artigo), análise da homepage.
- 2026-10-13 — Ronda 2: contrato v2/v2.1; texto premium integral no HTML (2 contentores); sitemaps e RSS;
  créditos fotográficos; `contextualData`.
- 2026-10-13 — Ronda 3 (crawl real de 8365764 e 8364379): fim do texto em `#article-end-marker`, embeds
  "leia também" e promos fora do corpo, cabeça da opinião, datas de peças agendadas, regra
  `premium_sem_texto_integral` testada, tags sem duplicados, `is_archive`.
- 2026-10-13 — Ronda 4 (contrato v2.2, 8 amostras em `sites/raw/links/`): os tweets entravam no corpo como
  blocos `quote`, com t.co, hashtags, menções e data como links (15 links de ruído em 8 páginas); os iframes
  YouTube/Facebook e o Instagram (`.block-html` entre contentores) não eram captados. Agora saem para
  `Article.embeds` (16 nas amostras). Fixtures: `backend/tests/fixtures/observador_article_{8365605,8366176}_embeds.html`.
