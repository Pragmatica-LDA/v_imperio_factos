# Fontes — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Configuração dos sites de notícias a monitorizar e dos pontos de entrada usados para descobrir notícias novas.
Adicionar um site deve ser só uma questão de configuração, sem código novo para o caso comum.

## Funcionalidades

### Configuração por site
- **O quê**: cada site tem a homepage, as secções/categorias, os feeds RSS e os sitemaps (incluindo news
  sitemaps, `sitemap-news.xml`), quando existirem.
- **Como funciona**: a descoberta ([crawl](crawl.md)) percorre todos os pontos de entrada do site. Os RSS e os
  sitemaps são preferidos porque apanham as notícias que nunca chegam à homepage (ou que lá ficam 20 minutos) e
  trazem muitas vezes a data e o ID interno.
- **Ficheiros-chave**: `backend/sources/models.py`, `backend/sources/seed.py`, `backend/sources/discovery.py`, `backend/sources/tasks.py`.
- **Adicionado/alterado em**: 2026-10-13 (conceito; implementado no backend).

### Âmbito de conteúdo
- **O quê**: faz-se o crawl de **todo** o conteúdo dos sites configurados; a classificação (temas, tipo de peça)
  acontece depois. Política é o caso de referência.
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Arranque
- **Sites de arranque**: Observador, JN e Público (escolha do utilizador, 2026-10-13). Revistas do grupo ficam
  fora; se um dia entrarem, são fontes independentes.
- **Outros candidatos**: RTP, SIC Notícias, CNN Portugal, DN, ECO, Notícias ao Minuto, Expresso, Lusa.

### Estratégia de descoberta por site
A homepage não chega para descobrir notícias: só mostra 21% (JN) a 33–45% (Observador) das notícias publicadas.
A descoberta vem dos sitemaps; a homepage fica como sinal de destaque (zona e posição) e, no JN, como fonte do
sinal de premium.

| Site | Fonte principal | Complementos | Notas |
|---|---|---|---|
| Observador | `/wp-sitemap.xml`: última página dos tipos post, obs_longform, obs_opinion, obs_factcheck, cada 10–15 min | Homepage 15–30 min; RSS `/feed/` opcional (dá a assinatura Lusa) | Sem news sitemap; o sitemap só tem `loc` + `lastmod` (pode ser anterior à publicação em peças agendadas) |
| JN | `/feed/news/sitemap.xml` (~48h, título, data, keywords), cada 5–10 min | Sitemaps diários (hoje e ontem) 1–2×/h; homepage 15–30 min | Premium só se vê na homepage; índice `/feed/sitemap.xml` com 1 sitemap por dia desde 2004-06-01 (backfill possível); sem RSS conhecido |
| Público | `/sitemaps/news.xml` (proposta, não validada) | Homepage 15–30 min; RSS Feedburner | Amostras de sitemap e RSS por fornecer pelo utilizador |

Detalhe em [docs/sites/](../sites/) e [parsers](parsers.md).
- **Adicionado/alterado em**: 2026-10-13 (análise dos agentes de site).

### robots.txt e acesso
- **JN**: o robots.txt tem um aviso legal que proíbe crawlers sem licença, mas as regras técnicas não bloqueiam.
  Decisão do utilizador: avançar, por ser uma PoC interna e nada ser publicado. Produção precisa de licença ou parecer.
- **Observador**: permite os bots do Claude; sem restrições relevantes.
- **Público**: bloqueia explicitamente cerca de 150 bots de IA, **incluindo o Claude Code**. Os agentes Claude não
  fazem pedidos ao publico.pt (trocar o User-Agent seria evasão). O crawl é corrido pelo utilizador, com o
  crawler dele; as amostras são fornecidas por ele em `sites/`.
- **Adicionado/alterado em**: 2026-10-13.

### Pontos de entrada e cadências (implementado)
- **Seed** (`sources/seed.py`, aplicado por `manage.py bootstrap`):

  | Site | Pontos de entrada (kind, intervalo) |
  |---|---|
  | Observador | `sitemap_index` wp-sitemap, tipo post (10 min); longform, opinion e factcheck (30 min); homepage (20 min); `/feed/` (30 min) |
  | JN | `sitemap_news` (5 min); `sitemap_daily` hoje+ontem, template `{yyyy}{mm}{dd}` (30 min); homepage (20 min); `min_delay_s` 2 s; `skip_premium_on_discovery` |
  | Público | `news.xml` (5 min); homepage (20 min); Feedburner (30 min) |

- **Kinds**: `homepage`, `sitemap`, `sitemap_news`, `sitemap_index`, `sitemap_daily` (`days_back`), `feed`. Cada `EntryPoint`
  tem `interval_s`, `next_run_at` e `config`; cada execução gera um `DiscoveryRun` (found, excluded, new, updated, skipped_old,
  error, urls_fetched).
- **Tarefas**: `tick_discovery` (60 s) enfileira os entry points vencidos; `discover_entrypoint` corre um.
- **Sem backfill**: itens mais antigos que `discovery.max_item_age_h` (24 h) são ignorados (`skipped_old`).
- **Site**: `slug`, `parser_module`, `min_delay_s`, `skip_premium_on_discovery` e FK para a entidade do meio.
- **Adicionado/alterado em**: 2026-10-13.

### O site como entidade
- **O quê**: cada meio é também uma [entidade](entidades.md). O `bootstrap` cria uma entidade de tipo meio por `Site` (`Site.entity`). Quando uma notícia cita outro meio como fonte,
  a [análise](analise.md) liga-a directamente à entidade desse meio.

## Modelo de dados
- **Site**: slug, parser_module, min_delay_s, skip_premium_on_discovery, entity (FK), activo.
- **EntryPoint**: site, kind, URL, interval_s, next_run_at, config.
- **DiscoveryRun**: entry point, contadores (found, excluded, new, updated, skipped_old, error, urls_fetched), timestamps.

## Endpoints
`/api/sites/`, `/api/entrypoints/` (+ `run`) e `/api/discovery-runs/` (ver [backoffice](backoffice.md#endpoints)).

## Por fazer
- Validar a estratégia do Público com amostras reais de `news.xml`, `sitemapindex.xml` e Feedburner.
- Decidir: marcas do Público (P3, Fugas, Ípsilon, Ímpar, Azul, Público Brasil), "Ciência na Europa" (JN, hoje
  excluído) e "Especial Executivos" (Público, hoje incluído).
- Detecção automática de RSS e sitemaps ao adicionar um site.
- Política de rate limiting e robots.txt para produção (ligada à fase legal, ver [README](../README.md#adiado)).
- Validar no primeiro run completo as fontes do Público (`news.xml`, Feedburner), ainda não exercitadas (os agentes Claude não fazem pedidos ao publico.pt; corre o crawler do sistema).

## Notas e limitações
- Premium sem texto integral fica fora de âmbito (ver [crawl](crawl.md#premium)).
- Os 3 sites estão activos e o beat ligado (decisão do utilizador, 2026-10-13); o crawler do sistema (`FactosBot`) é que acede ao Público.
