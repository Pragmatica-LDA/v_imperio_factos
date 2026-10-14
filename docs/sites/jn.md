# Jornal de Notícias (JN) — parser

> Parser: `backend/parsers/jn.py` (contrato v2.2) · Última actualização: 2026-10-13
> Runner: `cd backend && python3 -m parsers.jn ../sites/jn_homrpage.html ../sites/jn_noticias.html [../sites/jn_sitemap_*.xml …] [--out dir]`
> Saída: `sites/out/jn_homepage.json`, `jn_article.json`, `jn_sitemap_<nome>.json`

## Estado
⚠️ PoC funcional (2026-10-13).
- Feito:
  - homepage, artigo, índice de sitemaps, news sitemap e sitemaps diários;
  - regras de âmbito e premium;
  - autores colectivos e afiliações;
  - imagens com crédito;
  - `extraction_debug` em todos os campos.
- Validado com 2 homepages e 3 artigos reais (1 premium).
- Falta: amostras de live blog, podcast, opinião, artigo actualizado e imagens no corpo; confirmar "Ciência na
  Europa"; decisão legal para produção.

## Amostras e outputs
| Ficheiro | O quê |
|---|---|
| `sites/jn_homrpage.html`, `sites/jn_noticias.html` | Amostras iniciais (homepage + artigo 18136577, free, "JN/Agências") |
| `sites/raw/jn_homepage_20261013T120327Z.html` | Homepage do crawl real |
| `sites/raw/jn_article_18136568_*.html` | Artigo free (take Lusa assinado "JN/Agências"), 442 palavras |
| `sites/raw/jn_article_18135966_*.html` | Artigo premium "Exclusivo" cortado (72/873 palavras) → fora de âmbito |
| `sites/jn_sitemap_news.xml`, `sites/jn_sitemap_index.xml`, `sites/jn_sitemap_day_2026-10-1{2,3}.xml` | Sitemaps (13/10, ~12:00 UTC) |
| `sites/out/jn_*.json` | Saídas do parser (homepage com excluídos, artigos, sitemaps) |

Regenerar os outputs: `cd backend && python3 -m parsers.jn ../sites/jn_homrpage.html ../sites/jn_noticias.html ../sites/jn_sitemap_news.xml ../sites/jn_sitemap_day_2026-10-13.xml ../sites/jn_sitemap_day_2026-10-12.xml`.
Os ficheiros de `sites/raw/` são processados pelos scripts de crawl (ver [parsers](../features/parsers.md)).

## Plataforma
Next.js (App Router), grupo Notícias Ilimitadas (imagens em `staticx.noticiasilimitadas.pt`). Além do HTML,
cada página traz o **RSC payload** (`<script>self.__next_f.push([1, "..."])</script>`): uma string JSON que,
depois de descodificada, contém os objectos de conteúdo. É a fonte mais rica. As classes CSS são CSS modules
com hash; os selectores usam só o sufixo (`[class*="__AGBody"]`). Os sitemaps são servidos pela "ngx-api"
(`ngx-api-version: 3.3.18.0`).

## URLs e ID
- Artigo: `https://www.jn.pt/<secção>/artigo/<slug>/<id>`. O **ID interno** é o último segmento (8 dígitos,
  crescente). O slug muda com o título; o ID não.
- Aliases: AMP `https://www.jn.pt/amp/<id>/<slug>` (`<link rel="amphtml">`), RSC `UrlApp`/`UrlAppfb`.
- Normalização: host `www.jn.pt`, sem query/fragmento, barras duplicadas colapsadas.

## Âmbito
Os itens fora de âmbito ficam com o motivo em `excluded_reason` (homepage/sitemap com `include_excluded=True`)
ou em `Article.out_of_scope`. Regras por ordem (a mais específica primeiro):

| Regra | Valores | Motivo |
|---|---|---|
| `Layout.Code` | `NG:BrandsLife` | patrocinado |
| `SectionSlug` (RSC) ou secção do URL | `brands-life` | patrocinado |
| | `iniciativas`, `apostas`, `casino` | promocional |
| | `jn-direto` | video |
| | `jogos-em-direto` | live |
| | `noticias-magazine`, `evasoes`, `volta-ao-mundo`, `delas`, `jn-kids` | revista-do-grupo |
| tag / tag da slice | "Ciência na Europa" | parceria (heurística, por confirmar) |
| assinatura | "Marketing", "Equipa de conteúdo JN" | promocional |
| selo do cartão / zona (fallback HTML) | `__Sponsored`, `__BrandstoryStamp` / `ciencia-na-europa`, `brand-s-life`, `loja-jn` | idem |

