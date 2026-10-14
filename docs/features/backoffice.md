# Backoffice — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Revisão e correcção do que os modelos do pipeline propõem: temas, entidades, timelines e parâmetros do sistema.
**A gestão principal é feita por um agente via CLI + skill**, sobre a API ([arquitectura](arquitectura.md)), e não
por um backoffice web. O Django admin fica como fallback.

## Funcionalidades

### Requisitos para gestão por agentes (implementados)
- **Tokens por actor**: cada humano e cada agente tem o seu token.
- **Auditoria** de todas as alterações: quem, quando, antes e depois. Permite ver e reverter um erro de um agente.
- **Dry-run** nas operações destrutivas (fundir/dividir temas, fundir entidades): o agente vê o impacto
  ("vai migrar 340 notícias") antes de executar.
- **Idempotência**: o agente pode repetir chamadas sem efeitos duplicados.
- **Output JSON estável** no CLI.
- **Filas de revisão consultáveis** ("o que está por rever?") para o agente trabalhar por lotes.
- **Como ficou**: tokens DRF por `Actor` (`manage.py create_actor <nome> --kind agent`, kind human|agent); todas as escritas
  geram `AuditLog`; os POST aceitam `Idempotency-Key` (`IdempotencyKey`); as fusões fazem dry-run por omissão; filas de revisão em
  `/api/entities/review-queue` e `/api/topics/review-queue`.
- **Adicionado/alterado em**: 2026-10-13 (proposta; implementado).

### Revisão de temas
- **O quê**: aprovar temas no estado por rever, fundir, dividir, mover na hierarquia, definir o tipo de recorrência.
- **Fusão**: migra automaticamente as notícias e a temperatura ([temas](temas.md#fusão-e-divisão)).
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Revisão de entidades
- **O quê**: fundir e separar entidades, corrigir público/privado, associar ou corrigir o identificador externo
  ([entidades](entidades.md)).

### Validação de timelines
- **O quê**: validar ou corrigir os factos da timeline, com os URLs de origem e a linha de debug visíveis.

### Parâmetros
- **O quê**: editar os parâmetros configuráveis (tempos de revisita, limiares, pesos), ver
  [README](../README.md#parâmetros-configuráveis-valores-iniciais). `PATCH /api/parameters/<chave>` exige `reason`, valida o tipo e
  é auditado; a cache Redis é invalidada.

### CLI e skill
- **O quê**: `cli/factos.py` (stdlib, `FACTOS_API_URL`/`FACTOS_TOKEN`, output JSON) e a skill `.claude/skills/factos/SKILL.md`
  para o agente de gestão. Token `claude-main` (agente) criado para testes.

### Dashboard de fiabilidade do crawl
- **O quê**: `/dashboard/crawl/` (staff), pedido para detectar quedas de fiabilidade (95 → 50 → 60 → 70). Por site, ao longo do
  tempo (hora/dia): `success_rate`, `quality_ok_rate` e itens descobertos por run (queda súbita = parser partido); estado
  ok/warn/alert com razões; campos de qualidade que mais falham; últimas falhas.
- **Limiares** (parâmetros): `quality.success_warn` 0,9, `quality.success_alert` 0,7, `quality.drop_alert` 0,15 face à média móvel de
  `quality.moving_avg_buckets` (6), `quality.min_bucket_fetches`; sem dados → warn.
- **API**: `/api/stats/crawl-health` alimenta o dashboard e, mais tarde, o React.
- **Ficheiros-chave**: `backend/dashboard/`, `backend/api/stats.py`.

### Admin
- **O quê**: Django admin registado nas apps como fallback.

### Fontes
- **O quê**: adicionar e editar sites e pontos de entrada ([fontes](fontes.md)).

## Modelo de dados
Usa os modelos das outras áreas. Conceptual: registo de quem fez cada correcção e quando.

## Endpoints
DRF com token auth em `/api/`; OpenAPI em `/api/docs/`. Todas as escritas são auditadas.
- Fontes: `sites`, `entrypoints` (+ `run`), `discovery-runs`.
- Crawl: `articles` (+ `versions`, `refetch`, `ingest`), `versions` (+ `analyze`), `fetches`, `failures` (+ `retry`).
- Config: `parameters` (PATCH com `reason`), `audit`.
- Entidades: `entities` (`review-queue`, `aliases`, `merge`); temas: `topics` (`review-queue`, `hot`, `editions`, `merge`).
- Análise e duplicados: `analyses`, `duplicates/clusters`.
- Estatísticas: `stats`, `stats/crawl-health`.

## Por fazer
- Rever as 620 entidades e os temas `por_rever` em lotes pelo agente (skill/CLI).
- Operações de dividir temas e separar entidades (hoje só fusão).
- Validação de timelines (dependente do enriquecimento).
- Tokens por actor existem; falta política de rotação/revogação.
- Remover os scripts PoC quando deixarem de ser úteis.

## Notas e limitações
- Uso interno.
- As fusões (`merge`) são dry-run por omissão: o agente vê o impacto e confirma explicitamente.
