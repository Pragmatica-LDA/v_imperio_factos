---
name: factos
description: Gerir o Factos (base histórica de notícias portuguesas) através do CLI `cli/factos.py` sobre a API — rever filas de entidades e temas por lotes, fundir com dry-run, monitorizar a fiabilidade do crawl, afinar parâmetros, investigar falhas técnicas, ingerir ou reler notícias e consultar a auditoria. Usar sempre que o pedido for sobre o estado, a revisão ou a operação do Factos: "o que está por rever", "funde estas entidades", "como está o crawl", "o JN está a falhar", "muda o limiar", "temas quentes", "relê esta notícia", "quem mudou isto".
---

# Factos — gestão por agente via CLI

Toda a gestão passa pela API, com o CLI `cli/factos.py` (só stdlib). Nunca escrevas directamente na BD nem
uses o admin para o que a API faz: só a API grava auditoria (antes/depois) e respeita idempotência.

## Configuração
```bash
export FACTOS_API_URL=http://localhost:8010/api     # omissão
export FACTOS_TOKEN=...                             # manage.py create_actor <nome> --kind agent
alias factos="python3 cli/factos.py"
```
Criar o token (uma vez; o comando é o único que o mostra):
`docker compose exec backend python manage.py create_actor claude-agente --kind agent`

Saída: JSON estável no stdout. Erro: JSON no stderr (`error`, `status`, `body`) e exit code 1 — lê o `body`,
traz a validação da API. Listas são paginadas (`count`, `next`, `results`; `--limit`, `--offset`).

## Regras
1. **Dry-run antes de qualquer fusão.** `merge` é dry-run por omissão; só depois de leres o impacto
   (`mentions`, `aliases`, `cited_sources`, `sites`, `article_links`, `editions_merged`, `type_mismatch`…)
   executas com `--execute`. Se `type_mismatch` for true ou o impacto for desproporcionado, pára e pergunta.
2. **Idempotency keys em todos os POST.** Usa `--idempotency-key` determinística por operação
   (ex.: `merge-entity-12-into-7`, `refetch-345-2026-10-13`). Repetir a mesma chave devolve a mesma resposta
   sem repetir o efeito; o CLI gera um uuid se não passares nenhuma (aí uma repetição *não* é segura).
3. **Nunca mudes um parâmetro sem dizer porquê.** `params set` exige `--reason`; o motivo fica na auditoria.
   Antes, mostra o valor actual e o `default`; depois, confirma com `params get`.
4. **Factos sobre entidades não vêm do teu conhecimento de treino.** Para decidir se duas entidades são a
   mesma, usa o que a API mostra (aliases, menções, `debug`, notícias) e, se faltar, pesquisa fresca com
   URLs de origem — e regista os URLs no `--reason`.
5. **Trabalha por lotes pequenos** (10–20) e resume no fim o que fizeste, com os IDs e os `audit_id`.
6. Não faças pedidos HTTP aos sites de notícias: para reler uma notícia usa `articles refetch`.

## Fluxos

### Fila de revisão de entidades
```bash
factos entities review --limit 20            # por_rever, mais mencionadas primeiro (campo "mentions")
factos entities show 123                     # aliases, tipo, debug (porque foi criada)
factos entities list --q "costa" --type pessoa   # candidatos a duplicado
```
Para cada entidade decide uma de três:
- **Aprovar**: `factos entities update 123 '{"status": "active"}'`
- **Fundir** (é a mesma que outra): dry-run → lê o impacto → `--execute`:
  ```bash
  factos entities merge 123 --into 45 --idempotency-key merge-entity-123-into-45
  factos entities merge 123 --into 45 --execute --reason "mesmo nome e cargo; ver <URL>" \
      --idempotency-key merge-entity-123-into-45-exec
  ```
- **Corrigir**: `update` com o campo certo (`type`, `is_public`, `external_id`, `parent`) e aliases:
  `factos entities alias add 45 "A. Costa"` / `factos entities alias remove 45 <alias_id>`.
  Se o `alias add` devolver `same_alias_in` não vazio, outra entidade já tem esse alias: investiga.

