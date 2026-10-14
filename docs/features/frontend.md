# Front-end — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Página "todo-terreno" para perceber o que está a acontecer na actualidade, a partir de tudo o que foi recolhido:
histórias do momento, quem está nas notícias, temperatura dos temas, últimas por meio, números do arquivo, detalhe de
cada notícia/entidade/tema e arquivo pesquisável. React 19 + Vite, sem dependências extra (router por hash, gráficos SVG).

## Decisão: notícias ou factos?
A unidade principal é a **história**: notícias da janela `front.window_h` (24h) agrupadas quando estão no mesmo
cluster de duplicados ou partilham entidades salientes (pessoas, partidos, instituições…; ≥ `front.story_min_shared`
e sobreposição pesada pelo IDF ≥ `front.story_min_similarity`). A história mostra a notícia-líder e as dos outros meios
("Também"). Os "factos" (timelines das entidades) ainda não existem; entram quando houver enriquecimento.

## Funcionalidades

### Homepage (`#/`)
- **Pulso**: notícias na janela, histórias com várias notícias, entidade mais citada, arquivo, entidades.
- **Agora**: histórias ordenadas por actualidade (meia-vida `front.story_half_life_h`) × cobertura
  (`front.story_weight_coverage`) × temperatura do tema (`front.story_weight_temperature`) × destaque na homepage
  (`front.story_weight_homepage`). Agrupamento guloso não transitivo (evita histórias-gigante).
- **Quem está nas notícias**: entidades com mais notícias na janela, variação face à janela anterior, tom das menções.
  Excluídos: tipos `front.entity_exclude_types` (meios) e menções só com papéis `front.entity_exclude_roles` (autor).
- **Onde**: locais mais citados.
- **Temperatura dos temas**: barra, sparkline do histórico (`TopicTemperature`), notícias na janela / 72h, meios.
- **Últimas por meio**: JN, Público, Observador (`front.latest_per_site`).
- **Números**: tom (positivas/neutras/negativas), IA (com/sem), tipo de peça, notícias por dia por meio.
- **Adicionado/alterado em**: 2026-10-13.

### Indicadores derivados
- **Tom da notícia**: a análise não tem sentimento global. Média do sentimento por entidade (sem locais;
  `sentiment_score` ou ±1/0); positivo/negativo além de ±`front.tone_threshold` (0,25).
- **Com IA**: `ai_indicator.score` ≥ `front.ai_threshold` (50). Indicador do LLM de análise, não veredicto.

### Detalhe da notícia (`#/noticia/<id>`)
Resumo, entidades com papel/tom/justificação, locais, fontes citadas, texto integral, versões, duplicados (mesmo texto
de origem), **mesmo tema** e **outros temas, mesmas pessoas** (entidades partilhadas pesadas pelo IDF, ≥
`front.story_min_shared`), link para o original.

### Entidade (`#/entidade/<id>`) e tema (`#/tema/<id>`)
Entidade: notícias, tom das menções, por meio, série diária (`front.entity_days`), papéis, cargos, entidades que
aparecem com ela, temas. Tema: caminho, temperatura e histórico, série diária, subtemas (incluídos nas contagens),
edições, entidades, notícias.

### Arquivo (`#/arquivo`) e pesquisa
Tabela paginada com filtros (título, meio, tipo de peça, datas, tema, entidade). Pesquisa rápida no cabeçalho
(entidades e aliases, temas, títulos).

### Login
Token DRF via `POST /api/auth/token/` (utilizador Django; `front.LoginView`), guardado no `localStorage`. 401 → volta ao login.
O login não usa autenticação por sessão: com sessão aberta no admin (os cookies de `localhost` são partilhados entre
portas) o DRF exigia CSRF e respondia 403.

## Endpoints
`backend/api/front.py`, só leitura, autenticados:
- `GET /api/front/overview/` — tudo da homepage. Pré-calculado pela tarefa periódica `api.tasks.warm_front_overview`
  (60 s, fila `maintenance`), guardado por 2 × `cache.front_s`.
- `GET /api/front/articles/?q&site&topic&entity&piece_type&since&until&limit&offset`
- `GET /api/front/articles/<id>/`, `/api/front/entities/<id>/`, `/api/front/topics/<id>/`, `/api/front/search/?q`
- `POST /api/auth/token/`

## Ficheiros-chave
`backend/api/front.py`, `backend/api/tasks.py`, `backend/tests/test_front.py` (11 testes);
`frontend/src/{App.tsx, api.ts, router.ts, types.ts, format.ts, styles.css}`, `frontend/src/pages/*`, `frontend/src/components/ui.tsx`.

## Por fazer
- Rever com o utilizador a afinação das histórias e do tom (limiares em parâmetros).
- Filtro por tom/IA no arquivo (hoje só visível).
- Timeline das entidades quando houver enriquecimento.
- Estatísticas de estudo: fontes anónimas por meio, volatilidade/edições, notícias apagadas, exportação.
- Build de produção e servir o frontend fora do Vite.

## Notas e limitações
- Uso interno. Fontes (Newsreader, Instrument Sans, JetBrains Mono) via Google Fonts.
- O overview a frio leva ~12 s na BD em Docker local; por isso é pré-calculado.
