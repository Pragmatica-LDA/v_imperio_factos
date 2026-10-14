# Arquitectura — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Stack técnica e organização dos processos. O projecto é **API-first** e pensado para ser **gerido por agentes**:
o CLI, o agente de gestão e o front-end React usam todos a mesma API.

## Funcionalidades

### Stack (decidido)
- **Backend**: Django.
- **Frontend**: React.
- **Tarefas e agendamento**: Celery.
- **Cache do front-office**: Redis.
- **API-first**: todas as operações são expostas na API; nada é feito só por dentro do admin ou por scripts soltos.
- **Gestão por agentes**: CLI + skill do Claude sobre a API (ver [backoffice](backoffice.md)).
- **Adicionado/alterado em**: 2026-10-13 (decisão).

### Infraestrutura Docker (dev)
- **O quê**: `docker-compose.yml` na raiz com o ambiente de desenvolvimento. Arranque: `./start_local.sh`.
  - **Dev (por omissão)**: Postgres, Redis, `migrate`, workers e beat em Docker; **backend (`runserver`) e frontend (Vite)
    correm na máquina**, com hot reload. O script cria o `.env` se faltar, prepara `backend/.venv` (uv, Python 3.13;
    reinstala quando o `requirements.txt` muda) e `frontend/node_modules` (registo npm público), exporta as variáveis
    do `.env` com os hosts trocados para `localhost` e as portas publicadas, espera pelo health e mostra os URLs.
    Ctrl+C pára o backend e o frontend; `docker compose down` pára o resto.
  - **Hot reload dos workers e do beat**: correm sob `watchfiles` (reiniciam quando muda um `.py`), com
    `WATCHFILES_FORCE_POLLING=true` porque os eventos de ficheiros não atravessam o bind mount do Docker Desktop.
  - **Tudo em Docker**: `./start_local.sh --docker` (backend e frontend no profile `docker-app`). `--no-build` não reconstrói as imagens.
- **Serviços**:

  | Serviço | Imagem / comando | Notas |
  |---|---|---|
  | `db` | `pgvector/pgvector:0.8.7-pg18-trixie` | Postgres 18 + pgvector; extensão activada pela migração `core.0001_vector_extension` |
  | `redis-broker` | `redis:8.8.3-alpine` | broker do Celery: `noeviction` + AOF, volume persistente |
  | `redis-cache` | `redis:8.8.3-alpine` | cache do front-office: `allkeys-lru`, sem persistência, `maxmemory` configurável |
  | `migrate` | `manage.py migrate` | one-shot; backend, workers e beat só arrancam depois de terminar com sucesso |
  | `backend` | `runserver` (dev) | imagem `factos-backend` (Python 3.13-slim); gunicorn é o `CMD` por omissão da imagem |
  | `worker-crawl` | `celery worker -Q discovery,crawl,revisits,maintenance` | concorrência em `CELERY_CRAWL_CONCURRENCY` |
  | `worker-analysis` | `celery worker -Q analysis,enrichment` | concorrência em `CELERY_ANALYSIS_CONCURRENCY` |
  | `beat` | `celery beat` com `DatabaseScheduler` | schedules na BD (`django-celery-beat`) |
  | `frontend` | Vite dev server (Node 24 LTS) | proxy de `/api` para o backend (mesma origem, sem CORS em dev) |

- **Portas no host** (configuráveis no `.env`, escolhidas para não colidir com outros projectos locais):
  backend `8010`, frontend `5180`, Postgres `5442`, Redis broker `6390`, Redis cache `6391`.
- **Endpoints base**: `GET /api/health/` (verifica BD, broker e cache; 503 se algum falhar), `/api/schema/` e
  `/api/docs/` (OpenAPI via drf-spectacular), `/admin/`.
- **Superuser do admin**: o serviço `migrate` corre `manage.py ensure_superuser`, que cria ou actualiza (password incluída) o user de `DJANGO_SUPERUSER_USERNAME`/`PASSWORD`/`EMAIL` do `.env`.
  Mudar o username cria um user novo (o antigo fica).
- **`.env` só é lido no arranque**: depois de o editar, correr `./start_local.sh` (recria os containers e reinicia
  o backend e o frontend na máquina); um `docker compose restart` não chega.
- **Visão geral visual** (diagrama, fluxos, papel de cada container): https://claude.ai/artifact/NrhHRLDu4maTAqjJhBjNGi
- **Configuração**: tudo por variáveis de ambiente (`django-environ`), ver `.env.example`. Timeouts e limites do
  Celery (`CELERY_VISIBILITY_TIMEOUT` 3600s, `CELERY_TASK_TIME_LIMIT` 1800s, soft 1500s, prefetch 1) são configuráveis.
