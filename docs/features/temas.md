# Temas e edições — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Organiza as notícias por tema, com hierarquia e edições (ex.: Orçamento do Estado 2025, 2026). A temperatura de
cada tema determina os temas quentes do front-end e a cadência das [revisitas](versoes.md).

## Funcionalidades

### Associação a temas existentes primeiro
- **O quê**: o modelo associa sempre a notícia a temas que já existem. Só propõe um tema novo quando não encontra
  correspondência. Evita "Orçamento do Estado 2026", "Orçamento 2026" e "OE2026" como três temas.
- **Tema novo**: fica no estado **por rever** no [backoffice](backoffice.md). A notícia fica associada
  provisoriamente e já conta para a temperatura.
- **Implementado**: o LLM recebe como candidatos os temas da BD, os mais quentes primeiro; o caminho devolvido resolve-se nível a
  nível e o que faltar cria-se `por_rever` (com os pais). Taxonomia semente: `themes_seed.json` do benchmark (47 temas activos).
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Hierarquia
- **O quê**: árvore de temas. Exemplo: Política > Orçamento do Estado > OE2026 > IRS Jovem.

### Tema, evento e caso
- **O quê**: são coisas distintas. Um caso (ex.: Spinumviva) não é o mesmo que o tema (ex.: Corrupção). Os eventos
  têm data e podem entrar na timeline das [entidades](entidades.md).

### Edições e tipo de recorrência
- **O quê**: cada tema tem um tipo de recorrência que diz ao modelo em que edição colocar a notícia:
  - **Anual**: Orçamento do Estado, Estado da Nação (cada um na sua data).
  - **Por evento**: eleições (uma edição por eleição).
  - **Nenhuma**: casos judiciais.
- **Várias edições na mesma notícia**: uma notícia que compara o OE2025 com o OE2026 liga-se às duas edições.

### Vários temas por notícia
- **O quê**: uma notícia pode ter vários temas, cada um com várias edições.
- **Peso de relevância 0–1** em cada relação notícia↔tema, em vez de primário/secundário.

### Temperatura
- **O quê**: mede quão "quente" está um tema.
- **Como funciona**: nº de notícias novas por janela temporal, ponderado pelo nº de meios distintos, com
  decaimento no tempo. Sem dados de redes sociais.
- **Fórmula implementada** (`topics/service.py`, `recompute_all` a cada 15 min): Σ peso × 0,5^(idade_h / `topics.half_life_h` 24)
  × (1 + `topics.media_weight` 0,5 × (meios − 1)), dentro da janela `topics.window_h` (72 h); só conta a última análise de cada
  artigo. Histórico em `TopicTemperature`. Limiares: frio < `topics.cold_threshold` 0,5; quente ≥ `topics.hot_threshold` 5,0.
- **Sem roll-up para os pais**: a temperatura fica no tema-folha ou na edição. Se for agregada nos pais, "Política" ou "Governo" estariam sempre quentes (por decidir).
- **Uso**: temas quentes no [front-end](frontend.md); cadência das revisitas (manda o tema mais quente da notícia).

### Fusão e divisão
- **O quê**: os temas fundem-se e dividem-se ao longo do tempo, via [backoffice](backoffice.md). Quando se funde
  um tema com outro, as notícias e a temperatura migram automaticamente.

## Modelo de dados
Conceptual:
- **Tema**: nome, pai, tipo (tema, evento, caso), tipo de recorrência, estado (activo, por rever, fundido).
- **Edição**: tema, identificador (ano, eleição…), datas.
- **Notícia↔Tema/Edição**: peso 0–1, debug do modelo.
- **Temperatura**: tema-folha/edição, valor, timestamp (histórico).

## Endpoints
`/api/topics/`, `/api/topics/review-queue`, `/api/topics/hot`, `/api/topics/editions`, `/api/topics/merge` (dry-run por omissão). Ver [backoffice](backoffice.md#endpoints).

## Por fazer
- Temas amplos (Crime, Governo) ficam quentes: afinar `topics.hot_threshold` e os pesos; decidir o roll-up para os pais.
- Rever em lote os temas `por_rever` (45 no smoke test) pela skill/CLI.
- Matching por embeddings (hoje só a lista de candidatos ao LLM).
- Regras de atribuição de edição por tipo de recorrência.

## Notas e limitações
- A temperatura de um tema por rever conta desde logo; se for fundido, migra.
- Smoke test: 47 temas activos + 45 `por_rever`; mais quentes: Forças de segurança, Crime, Governo.
