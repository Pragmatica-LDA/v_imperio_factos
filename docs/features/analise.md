# Análise da notícia — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Corre em cada versão de cada notícia e produz a catalogação estruturada: entidades e papéis, sentimento por
entidade, fontes citadas, temas e edições, tipo de peça, localização e um indicador de escrita por IA.

## Funcionalidades

### Sentimento por entidade
- **O quê**: positivo, negativo ou neutro **em relação a cada entidade**, não à notícia em geral. Uma notícia pode
  ser neutra no geral e muito negativa para a entidade X.
- **Onde fica**: na relação notícia↔entidade ([entidades](entidades.md)).
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Fontes da notícia
- **Tipologia inicial**: anónima, oficial, documento (PDF oficial, comunicado da Presidência…), agência, redes
  sociais, especialista, outro meio. A lista pode crescer.
- **Fontes anónimas**: guardam o atributo parcial ("fonte próxima do Governo", "fonte do PS").
- **Outro meio**: se o meio já existe como entidade, liga-se directamente.

### Tipo de peça
- **O quê**: notícia, opinião, entrevista, análise, editorial.
- **Porquê**: num artigo de opinião o sentimento é intencional (o autor tem um viés assumido) e não deve
  contaminar as estatísticas de notícias.

### Temas, edições e localização
- Ver [temas](temas.md) e [entidades](entidades.md#localização-geográfica).

### Detecção de escrita por IA
- **O quê**: um **indicador** (percentagem de confiança), nunca um facto.
- **Como funciona**: a arquitectura suporta **vários detectores**, guarda o resultado de cada um e permite
  compará-los. O algoritmo é para ir afinando.
- **Hipótese**: comparar com o histórico de estilo do próprio jornalista (mudança súbita = sinal mais forte).

### Linha de debug
- **O quê**: cada decisão guarda o raciocínio do modelo, as fontes usadas e as fontes descartadas. Serve para
  perceber e corrigir resultados estranhos.

## Pipeline de análise (implementado)
- **O quê**: app `backend/analysis/`, uma chamada ao LLM por `Version`, com o `SYSTEM_PROMPT_V1` e o schema v1 do benchmark
  (`PROMPT_VERSION = "prod-v1+bench-v1"`). Os temas candidatos são os da BD, os mais quentes primeiro.
- **Modelo**: `gemma4:31b` no Ollama Cloud (`llm.provider=ollama`, `llm.model=gemma4:31b`,
  `llm.params={"temperature": 0, "num_ctx": 16384}`, `llm.max_output_tokens=12000`: 4096 truncava 10/109 respostas).
  Escolhido pelo utilizador pelo melhor equilíbrio score/latência do benchmark (antes: Haiku 5.5, usado no smoke test).
  Teste real: 5,6 s, 3,9k tokens de entrada, válido à 1.ª. Trocar de modelo é só mudar os parâmetros `llm.*`.
  Providers anthropic/openai/ollama em `benchmark/llm`; o `fake` (testes) em `analysis/llm.py`.
- **Validação**: `jsonschema`; respostas vazias (`analysis.min_words_expect_entities`) são detectadas e reparadas (`analysis.repair_attempts`).
- **Orçamento**: `analysis.daily_limit` (500) por dia; o excedente fica `skipped_budget` e `drain_pending` (5 min) retoma.
- **Pós-análise**: `diff_from_previous` face à análise da versão anterior ([versoes](versoes.md)); `CitedSource`; resolução de
  [entidades](entidades.md) e [temas](temas.md); recálculo da cadência de revisita; entrada nos [duplicados](duplicados.md).
- **Smoke test** (112 artigos): 99 analisados, 10 falhados por truncagem (corrigido), ~6,6 s e ~6k tokens de entrada / ~1,4k de saída por
  artigo, 0 reparações, 910 menções de entidades, 304 fontes citadas.
- **Ficheiros-chave**: `backend/analysis/service.py`, `llm.py`, `prompts.py`, `tasks.py`.
- **Adicionado/alterado em**: 2026-10-13.

## Benchmark de LLMs
- **O quê**: app `backend/benchmark/` para escolher o modelo da análise. Uma **baseline** (análise de referência
  feita pelo Claude Opus 5.5 no Claude Code, com o mesmo prompt e schema) serve de padrão; cada modelo candidato
  analisa os mesmos artigos e é pontuado contra ela, com latência, tokens e custo.
- **Amostra**: 29 artigos dos parsers da PoC (`sites/out`, montado em `/data/sites_out`): Observador, JN e Público;
  notícia, opinião, análise, entrevista; takes Lusa e duplicados entre meios. Premium sem texto e corpos incompletos ficam de fora.
- **Prompt v1** (`benchmark/bench/prompt.py`, guardado em `PromptVersion`): tipo de peça, entidades (nome canónico,
  tipo, público/privado, papéis, cargo à data, sentimento por entidade + justificação), fontes (tipologia, atributo
  parcial, excerto), temas (taxonomia-semente em `fixtures/themes_seed.json`, temas novos com `is_new`, edição, peso),
  locais, indicador de IA e linha de debug. Só factos do texto. A assinatura não é fonte.
- **Schema** (`bench/schema.py`) compatível com os três providers: tudo em `required`, `additionalProperties: false`,
  nulos via `anyOf`, intervalos validados à parte.
- **Providers** (`benchmark/llm/`, interface `get_provider(config).analyse(system, user, schema) -> LLMResult`, também
  usada pelo pipeline): Anthropic (structured outputs, system prompt em cache), OpenAI (Responses API, `strict`,
  `base_url` explícito), Ollama (Cloud em ollama.com ou servidor próprio, `Authorization: Bearer OLLAMA_API_KEY`).
- **Reparação**: uma resposta inválida ou vazia é repetida com os erros (`params.repair_attempts`, 2 em todos os
  modelos); latência, tokens e custo somam as tentativas e o relatório mostra a taxa de válidos à 1.ª.
- **Scoring** (`bench/scoring.py`, pesos e limiares em `ScoringConfig`): tipo de peça exacto; entidades por nome
  normalizado + fuzzy (`rapidfuzz`, limiar 85) → F1, e nas emparelhadas tipo, público, papéis (Jaccard) e
  sentimento (neutro vs polar = 0,5; polaridade invertida = 0); fontes por tipo + entidade/excerto e por
  distribuição de tipos; temas por prefixo do caminho na hierarquia; edição; locais F1; indicador IA por erro absoluto.
  Total = média ponderada. Testes em `benchmark/tests/test_scoring.py`.
- **Comandos**:
  ```
  manage.py bench_import_articles [pastas]          # amostra a partir dos JSON dos parsers
  manage.py bench_seed [--update]                    # prompt v1, scoring, modelos Anthropic/OpenAI
  manage.py bench_models --list | --list-ollama | --add-ollama <modelo…|all>
  manage.py bench_export_prompts <pasta>             # pedidos exactos, para produzir uma baseline à mão
  manage.py bench_import_baseline <pasta> --label L  # baseline manual (um <site>_<id>.json por artigo)
  manage.py bench_run --baseline L --models a,b [--repeat N] [--articles k1,k2]
  manage.py bench_run --resume RUN --models a,b      # completa um run (pares em falta)
  manage.py bench_run --as-baseline L --models opus-5-5   # nova baseline via API
  manage.py bench_report [RUN] [--out f.md] [--recompute]
  ```
  API só de leitura em `/api/benchmark/` (articles, models, runs, results).
- **Baseline actual**: `opus-5.5-cc-2026-10-13` (`benchmark/fixtures/baselines/`).
- **Adicionado/alterado em**: 2026-10-13.

### Resultados do run 2 (2026-10-13, 29 artigos, prompt v1)
Relatório completo: `backend/benchmark/reports/run2.md`.

| modelo | score | válidos à 1.ª | p50 | $/1000 artigos |
|---|---|---|---|---|
| Ollama deepseek-v4.1-flash | 0,867 | 100% | 11,2 s | subscrição |
| Ollama gemma4:31b | 0,851 | 100% | 4,8 s | subscrição |
| Claude Sonnet 5.5 (effort low) | 0,831 | 69% | 11,3 s | 32,62 |
| Ollama glm-5.3-flash | 0,824 | 97% | 49,8 s | subscrição |
| GPT-5.4 mini (reasoning low) | 0,819 | 100% | 7,0 s | 8,27 |
| Claude Haiku 5.5 (effort medium) | 0,791 | 83% | 8,9 s | 2,03 |
| GPT-5.4 nano (reasoning low) | 0,753 | 100% | 10,2 s | 2,63 |
| Claude Haiku 5.5 (effort low) | 0,745 | 93% | 6,8 s | 1,39 |

- Os pontos fracos comuns são temas (nomes diferentes para casos novos), papéis e fontes. O sentimento por
  entidade fica entre 0,90 e 0,96 em todos.
- Ficaram por correr no Ollama: gpt-oss 20b/120b, nemotron-3-nano e kimi-k2.6 (o mais lento, ~170 s por artigo).
- **Decisão** (utilizador, 2026-10-13): `gemma4:31b` no Ollama Cloud em produção (ver [pipeline](#pipeline-de-análise-implementado)).
- **Acoplamento**: o pipeline usa o prompt e o schema do benchmark (`analysis/prompts.py` importa
  `benchmark.bench.prompt`, versão `prod-v1+bench-v1`). Uma mudança ao prompt é uma versão nova (`PromptVersion` v2 +
  `PROMPT_VERSION`) e deve passar primeiro pelo benchmark contra a mesma baseline.

## Modelo de dados
Conceptual:
- **Análise**: versão, tipo de peça, modelo e prompt usados, debug.
- **Fonte citada**: análise, tipo, atributo parcial, entidade ligada (opcional), excerto.
- **Resultado de detector IA**: análise, detector, percentagem, debug.

## Endpoints
`/api/analyses/`, `POST /api/versions/<id>/analyze`. Ver [backoffice](backoffice.md#endpoints).

## Por fazer
- Modelo de produção decidido (2026-10-13): `gemma4:31b` no Ollama Cloud — score 0,851, p50 4,8 s, 29/29 válidas à 1.ª no
  [benchmark](#benchmark-de-llms), sem custo por token. Por fazer: confirmar os limites do plano Ollama Cloud para o volume
  diário, decidir um fallback automático para Haiku 5.5 e rever à mão ~20 análises reais.
- As 99 análises do smoke test são do Haiku 5.5; reanalisar com o gemma4:31b se se quiser a base homogénea.
- Prompt: o Haiku expandiu "SIRESP" para um nome completo que não está no texto (conhecimento de treino); afinar.
- Detecção de IA e embeddings por implementar.
- Benchmark: correr os modelos Ollama em falta, `--repeat 3` para medir a variância, rever à mão as divergências nos temas.
- Escolher os detectores de IA iniciais.
- Versionar o modelo e o prompt de cada análise: já se guarda `PROMPT_VERSION`; falta a fase de qualidade (ver [README](../README.md#adiado)).
- Conjunto de notícias anotadas à mão para validar.

## Notas e limitações
- Os detectores de IA são pouco fiáveis em texto jornalístico curto e editado: indicador, não veredicto.
- Os atributos das fontes anónimas são para revisitar com casos reais.
- **Ollama Cloud ignora `format`/`json_schema`** (sem constrained decoding): o schema vai no prompt e a resposta é
  validada e reparada.
- **Claude Sonnet 5.5 e Haiku 5.5**: com este prompt, a salvaguarda `reasoning_extraction` recusava (Sonnet) quando o
  debug pedia "o raciocínio"; passou a "justificação curta". Mesmo assim, ~30% (Sonnet) e ~10–17% (Haiku) das
  respostas vêm como um stub vazio válido no schema (`reasoning: "x"`, listas vazias): tratados como inválidos e repetidos.
- O `OPENAI_BASE_URL` do `.env` aponta para o Ollama: o provider OpenAI do benchmark usa sempre o `base_url` da ModelConfig.