- **Filas**: cada fila tem exchange e routing key próprias (sem isso o kombu ligava todas à exchange `maintenance`).
  As tarefas escolhem a fila com `@shared_task(queue="...")`; a fila por omissão é `maintenance`.
  `acks_late` + `reject_on_worker_lost`: as tarefas têm de ser idempotentes.
- **Ficheiros-chave**: `start_local.sh`, `docker-compose.yml`, `.env.example`, `backend/Dockerfile`, `backend/entrypoint.sh`,
  `backend/requirements.txt`, `backend/config/settings.py`, `backend/config/celery.py`, `backend/core/` (health,
  tarefa `ping`, comando `ensure_superuser`), `frontend/Dockerfile`, `frontend/vite.config.ts`.
- **Adicionado/alterado em**: 2026-10-13.

### Deploy no Coolify (preparado, por fazer o primeiro deploy)
- **O quê**: `docker-compose.coolify.yml` na raiz. Sem `ports`, `networks` nem `container_name`; entrada pública pelo
  `nginx` (porta 80, `coolify.expose=true`), todos os outros serviços com `coolify.expose=false`.
- **Serviços**: `nginx` (build do React + proxy de `/api`, `/admin`, `/dashboard`, `/static` para o Django;
  `docker/nginx/`), `migrate` (uma vez por deploy: migrate, ensure_superuser, bootstrap), `backend` (gunicorn,
  healthcheck em `/api/health/`), `worker-crawl`, `worker-analysis`, `beat`, `redis-broker` (AOF, noeviction),
  `redis-cache` (LRU). Volume `raw_html` partilhado em `/data/raw`.
- **Postgres**: recurso gerido do Coolify com a imagem `pgvector/pgvector:0.8.7-pg18-trixie`, ligado pelas variáveis `POSTGRES_*`.
- **Imagem do backend**: `backend/Dockerfile.coolify` (multi-stage, `collectstatic` no build, utilizador sem privilégios);
  a mesma imagem corre backend, workers, beat e migrate. Estáticos do Django servidos pelo whitenoise
  (`DJANGO_STATIC_MANIFEST=1` só na imagem de produção).
- **Settings**: `SECURE_PROXY_SSL_HEADER` (SSL termina no Traefik; nunca `SECURE_SSL_REDIRECT`), cookies seguros com
  `DJANGO_SECURE_COOKIES=1`.
- **Variáveis**: `.env.coolify.example`.
- **Testado localmente** (2026-10-14) com um Postgres temporário: stack toda saudável, SPA, login, API, admin e estáticos OK.
- **Adicionado/alterado em**: 2026-10-14.

