# Factos

> Estado: ⚠️ parcial (pipeline ligado e front-end inicial; falta enriquecimento)  ·  Última actualização: 2026-10-13

Base de dados histórica de notícias portuguesas. Recolhe as notícias dos sites configurados, analisa-as
(entidades, sentimento por entidade, fontes, temas e edições, tipo de peça, indicador de IA) e regista as
versões de cada notícia através de revisitas dinâmicas.

## Visão do produto
- **Uso**: interno, para já.
- **Objectivo**: construir, ao longo do tempo, um arquivo estruturado e consultável. Exemplo: "todas as notícias
  sobre o Orçamento do Estado 2023–2026", "crimes em Lisboa vs Porto", "que meio usa mais fontes anónimas".
- **Front-end**: estatísticas, temas quentes do momento, pesquisa histórica.
- **Backoffice**: revisão humana de temas, entidades e timelines.
- **Sem backfill**: a recolha começa no dia de arranque (o que ainda estiver nas homepages e feeds entra).
- **Foco inicial**: política é o caso de referência, mas faz-se o crawl de tudo e classifica-se depois.
- **Sites de arranque**: Observador, JN e Público (ver [fontes](features/fontes.md) e [docs/sites/](sites/)).

## Pipeline (conceptual)
```
Fontes (site, secções, RSS, sitemaps)
  → Descoberta de links novos  → Fila
  → Crawl + extracção do artigo → Versão v1
  → Análise (entidades, sentimento, fontes, temas, tipo de peça, IA) → Duplicados
  → Temperatura dos temas → Agendamento de revisitas → v2, v3… (diff de texto + diff de análise)
Em paralelo: enriquecimento de entidades (timeline) via agente com internet (por implementar)
```
Implementado e ligado de ponta a ponta (tarefas Celery) até duplicados, temperatura e revisitas; falta o
enriquecimento e a detecção de IA dedicada; o front-end inicial já existe. Ver [ROADMAP](ROADMAP.md).

## Stack
Django 6.0 + DRF (backend), React 19 + Vite (frontend), Celery + beat (tarefas), Redis (broker e cache, instâncias separadas),
Postgres 18 + pgvector, httpx (crawl), LLM gemma4:31b no Ollama Cloud (análise; trocável por parâmetro). Tudo em Docker Compose (`docker compose up --build`). API-first e gestão por agentes
via CLI + skill. Detalhe e propostas por confirmar em [arquitectura](features/arquitectura.md).

## Princípios transversais
1. **Tudo configurável**: limiares, tempos, pesos e fórmulas vivem em configuração.
2. **Debug em cada decisão de um modelo**: raciocínio, fontes usadas e fontes descartadas.
3. **Revisão humana** no backoffice para temas, entidades e timelines (os modelos propõem, as pessoas corrigem).
4. **Associar ao que já existe antes de criar**: temas e entidades novos só quando não há correspondência.
5. **Factos frescos, nunca de memória**: a timeline das entidades vem de pesquisa na internet, com URLs de origem.
6. **Texto integral guardado** por agora; a política de retenção é decidida na fase legal.

## Áreas

| Área | Doc | Estado |
|---|---|---|
| Arquitectura | [arquitectura](features/arquitectura.md) | ⚠️ parcial |
| Fontes | [fontes](features/fontes.md) | ⚠️ parcial |
| Crawl e extracção | [crawl](features/crawl.md) | ⚠️ parcial |
| Parsers | [parsers](features/parsers.md) | ⚠️ parcial |
| Versões e revisitas | [versoes](features/versoes.md) | ⚠️ parcial |
| Temas e edições | [temas](features/temas.md) | ⚠️ parcial |
| Entidades | [entidades](features/entidades.md) | ⚠️ parcial |
| Análise da notícia | [analise](features/analise.md) | ⚠️ parcial |
| Duplicados | [duplicados](features/duplicados.md) | ⚠️ parcial |
| Backoffice | [backoffice](features/backoffice.md) | ⚠️ parcial |
| Front-end | [frontend](features/frontend.md) | ⚠️ parcial |

## Parâmetros configuráveis (valores iniciais)

| Parâmetro | Valor inicial | Área |
|---|---|---|
| Intervalo mínimo de revisita (tema quente) | 2h | [versoes](features/versoes.md) |
| Intervalo máximo de revisita (antes do corte) | 12h | [versoes](features/versoes.md) |
| Revisita tardia (correcções e apagamentos) | 7 dias | [versoes](features/versoes.md) |
| Cadência para notícias sem tema | 6h até 48h (`revisit.no_topic_interval_h`, `revisit.no_topic_max_age_h`) | [versoes](features/versoes.md) |
| Janela temporal da temperatura | 72h (`topics.window_h`) | [temas](features/temas.md) |
| Ponderação pelo nº de meios distintos | +0,5 por meio adicional (`topics.media_weight`) | [temas](features/temas.md) |
| Decaimento da temperatura | meia-vida 24h (`topics.half_life_h`) | [temas](features/temas.md) |
| Limiar "tema frio" / "tema quente" | 0,5 / 5,0 (`topics.cold_threshold`, `topics.hot_threshold`) | [temas](features/temas.md) |
| Limiar de similaridade para duplicados | 0,75 (`duplicates.threshold`, MinHash; par BE/MAI mede 0,87) | [duplicados](features/duplicados.md) |
| Front-office: janela, histórias, tom, IA | 24h, ≥2 entidades e 0,5 de sobreposição, ±0,25, 50 (`front.*`) | [frontend](features/frontend.md) |
| Componentes e pesos da volatilidade | a definir | [versoes](features/versoes.md) |

Todos vivem no modelo `Parameter` (valores por omissão em `backend/core/parameters.py`), editáveis pela API (ver [backoffice](features/backoffice.md)).

## Fora de âmbito (para já)
Live blogs e notícias "ao minuto", YouTube, podcasts, vídeo puro, redes sociais, conteúdo patrocinado ou
promocional, revistas/marcas do grupo e premium sem texto integral no source code.

## Adiado
- **Legal**: RGPD (dados de pessoas visadas em processos-crime, art. 10.º), direitos de autor e retenção do texto
  integral (guardar só durante a janela de revisitas? hash + diff?).
- **Qualidade e auditabilidade**: conjunto de notícias anotadas à mão, métricas de erro, versionar o modelo e o
  prompt usados em cada análise.
- **Custos**: volume por dia × versões × chamadas ao LLM.
- **Técnica por decidir**: deploy (ver [arquitectura](features/arquitectura.md#por-fazer)). Decidido: LLM de produção = gemma4:31b
  (Ollama Cloud), extracção por parsers, Redis como broker e Postgres + pgvector.

## Ver também
- [ROADMAP](ROADMAP.md)
