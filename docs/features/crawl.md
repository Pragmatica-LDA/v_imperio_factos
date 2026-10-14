# Crawl e extracção — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Descobre links de notícias novos desde o último crawl, coloca-os numa fila e processa cada um: descarrega a
página, guarda-a completa e extrai apenas o artigo. É o ponto de entrada de cada notícia na base de dados.

## Funcionalidades

### Descoberta de links novos
- **O quê**: percorre os pontos de entrada de cada site ([fontes](fontes.md)) e regista os links que ainda não
  existem na base de dados.
- **Como funciona**: compara os links encontrados com as notícias já conhecidas (pelo ID interno do site quando
  detectável, senão pelo URL canónico). Os links novos entram na fila.
- **Implementado**: `sources/discovery.py` (`run_entrypoint`) usa `parsers/registry.py`; `crawl/ingest.py` `register_item` cria
  ou actualiza o `Article` (estado `discovered`) e enfileira o fetch. Observador: o ID só se conhece depois do fetch, por isso
  artigos com o mesmo ID são fundidos. Mudança de `lastmod` no sitemap (Observador) → revisita imediata (`revisit.on_lastmod_change`).
- **Adicionado/alterado em**: 2026-10-13 (conceito; implementado).

### Fila de processamento
- **O quê**: desacopla a descoberta do processamento. Cada link na fila é descarregado, extraído e enviado para a
  [análise](analise.md). A mesma infraestrutura serve as revisitas ([versoes](versoes.md)) e o enriquecimento de
  [entidades](entidades.md).
- **Como funciona**: Celery, com uma fila por tipo de trabalho (`discovery`, `crawl`, `analysis`, `enrichment`,
  `revisits`). Broker Redis (ver [arquitectura](arquitectura.md#broker-e-filas-decidido-e-implementado)). `crawl/tasks.py`: `fetch_article` (fila `crawl`, também serve as revisitas) e `sweep_revisits`.

### Página completa + extracção do artigo
- **O quê**: guarda o HTML completo de cada leitura, mas a análise e o diff usam **só o conteúdo extraído**:
  título, lead, corpo, autor, data de publicação, marca "actualizado às".
- **Porquê**: os blocos à volta do artigo ("leia também", publicidade, contadores de comentários, links
  relacionados) mudam constantemente e gerariam falsas edições.
- **Estratégia decidida**: parsers com regras por site, preferindo dados estruturados (ver [parsers](parsers.md)).
  PoC feita para Observador, JN e Público, com crawl real de homepages e de 2 artigos por site.
- **Ficheiros-chave**: `backend/parsers/`, `backend/crawl/quality.py`, `crawl_homepages.py`, `crawl_articles.py` (PoC).
- **Adicionado/alterado em**: 2026-10-13 (PoC; integrado no backend).

### Premium
- **O quê**: artigos premium sem texto integral no source code ficam fora de âmbito e o corpo parcial não é guardado.
  Quando a homepage já marca o premium (JN), o artigo nem é descarregado. O Observador entrega o texto integral no
  HTML, por isso os premium entram.
- **Público**: o servidor corta o corpo (1.º parágrafo + gate Piano). O premium detecta-se no artigo
  (JSON-LD `isAccessibleForFree=false`, `publicoConfig.isExclusivo`, `#paywall-disclaimer`), mas não na homepage.
- **Adicionado/alterado em**: 2026-10-13 (decisão).

### Identidade da notícia
- **O quê**: a notícia é identificada pelo ID interno do site quando é detectável, porque muitos sites geram o slug
  a partir do título e o URL muda quando o título muda. Uma notícia pode ter vários URLs associados.
- **Fallback**: sem ID detectável, usa o URL canónico; se não for possível ligar, "é o que é".
- **JN**: o ID é o último segmento de `/<secção>/artigo/<slug>/<id>` (8 dígitos) e vem também em todos os sitemaps;
  a versão AMP (`/amp/<id>/<slug>`) é guardada como alias (ver [jn](../sites/jn.md#urls-e-id)).
- **Público**: o ID é o número no fim do slug, em `/AAAA/MM/DD/<secção>/<tipo>/<slug>-<id>` (7 dígitos). O link curto
  `/n<id>` (relacionados, "Ler mais") é guardado como alias (ver [publico](../sites/publico.md#urls-e-id-interno)).

### Fetch e regras HTTP (implementado)
- **HTTP**: `crawl/http.py` (httpx, redirects manuais para guardar a cadeia). Rate limit por site em `crawl/ratelimit.py`
  (Redis `SET NX PX`, `Site.min_delay_s`).
- **Armazenamento**: HTML gzip no volume `raw_html` (`crawl/storage.py`), caminho em `Fetch.raw_path`.
- **Resultado** (`crawl/ingest.py` `process_fetch`): `Fetch.outcome` = ok | unchanged | out_of_scope | deleted | redirect |
  technical_failure | parse_error. 404/410 e redirect para homepage/secção → `deleted`; 301 para outro artigo → novo `ArticleURL`;
  parse fora de âmbito (ex.: premium) → `out_of_scope`; só há `Version` nova se o hash do conteúdo mudou.
- **Qualidade**: `crawl/quality.py` (diagnóstico portado da PoC) grava `Fetch.quality` (JSON) e `quality_ok`; alimenta o
  [dashboard](backoffice.md#dashboard-de-fiabilidade-do-crawl).
- **Estados do `Article`**: discovered | active | out_of_scope | deleted | failed.
- **Adicionado/alterado em**: 2026-10-13.

### Falhas técnicas
- **O quê**: timeouts, 5xx, 403/429 e bloqueios **não** são dados editoriais. Vão para `TechnicalFailure`, com retry e backoff
  (`failures.backoff_s`, máximo `failures.max_attempts`); `sweep_failures` corre a cada 5 min. Reenvio manual em `POST /api/failures/<id>/retry`.
- **Nota**: as respostas com significado editorial (404, 410, 301) estão em [versoes](versoes.md).

## Modelo de dados
- **Article**: site, ID interno, status, `next_revisit_at`, `revisit_reason`, `revisit_topic`, `late_revisit_done`, `version_count`, `change_ratio_total`.
- **ArticleURL**: artigo, URL, tipo (canónico, alias, redirect).
- **Fetch**: artigo, timestamp, HTTP, URL final, `outcome`, `quality` + `quality_ok`, `raw_path`.
- **HomepageAppearance**: artigo, zona, posição, timestamp.
- **TechnicalFailure**: fetch, tipo de erro, nº de tentativas, estado.

## Endpoints
`/api/articles/` (+ `versions`, `refetch`, `ingest`), `/api/fetches/`, `/api/failures/` (+ `retry`), `/api/stats/crawl-health`
(ver [backoffice](backoffice.md#endpoints)).

## Por fazer
- Premium no Público e no Observador só se sabe ao abrir o artigo: avaliar a página `/exclusivos` do Público.
- Público: há episódios de podcast publicados com URL `/noticia/`. Na homepage detectam-se pela zona e pela
  assinatura de áudio ("edição de som"), mas num sitemap ou feed só se apanham depois de abrir o artigo.
- Validar o crawl do Público no primeiro run completo (descoberta e extracção).
- Rever a política de retry das falhas técnicas com dados reais.
- Smoke test real (3 h, Observador + JN): 112 artigos novos, 112/112 HTTP ok, 0 falhas técnicas, 1 premium JN excluído; qualidade Observador 100%, JN 84% (4 falsos negativos, entretanto corrigidos).

## Notas e limitações
- O texto integral é guardado por agora; a retenção é decidida na fase legal (ver [README](../README.md#adiado)).