### Apps Django (backend/)
| App | Papel |
|---|---|
| `core` | `Parameter` (todos os limiares, tempos e pesos), `Actor` + token DRF, `AuditLog`, `IdempotencyKey`, health, `manage.py bootstrap` |
| `sources` | `Site`, `EntryPoint`, `DiscoveryRun`; descoberta e seed ([fontes](fontes.md)) |
| `crawl` | `Article`, `ArticleURL`, `Fetch`, `Version`, `HomepageAppearance`, `TechnicalFailure`; fetch, ingest, revisitas ([crawl](crawl.md), [versoes](versoes.md)) |
| `parsers` | contrato comum, parsers por site e `registry.py` ([parsers](parsers.md)) |
| `analysis` | análise LLM por versão ([analise](analise.md)) |
| `entities`, `topics`, `duplicates` | resolução, temperatura e clusters ([entidades](entidades.md), [temas](temas.md), [duplicados](duplicados.md)) |
| `api` | DRF, token auth, auditoria, idempotência ([backoffice](backoffice.md)) |
| `dashboard` | `/dashboard/crawl/` (fiabilidade do crawl) |
| `benchmark` | escolha do LLM ([analise](analise.md#benchmark-de-llms)) |

- **Parâmetros e bootstrap**: `Parameter` tem os valores por omissão em `core/parameters.py`, em cache no Redis e
  editáveis pela API. `manage.py bootstrap` (corre no serviço `migrate`) cria os parâmetros em falta, os sites e
  entry points, as periodic tasks (`django-celery-beat`, na BD) e a taxonomia de temas. É idempotente.
- **Periodic tasks**: `tick_discovery` (60 s), `sweep_revisits` (5 min), `sweep_failures` (5 min), `drain_pending` da
  análise (5 min), `recompute_all` das temperaturas (15 min).
- **Providers de LLM**: `anthropic`, `openai`, `ollama` (Ollama Cloud em ollama.com com `OLLAMA_API_KEY`), reutilizados de
  `backend/benchmark/llm`, e um `fake` para os testes. Produção: `gemma4:31b` no Ollama Cloud (`llm.provider=ollama`,
  `llm.model=gemma4:31b`, `llm.params={"temperature": 0, "num_ctx": 16384}`, `llm.max_output_tokens=12000`), escolhido
  pelo utilizador a partir do benchmark. Fallback manual: `llm.provider=anthropic`, `llm.model=claude-haiku-5-5`.
- **Volumes**: `raw_html` (montado em `/data/raw`, `RAW_HTML_ROOT`) para o HTML gzip de cada fetch; `sites/out` montado para o benchmark.
- **Testes**: 111 com pytest (`docker compose run --rm --no-deps backend pytest`); fixtures em `backend/tests/fixtures/`.
- **Adicionado/alterado em**: 2026-10-13.

### Versões
| Componente | Versão | Porquê |
|---|---|---|
| Python | 3.13 | Celery 5.6 e kombu ainda só declaram suporte até 3.13 |
| Django | 6.0.9 | **não 6.1**: `django-celery-beat` 2.9.0 exige `Django<6.1`. O 6.0 tem correcções de segurança até Abril de 2027 |
| Celery | 5.6.3 | com `django-celery-beat` 2.9.0 |
| redis-py | 6.4.0 | o kombu 5.6 exige `redis<6.5` |
| DRF | 3.18.3 | + drf-spectacular 0.30.0, django-cors-headers 4.9.0, django-redis 7.0.0 |
| psycopg | 3.3.6 | + pgvector (Python) 0.5.1 |
| Postgres / pgvector | 18 / 0.8.7 | |
| Redis | 8.8.3 | |
| Node | 24 LTS | |
| React / Vite / TypeScript | 19.3 / 8.3 / 6.0 | alinhado com o template oficial `create-vite` |
| django-filter / httpx | 26.2 / 0.28.1 | API e crawl |
| anthropic / openai (SDKs) | 1.13.0 / 3.29.0 | providers de LLM |
| pytest / pytest-django / respx | 9.1.1 / 4.14.0 / 0.23.1 | testes |

- **Adicionado/alterado em**: 2026-10-13.

### Broker e filas (decidido e implementado)
- **Redis como broker do Celery, sem RabbitMQ**: chega para o volume previsto (milhares de notícias por dia mais
  revisitas) e evita um serviço extra.
- **Instância Redis do broker separada da cache**. A cache usa eviction (`allkeys-lru`); se partilhar a instância
  com o broker, o Redis pode apagar tarefas da fila sem avisar.
- **Tarefas longas** (enriquecimento de entidades com pesquisa na internet): `visibility_timeout` alto e tarefas
  idempotentes. Se as tarefas forem executadas em duplicado, reavaliar o RabbitMQ.
- **Filas separadas**: `discovery`, `crawl`, `analysis`, `enrichment`, `revisits`, `maintenance`. Cada fila tem os
  seus workers e a sua concorrência: um pico de análises LLM não bloqueia o crawl, e o crawl pode ter rate limiting
  por site.
- **`django-celery-beat`** com os schedules guardados na BD, para a cadência de descoberta ser configurável pela API.
- **Revisitas** por sweeper periódico sobre `next_revisit_at`, não por tarefas ETA (ver
  [versoes](versoes.md#revisitas-dinâmicas)).

### Base de dados (decidido e implementado)
- **Postgres + pgvector**: embeddings para o matching de temas e entidades e para a similaridade entre notícias
  ([duplicados](duplicados.md)), sem um serviço vectorial à parte.

### Dois tipos de agentes
- **Agente de gestão**: usa o CLI e a API para gerir temas, entidades, timelines e parâmetros (ver
  [backoffice](backoffice.md)).
- **Agentes do pipeline**: análise e enriquecimento; correm dentro das tarefas Celery e chamam o LLM directamente.

## Modelo de dados
Ver as outras áreas.

## Endpoints
API REST (DRF) em `/api/`, documentada em `/api/docs/`. Endpoints por área em [backoffice](backoffice.md#endpoints).

## Por fazer
- Subir para Django 6.1 quando sair um `django-celery-beat` compatível (antes de Abril de 2027).
- Primeiro deploy no Coolify: criar o recurso Postgres (pgvector), definir as variáveis e o domínio.
- Remover os scripts PoC (`crawl_*.py`) quando deixarem de ser úteis.
- Agentes de enriquecimento (fila `enrichment`) por implementar.
- `npm` local usa um Nexus privado: o `package-lock.json` do frontend foi gerado com `--registry https://registry.npmjs.org`.

## Notas e limitações
- O Django admin fica como fallback para emergências, sem investimento.