Configurável no topo do módulo (`OUT_OF_SCOPE_*`). Um ID rejeitado numa slice fica rejeitado em todas.

**"Ciência na Europa"** (secção `inovacao`): slice alimentada por tag, com autores estrangeiros sem página de
autor no JN (`Slug: null`). Parece conteúdo sindicado (talvez a Horizon da UE), mas nenhum campo o marca como
patrocinado. Fica excluído até haver confirmação.

## Homepage (`parse_homepage(html, base_url, include_excluded=False)`)
- **1.º RSC**: slices por ordem (`{"Title","Config":{Code,Layout,Link,Tags},"Contents":[...]}`).
- **2.º HTML** (fallback): `main article a[href]`; zona em `section header h2`; selo `__Exclusive` → premium.

| Campo | Fonte |
|---|---|
| url, site_article_id, section | `Url` normalizado → ID e secção de topo do path |
| title, lead | `Title`, `Abstract` |
| authors, agencies, byline_raw | `Author.Signature` (+`Author.Url`) → `parse_signature` |
| subsection | `SectionSlug` quando ≠ secção (localidade ou coluna) |
| published_at (+precision) | `Date` → UTC, `"datetime"` |
| access | `Categories[].Premium` (categoria "Exclusivo") ou `Layout.Premium` |
| piece_type / _raw | `Layout` + antetítulo (`Headline`) |
| zone / zones / rank | slug de `Config.Code` ou do título da slice; todas as slices onde aparece; ordem de 1.ª aparição (conta também os excluídos, por isso há buracos) |
| site_meta | `headline`, `section_name`, `layout_code`, `categories`, `has_video`, `has_audio`, `picture_guid` |

Amostra (13/10/2026, 11:30 UTC): **72 no âmbito, 89 excluídos.**
- Excluídos: 52 revista-do-grupo, 18 promocional, 7 patrocinado, 6 video, 6 parceria. O banner Jogos fica fora
  de `<article>` e não é contado.
- Os 72 têm autor: 19 "JN/Agências", 11 "Redação", 1 "AFP".
- 12 são premium.
- Sem RSC, o fallback dá 67.

## Artigo (`parse_article`)
| Campo | 1.ª fonte | Fallback |
|---|---|---|
| canonical_url / aliases | `<link rel=canonical>` / `amphtml` + RSC `UrlApp*` | JSON-LD `url`, `og:url`, RSC `Url` |
| site_article_id | ID do URL canónico | URL pedido, RSC `Id` |
| title / lead | JSON-LD `headline` / `description` | RSC `Title`/`Abstract`, HTML `h1` / `__AGLead` |
| body (Block) | JSON-LD `articleBody` (não existe no exemplo) | RSC `dataset.Body`, `[class*="__AGBodyContent"]` |
| authors / agencies / byline_raw | RSC `Authors[].Signature` (+`Url`) | JSON-LD `author`, `__AGAuthorLink`, meta `author`; agência também no fecho "(Lusa)" |
| images | RSC `dataset.Media[]` + JSON-LD `image.url` | HTML `[class*="__AGPic"] figure/figcaption`; corpo: `figure/figcaption` |
| published_at (+precision) / updated_at | JSON-LD `datePublished` / `dateModified` → UTC | `article:*_time`, RSC `Date`/`DateChanged` |
| section / subsection | URL / RSC `SectionSlug` | — |
| tags | JSON-LD `keywords` (sem duplicados, comparação sem maiúsculas/acentos) | `news_keywords`, RSC `Tags[].Name` |
| piece_type / _raw | RSC `Layout` + `PreTitle`/`Headline` | URL `/opiniao`, JSON-LD `@type` |
| access | JSON-LD `isAccessibleForFree` + RSC `Categories[].Premium`/`Layout.Premium` | — |
| body_complete / body_source / word_count | free sem caixa de paywall → `true`; restantes: `word_count` ≥ 0,9 × RSC `WordCount` / `jsonld|rsc|html` / palavras extraídas | — |
| body[].links | `a[href]` inline nos blocos do corpo (URL absoluto + âncora) | — |
| embeds | RSC `Body` `div[data-type="embed"]`, incluindo refs `"$<id>"` resolvidas para o chunk `<id>:T<len>,…` | HTML `[class*="__AGBodyContent"] div[data-type="embed"]` |
| out_of_scope | regras de âmbito (URL, `SectionSlug`, layout, tags, assinatura) | — |

