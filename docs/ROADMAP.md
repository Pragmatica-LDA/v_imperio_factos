# Roadmap / Timeline

Registo cronológico do que foi sendo feito. Mais recente primeiro.
Cada entrada resume a sessão; o detalhe vive em `docs/features/<area>.md`.

## 2026-10-14 — Deploy no Coolify (preparado)
`docker-compose.coolify.yml` com nginx (build do React + proxy para o Django), migrate, backend gunicorn, workers, beat
e os dois Redis; Postgres como recurso gerido do Coolify (pgvector). Imagem de produção do backend com whitenoise e
`SECURE_PROXY_SSL_HEADER`. Stack testada localmente de ponta a ponta. Login do front-office corrigido (403 por CSRF com
sessão do admin aberta).
- Áreas: [arquitectura](features/arquitectura.md#deploy-no-coolify-preparado-por-fazer-o-primeiro-deploy) · [frontend](features/frontend.md)
- Commits: —

## 2026-10-13 — Front-end inicial ("o que está a acontecer")
React sobre uma API nova só de leitura (`/api/front/`): histórias das últimas 24h (notícias agrupadas por cluster ou
entidades salientes, ordenadas por actualidade, cobertura, temperatura e destaque), entidades e locais em destaque com
variação, temperatura dos temas, últimas por meio, números (tom derivado do sentimento por entidade, indicador de IA, tipo
de peça, série diária), detalhe da notícia com relacionadas do mesmo tema e de outros temas pelas mesmas entidades,
páginas de entidade e tema, arquivo com filtros e pesquisa. Login por token. Overview pré-calculado por tarefa periódica.
Parâmetros `front.*`. 10 testes novos (134 no total).
- Áreas: [frontend](features/frontend.md)
- Commits: — (sem repositório git)

## 2026-10-13 — Pipeline ligado (crawl, versões, análise LLM, duplicados, API, dashboard)
Parsers integrados no backend e pipeline de ponta a ponta em Django/Celery: descoberta por sitemaps/feeds/homepage, fetch com
regras HTTP e rate limit, versões com diff, revisitas pela temperatura, análise LLM (smoke test com Haiku 5.5; produção passa a gemma4:31b no Ollama Cloud), resolução de entidades e temas,
duplicados (MinHash), API REST, CLI + skill e dashboard de fiabilidade do crawl. Smoke test real: 112 artigos, 112/112 HTTP ok, 99 analisados. 111 testes.
- Áreas: [arquitectura](features/arquitectura.md) · [fontes](features/fontes.md) · [crawl](features/crawl.md) · [parsers](features/parsers.md) · [versoes](features/versoes.md) · [analise](features/analise.md) · [entidades](features/entidades.md) · [temas](features/temas.md) · [duplicados](features/duplicados.md) · [backoffice](features/backoffice.md) · [frontend](features/frontend.md)
- Commits: — (sem repositório git)

## 2026-10-13 — Benchmark de LLMs para a análise
App `benchmark` com baseline de referência (Claude Opus 5.5 via Claude Code, 29 artigos), providers Anthropic,
OpenAI e Ollama Cloud com output estruturado, scoring configurável contra a baseline e relatório com score,
latência e custo. Primeiro run: Ollama deepseek-v4.1-flash (0,867) e gemma4:31b (0,851, 4,8 s) à frente de
Sonnet 5.5 (0,831), GPT-5.4 mini (0,819) e Haiku 5.5 (0,79/0,75). O Ollama Cloud não aplica o schema e o
Sonnet/Haiku 5.5 devolvem às vezes respostas vazias: ambos resolvidos com validação e reparação.
- Áreas: [analise](features/analise.md#benchmark-de-llms)
- Commits: — (sem repositório git)

## 2026-10-13 — Infraestrutura Docker
Ambiente de desenvolvimento em Docker Compose: Postgres + pgvector, Redis broker e Redis cache separados, backend
Django 6.0, dois workers Celery por grupo de filas, beat com schedules na BD e frontend React + Vite. Arranque com `./start_local.sh` e superuser do admin gerido pelo
`.env`. Django 6.1 fica de fora até o `django-celery-beat` o suportar.
- Visão geral da infraestrutura (página HTML): https://claude.ai/artifact/NrhHRLDu4maTAqjJhBjNGi
- Áreas: [arquitectura](features/arquitectura.md)
- Commits: — (sem repositório git)

## 2026-10-13 — PoC de parsers (Observador, JN, Público)
Parsers para homepage, sitemap/feed e artigo com contrato comum (v2.1), feitos por 3 agentes em paralelo. Primeiro
crawl real às homepages e a 2 artigos por site. Decididas as regras de âmbito, premium, fotógrafos e estratégia de descoberta.
- Observador: texto premium integral no HTML, descoberta por `wp-sitemap`, limpeza do corpo e datas de peças agendadas validadas no crawl real ([observador](sites/observador.md)).
- JN: extracção pelo payload RSC do Next.js, news sitemap (48h) + sitemaps diários desde 2004, premium detectado na homepage e excluído (corpo cortado pelo paywall), crédito fotográfico do RSC ([jn](sites/jn.md)).
- Público: HTML + JSON-LD + `publicoConfig`, zonas da homepage e exclusões auditáveis (podcasts com URL de notícia, promoções, Estúdio P), premium só detectável no artigo e excluído, crédito fotográfico do HTML. O robots.txt bloqueia o Claude Code: o crawl é corrido pelo utilizador e os sitemaps ficam por validar ([publico](sites/publico.md)).
- Áreas: [parsers](features/parsers.md) · [crawl](features/crawl.md) · [fontes](features/fontes.md) · [duplicados](features/duplicados.md) · [entidades](features/entidades.md)
- Commits: — (sem repositório git)

## 2026-10-13 — Arquitectura técnica (decisões iniciais)
Stack definida (Django, React, Celery, Redis), API-first e gestão por agentes via CLI + skill. Propostas por
confirmar: Redis como broker sem RabbitMQ, filas separadas, revisitas por sweeper, Postgres + pgvector.
- Áreas: [arquitectura](features/arquitectura.md) · [crawl](features/crawl.md) · [versoes](features/versoes.md) · [backoffice](features/backoffice.md) · [frontend](features/frontend.md)
- Commits: — (sem repositório git)

## 2026-10-13 — Definição do conceito
Conceito do produto fechado em três rondas de análise de gaps: âmbito, entidades e timelines, temas com edições
e temperatura, revisitas e versionamento, duplicados, análise por entidade. Fase técnica por iniciar.
- Áreas: [fontes](features/fontes.md) · [crawl](features/crawl.md) · [versoes](features/versoes.md) · [temas](features/temas.md) · [entidades](features/entidades.md) · [analise](features/analise.md) · [duplicados](features/duplicados.md) · [backoffice](features/backoffice.md) · [frontend](features/frontend.md)
- Commits: — (sem repositório git)