### Fila de revisão de temas
```bash
factos topics review --limit 20              # por_rever, com mais notícias primeiro ("article_links")
factos topics show 88                        # inclui edições
factos topics list --q "orçamento"
factos topics merge 88 --into 12             # dry-run: article_links, editions_merged, children…
factos topics merge 88 --into 12 --execute --reason "duplicado do OE 2027" --idempotency-key merge-topic-88-12
factos topics update 88 '{"status": "active", "parent": 12, "recurrence": "anual"}'
factos api POST /topics/12/editions/ '{"label": "2027", "starts_at": "2026-10-01"}'
factos topics hot --limit 10                 # mais quentes (em cache durante cache.stats_s)
```

### Monitorizar a fiabilidade do crawl
```bash
factos health                                # por hora, últimas stats.hour_window_h horas
factos health --bucket day --since 30d
factos health --site jn
```
Lê `status` global e, por site, `status` (`ok|warn|alert`) e `reasons[].message`. Códigos:
`success_rate`/`quality_ok_rate` (abaixo de `quality.success_warn`/`quality.success_alert`),
`*_drop` (queda ≥ `quality.drop_alert` face à média móvel de `quality.moving_avg_buckets` períodos),
`discovery_failed`, `discovery_drop` (itens por execução caíram: **parser provavelmente partido**),
`no_data`. `top_quality_fields` diz que campos falham (`missing:published_at`, `body:empty`…).
O dashboard humano está em `/dashboard/crawl/` (staff).

### Investigar falhas
```bash
factos failures --status open --site jn --limit 20
factos fetches --site jn --outcome parse_error --since 2026-10-13T00:00:00Z
factos fetches --site jn --quality-ok false --limit 5    # e depois:
factos articles versions 345 2                           # conteúdo, diff e texto da versão 2
factos entrypoints runs --site jn --limit 10             # descobertas: found, erros, http_status
factos failures retry 77 --idempotency-key retry-77-2026-10-13
factos entrypoints run 5 --idempotency-key run-ep5-2026-10-13T16
```
Padrões: muitos `http_429`/`http_403` → rate limit (afinar `crawl.default_min_delay_s` ou `min_delay_s` do
site); `parse_error`/`body:empty` em massa num site → o HTML mudou e o parser tem de ser corrigido (reporta
ao humano com URLs de exemplo; não é afinável por parâmetros).

### Afinar parâmetros
```bash
factos params list --prefix quality.
factos params get revisit.min_interval_h
factos params set quality.success_warn 0.85 --reason "JN tem 10% de premium sem texto; falsos avisos"
```
O valor é JSON (`0.85`, `true`, `[60, 300]`, `"texto"`) e tem de ter o tipo do valor por omissão.

### Notícias
```bash
factos articles list --site publico --status failed --limit 20
factos articles list --entity 45 --published-after 2026-10-01T00:00:00Z
factos articles show 345                     # URLs, versões, última análise, cluster
factos articles refetch 345 --idempotency-key refetch-345-2026-10-13
factos articles ingest --url https://www.publico.pt/... --site publico --idempotency-key ingest-<hash>
factos analyses list --article 345
factos analyses run <VERSION_ID>             # põe a análise LLM na fila
factos clusters --article 345
```

### Auditoria e estatísticas
```bash
factos audit --actor claude-agente --since 2026-10-13T00:00:00Z
factos audit --object-type entities.Entity --object-id 123
factos stats
```
A auditoria guarda `before`/`after`: para reverter um erro, lê o `before` e aplica-o com `update`/`params set`
(fusões não têm undo automático — mais uma razão para o dry-run).

### Genérico
`factos api METHOD PATH [JSON]` para qualquer endpoint (ver `/api/docs/`), ex.:
`factos api PATCH /entrypoints/5/ '{"interval_s": 900}'`.