Exemplo:
- Corpo com 4 blocos e 153 palavras, para 147 de `WordCount` → `body_complete=true`.
- Autor `JN/Agências`, com `url=/autor/jnagencias` e `agencies=["Agências"]`.
- 1 imagem com fotógrafo.
- Ruído descartado do corpo: `div.ArticlePageBodyAd`/`[data-article-body-pub]`, figuras e legendas (vão para
  `images`), `nav` de tópicos e partilhas, "Leia também"/"Saiba mais"/"Subscreva".

Ligações e embeds (v2.2):
- O JN quase não usa links inline: 3 em 15 artigos analisados (todos para outras notícias do JN). O RSC `Body`
  tem os mesmos links que o HTML renderizado; não se perde nada.
- Embeds: `div[data-type="embed"]` fora de `body` e de `links`; URL do post original por plataforma
  (Instagram `data-instgrm-permalink`, X último `a[href*=/status/]` + texto do tweet, Facebook `plugins/*.php?href=`,
  YouTube `/embed/<id>` → `watch?v=<id>`, Vimeo, `blockquote[cite]`). Sem `utm_*`/`ref_src`/`si`.
  Embeds longos vêm por referência (`"$19"`) e são resolvidos no RSC.
- "Leia também" (`blockquote[data-type="articles"]`) fica fora de blocos e links.
- Fixtures: `jn_article_18136523_embeds.html` (X), `jn_article_18136318_embeds.html` (Facebook),
  `jn_article_18136675_wordcount_inflado.html` (Instagram via `$ref`).

### Assinaturas (`parse_signature`, regras v2.1)
| Assinatura | authors | agencies |
|---|---|---|
| `JN/Agências` | [JN/Agências] (colectiva, com `url` da página de autor) | [`Agências`] |
| `Redação` | [Redação] | [] |
| `AFP` | [AFP] | [AFP] |
| `Ana Silva/Lusa` | [Ana Silva] | [Lusa] |
| `A (JN) e Judith Menezes e Sousa (TSF)` | [A `affiliation=JN`, Judith Menezes e Sousa `affiliation=TSF`] | [] |
| `Catarina G., Constança C., Ricardo P.` | 3 autores | [] |

- Assinatura sem pessoas → a assinatura inteira passa a autor colectivo. `byline_raw` guarda sempre a original.
- Separação por `,` e por ` e `. Um pedaço com menos de 2 palavras junta-se ao anterior (não parte
  "Menezes e Sousa").
- `Author.url` só é atribuído quando a assinatura dá um único autor.

### Fotografia (`Article.images`)
- **Artigo**: RSC `dataset.Media[]` = `{MediaType:"image", Url, Guid, Caption, Producer:"Foto: Pedro Granadeiro",
  Flags:["gallery"]}`.
  - A imagem principal usa o JPEG do JSON-LD (`…_1200x675.jpg`) quando o GUID coincide.
  - `caption` ← `Caption`; `credit_raw` ← `Producer`.
  - `parse_photo_credit` tira o prefixo "Foto:"/"Fotos:" e separa por `/`: as partes conhecidas
    (`IMAGE_AGENCIES`: Global Imagens, Lusa, EPA, AFP, Reuters, Getty Images, D.R.…) vão para `agency`, o resto
    para `photographers`.
  - Ex.: "Foto: Rui Oliveira/Global Imagens" → `photographers=[Rui Oliveira]`, `agency=Global Imagens`;
    "Lusa/EPA" → `agency=Lusa/EPA`.
- **Fallback HTML**: `[class*="__AGPic"] figure > figcaption` com 2 `<p>` (legenda e "Foto: …").
- **Corpo**: `<figure>` dentro do `Body` (não houve nenhuma no exemplo; testado com fragmento sintético).
- **Homepage**: **sem crédito**. `Picture` só traz `{Guid, Url, Flags}` e o HTML só tem `alt` "Imagem de
  contexto do artigo …". O GUID fica em `site_meta.picture_guid`.
- Não há página de fotógrafo; os fotógrafos não entram em `authors`.
- `Image.is_archive=True` quando o crédito tem "Arquivo"/"arq." (ex. "Foto: Rui Oliveira/Arquivo"). "Arquivo" é
  removido de `photographers`/`agency`.
