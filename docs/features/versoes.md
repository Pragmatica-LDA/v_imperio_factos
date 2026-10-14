# Versões e revisitas — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Cada notícia é relida várias vezes enquanto o tema estiver quente. Cada leitura com conteúdo diferente cria uma
nova versão (v1, v2, v3…), com o diff de texto **e** o diff da análise. Daqui saem o nº de edições, a % de
alteração, as notícias apagadas e a volatilidade.

## Funcionalidades

### Revisitas dinâmicas
- **O quê**: a cadência de releitura depende da temperatura do tema ([temas](temas.md)).
- **Como funciona**:
  - Tema quente → intervalo **mínimo** (inicial: 2h).
  - Tema a arrefecer → intervalos crescentes até ao **máximo** (inicial: 12h).
  - Tema frio → as revisitas param.
  - **Revisita tardia** (inicial: 7 dias) para detectar correcções e apagamentos posteriores.
  - Notícia com vários temas → **manda o tema mais quente**.
  - Notícias de última hora sem tema conhecido → **cadência própria**.
- **Agendamento (implementado)**: cada notícia guarda `next_revisit_at` na BD; `sweep_revisits` (cada 5 min, `select_for_update(skip_locked)`) vai buscar as notícias vencidas e põe-nas na fila `revisits`. Não se usam tarefas Celery com
  ETA/countdown, porque no Redis ficam na memória dos workers, podem perder-se ou duplicar-se e não reagem a mudanças
  de parâmetros. Com o sweeper, mudar um parâmetro tem efeito imediato.
- **Configuração**: todos os tempos são parâmetros (ver [README](../README.md#parâmetros-configuráveis-valores-iniciais)).
- **Fórmula** (`crawl/scheduling.py`, função pura):
  - temperatura ≥ `topics.hot_threshold` (5,0) → `revisit.min_interval_h` (2 h);
  - a arrefecer → interpolação linear até `revisit.max_interval_h` (12 h);
  - < `topics.cold_threshold` (0,5) → pára;
  - sem tema → `revisit.no_topic_interval_h` (6 h) até `revisit.no_topic_max_age_h` (48 h);
  - sempre uma revisita tardia em `published + revisit.late_days` (7 d), marcada em `late_revisit_done`.
- **Gatilhos**: o cadence é recalculado depois de cada análise (tema mais quente da notícia) e quando o `lastmod` do sitemap
  muda (Observador, `revisit.on_lastmod_change`: revisita já).
- **Smoke test**: revisitas a seguir a temperatura (2 h em temas quentes, até 5,8 h a arrefecer).
- **Ficheiros-chave**: `backend/crawl/scheduling.py`, `backend/crawl/tasks.py`, `backend/crawl/ingest.py`.
- **Adicionado/alterado em**: 2026-10-13 (conceito; implementado).

### Respostas HTTP nas revisitas

| Resposta | Tratamento |
|---|---|
| `200` | Leitura normal; nova versão se o conteúdo extraído mudou |
| `404` / `410` | Notícia **apagada**, registada como dado (não é erro) |
| `301` para a homepage/secção | Notícia **apagada** |
| `301` para outro artigo | Novo URL associado à mesma notícia |
| `302` / `307` (temporário) | Segue o redirect, mas mantém o URL original como referência |
| Timeouts, 5xx, 403/429, bloqueios | Falha técnica, processo à parte (ver [crawl](crawl.md#falhas-técnicas)) |

### Versões
- **O quê**: v1 é a primeira leitura; cada leitura com o conteúdo extraído diferente gera vn+1.
- **Implementação** (`crawl/versioning.py`): `content_hash` sobre título, lead, corpo, autores e tags; só há `Version` nova se mudar.
  A `Version` guarda `content` (`Article.to_dict`), `text`, `change_ratio`, `diff` por blocos (difflib) e `minhash` (usado nos [duplicados](duplicados.md)).
- **Atributos da notícia**: `version_count`, `change_ratio_total`, estado (`active`, `deleted`, `out_of_scope`, `failed`).
- **% de alteração**: pequena para uma gralha (poucos caracteres), maior para um parágrafo novo, um título mudado
  ou reordenação.

### Análise por versão
- **O quê**: cada versão é **reanalisada por completo** ([analise](analise.md)); o custo é irrelevante (cêntimos).
- **Diff da análise** (implementado em `analysis/service.py`, `diff_from_previous`): compara entidades, sentimento por entidade, temas e fontes com a análise da versão anterior. Exemplo: o
  sentimento sobre a entidade X passa de negativo na v1 para neutro na v2, um sinal editorial forte.

### Volatilidade
- **O quê**: métrica por notícia com duas componentes configuráveis:
  - **Texto**: % de alterações entre versões.
  - **Análise**: mudanças de sentimento por entidade e entidades, temas ou fontes que entram ou saem.
- **Fórmula**: a definir, configurável.

## Modelo de dados
Conceptual:
- **Versão**: notícia, nº, leitura de origem, conteúdo extraído, % de alteração face à anterior.
- **Análise**: versão, resultados ([analise](analise.md)), modelo e prompt usados, debug.
- **Diff de análise**: versão anterior, versão nova, alterações por dimensão.
- **Agendamento**: notícia, próxima revisita, tema que determinou a cadência.

## Endpoints
`/api/articles/<id>/versions`, `/api/articles/<id>/refetch`, `/api/versions/` (+ `analyze`). Ver [backoffice](backoffice.md#endpoints).

## Por fazer
- Fórmula da volatilidade (texto + análise), configurável.
- Afinar a cadência com dados reais (parâmetros `revisit.*`).
- Classificar o tipo de edição (cosmética, título, substantiva, correcção)? Por decidir.

## Notas e limitações
- Live blogs e "ao minuto" estão fora de âmbito.
- O diff usa só o conteúdo extraído, nunca o HTML completo.