- `Media[].Flags`: `highlight`/`gallery` marcam a imagem principal; `text` marca uma imagem inserida no texto.
  No 18135966 (premium) a 2.ª imagem (`Flags:["text"]`) não tem `Caption` nem `Producer` e não é desenhada no
  HTML: está no texto cortado pelo paywall. Não é a imagem do autor (essa está em `Authors[].Images`) nem um
  placeholder. Fica em `images`, com "FALHA DE CRÉDITO" no `extraction_debug.images`.

### Premium sem texto integral (decisão 2026-10-13)
- Crawl real do 18135966 ("Governo admite rombo…", Exclusivo): o source só traz o 1.º parágrafo
  (72 palavras, contra `WordCount` 873). O resto não está no HTML nem no RSC `Body`.
- O corte é marcado em três sítios: JSON-LD `isAccessibleForFree:false`, categoria `NG:Exclusivo`
  (`Premium:true`) e a caixa HTML `[class*="__ArticlePaywall"]` ("Conteúdo exclusivo para assinantes").
- Regra: `access="premium"` com corpo incompleto (`word_count < 0,9 × WordCount` ou caixa de paywall) dá
  `out_of_scope="premium_sem_texto_integral"`, `body_complete=False`, `body=[]` e `word_count=None`. O nº de
  palavras parciais fica no `extraction_debug.body_complete`.
- **Saber se é premium sem abrir o artigo:**
  - homepage: **sim**, pelo RSC `Categories[].Premium` (selo "Exclusivo") → `access="premium"` (12/72 a 13/10);
  - news sitemap e sitemaps diários: **não**, não trazem nenhum campo de acesso.
  - Os artigos descobertos só pelo sitemap têm de ser abertos (ou cruzados com a homepage) para saber.

### Tipo de peça e paywall
- `Layout.Opinion=true`/`NG:Opinião` → `opiniao`; `NG:Article` → `noticia` (valor por omissão do site);
  `NG:Infografia` → None.
- Antetítulo (heurístico): "Entrevista…" → `entrevista`; também reportagem, análise, editorial, crónica,
  crítica, fact check, "Investigação JN".
- Paywall: categoria `{"Code":"NG:Exclusivo","Premium":true}` (selo "Exclusivo"); JSON-LD `isAccessibleForFree`.

## Descoberta: sitemaps e RSS
**Decisão legal.** O `robots.txt` abre com este disclaimer:

> É proibido o uso de web crawlers ou outros métodos automáticos de navegação neste site. Proibimos o rastreamento
> de nosso site usando um agente que não corresponda à sua identidade conforme número 2 alínea w) do artigo 75º do
> Decreto Lei n.º 63/85, de 14 de Março. Convidamos-vos a entrar em contato connosco para subscrever uma licença de
> utilizador. Apenas os nossos parceiros têm o direito de utilizar o nosso conteúdo para uma finalidade que não seja
> estritamente individual.

**PoC interna: avançar por decisão do utilizador (2026-10-13).** Nada é publicado. Antes de passar a produção
é preciso licença ou parecer legal.

Pedidos feitos: 6 (2× `robots.txt`, news sitemap, índice, 2 sitemaps diários).
- User-Agent: `FactosBot/0.1 (PoC interna; contacto …)`; intervalo ≥2s (`Crawl-delay: 1`).
- Nada em `/embed/`, `/_next/`, `/api/`.

Regras técnicas do `robots.txt`:
- `User-agent: *` tem `Crawl-delay: 1` e `Disallow` de `/embed/`, `/_next/`, `/api/` e `?utm_*`/`?fbclid*`/`?gclid*`.
- GPTBot e CCBot estão bloqueados.

| Sitemap | Formato | Campos | Janela / entradas | Cache | Amostra |
|---|---|---|---|---|---|
| `/feed/news/sitemap.xml` | Google News `urlset` | `loc`, `news:publication_date` (UTC, `Z`), `news:title`, `news:keywords`, `news:genres` (só `Opinion`, 16×) | ~48h (11/10 13:02 → 13/10 11:57 UTC), 267 URLs | `max-age=30` | `sites/jn_sitemap_news.xml` |
| `/feed/sitemap.xml` | `sitemapindex` | `loc` | 1 sitemap por dia, 8170 dias (2004-06-01 → hoje) | `s-maxage=1800` | `sites/jn_sitemap_index.xml` |
| `/feed/sitemap.xml?yyyy=AAAA&mm=MM&dd=DD` | `urlset` | `loc`, `lastmod`, `changefreq` (`hourly` hoje, `daily` ontem); **sem título** | dia em UTC: 56 (13/10 até 11:57), 148 (12/10) | — | `sites/jn_sitemap_day_2026-10-1{2,3}.xml` |
| `/feed/image/sitemap.xml` | — | não descarregado | | | |
| `/feed/video/`, `/feed/apostas/`, `/feed/casino/` | — | ignorados (fora de âmbito) | | | |

- O ID vem sempre no `loc` (mesmo padrão `/artigo/<slug>/<id>`).
- `lastmod` do diário = data de publicação ao minuto nos 55 casos cruzados com a homepage (a homepage tem
  `:01` nos segundos das opiniões). Não está confirmado se muda com edições.
- As revistas do grupo quase não aparecem (1 `jn-kids` no news sitemap); as `iniciativas` não aparecem.
- O news sitemap traz `jn-direto` (4), `brands-life` (1), `jogos-em-direto` (1); o diário de 12/10 traz
  `apostas` (2).
- RSS/Atom: nenhum `<link rel=alternate>` no HTML. Não testei caminhos de feed: fiz só os pedidos autorizados.

**Cobertura (13/10/2026):**
- Homepage → news sitemap: **54/54 = 100 %** dos artigos no âmbito publicados dentro da janela de 48h. Os
  outros 18 são mais antigos (Academia de Notícias, Poder Local, opinião de 05/10…) e estão fora da janela.
- News sitemap → homepage: só **54 dos 260** no âmbito (21 %) aparecem na homepage.
- Diário 12+13/10: 204 URLs, 202 também no news sitemap (os 2 restantes são `apostas`). Todos os 51 artigos
  da homepage publicados a 12–13/10 estão no diário.
- O que o sitemap traz e a homepage não: ~4/5 da produção diária (sobretudo `mundo`, `pais`, `desporto`),
  `keywords` e `genres`. Não traz autor, lead, acesso nem zona.

**Funções:**
- `parse_sitemap_index(xml) -> list[str]`.
- `parse_sitemap(xml, include_excluded=False) -> list[HomepageItem]`: serve para o news sitemap e para os
  diários, com as mesmas regras de âmbito. Do diário, `lastmod` vai para `site_meta` e não para `published_at`.
- Usa `lxml` com `resolve_entities=False, no_network=True`.
- Sem `parse_feed`: não há feed conhecido.

**Estratégia recomendada:**
1. **News sitemap como fonte principal**: 1 pedido a cada 5–10 min (configurável). A cache é de 30s e há
   ~140 URLs/dia (148 a 12/10), por isso 10 min dá folga. Traz ID, título, data e opinião.
2. **Sitemap diário de hoje e de ontem** como rede de segurança, 1–2×/hora. Apanha o que sair da janela de 48h
   ou falhar no news.
3. **Homepage a cada 15–30 min**, não para descoberta mas como **sinal editorial**: `zone`/`rank`/`zones`
   (destaques, mais vistas), `access` premium, autor e antetítulo antes de abrir o artigo.
4. **Backfill histórico** pelo índice (desde 2004), com rate limit baixo, só se for decidido.

## Notas de duplicados
- 18136568 (JN, "Ministério da Administração Interna é 'novela permanente de casos'…", assinado
  "JN/Agências") é o mesmo take da Lusa que o Observador 8365764. Há uma divergência de texto: o JN escreve
  "**acima** do valor previsto na lei" e o Observador "**abaixo**". É um caso útil para a detecção de
  duplicados e réplicas e para a análise de diferenças entre réplicas.

## Limitações e casos por validar
- Só 1 notícia de exemplo (grátis, "JN/Agências", 1 foto). Premium, Lusa, actualização, foto no corpo e
  crédito com agência foram testados com HTML alterado ou fragmentos sintéticos.
- Validado (crawl real): o `Body` de um "Exclusivo" vem **cortado** (só o 1.º parágrafo).
- Por validar: o `Layout.Code` de live blogs e podcasts; a semântica
  de `lastmod` (publicação vs edição); o image sitemap (pode trazer créditos).
- "Ciência na Europa": exclusão heurística.
- `piece_type` pelo antetítulo é heurístico; `NG:Article` → `noticia` é o valor por omissão.
- Peças com vídeo fora de `jn-direto` (`HasVideo=true`) entram.
- Classes CSS com hash podem mudar a cada deploy.
- O `WordCount` do JN conta o source do corpo (markup, embeds, abstract) e vem inflacionado de forma irregular
  (ex.: 18136675, 219 palavras reais vs 949, por um embed do Instagram). Só decide `body_complete` em premium;
  em free sem paywall o rácio fica como nota de debug. Fixture: `jn_article_18136675_wordcount_inflado.html`.
