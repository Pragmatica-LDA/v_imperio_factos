# Entidades — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Tudo o que pode ser referenciado numa notícia: pessoas, partidos, governo, tribunais, PSP, empresas (ex.: Sony),
União Europeia, Conselho Europeu, meios de comunicação, locais. Cada entidade liga-se às notícias através de
papéis e, se for pública, tem uma timeline própria enriquecida por um agente com acesso à internet.

## Funcionalidades

### Papel na notícia
- **O quê**: o papel é uma **relação** notícia↔entidade, não um tipo de entidade: autor (jornalista), visado,
  citado, acusado, fonte… A mesma entidade pode ter vários papéis na mesma notícia.
- **Cargo à data**: a relação guarda o cargo que a entidade tinha na data da notícia (ex.: ministro em 2024,
  deputado em 2026).
- **Sentimento**: cada relação tem o sentimento da notícia em relação a essa entidade ([analise](analise.md)).
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Resolução de entidades
- **O quê**: "Costa", "António Costa" e "o presidente do Conselho Europeu" podem ser a mesma entidade. Há homónimos.
- **Implementado** (`entities/resolve.py`, por alias normalizado): um só candidato → liga; ambíguo → nova entidade `por_rever`
  com os candidatos no debug; nenhum → nova `por_rever`; meios → `Site.entity`. Sem pesquisa externa nem embeddings.
- **Identificador externo**: a entidade liga-se a um identificador externo (ex.: Wikidata QID). O enriquecimento
  só é feito a partir dele; sem identificador, fica **por rever**.

### Timeline da entidade
- **O quê**: o "LinkedIn" da entidade: o que foi e quando (ex.: presidente da Câmara de Lisboa, deputado,
  primeiro-ministro, presidente do Conselho Europeu), incluindo eventos e casos ([temas](temas.md)).
- **Como funciona**: processo paralelo, numa fila própria. Um agente **com acesso à internet** pesquisa e preenche
  a timeline. **Nunca usa o conhecimento de treino do modelo.** Complementa com o que as próprias notícias trazem.
- **Cada facto guarda**: URLs de origem e uma linha de debug (porque decidiu, fontes usadas e descartadas).
- **Validação humana** no [backoffice](backoffice.md).

### Figura pública vs pessoa privada
- **O quê**: só as entidades públicas são enriquecidas. Uma pessoa privada (ex.: "suspeito de 34 anos detido em
  Setúbal") fica só ligada à notícia, sem perfil.
- **Quem decide**: o modelo propõe, o backoffice corrige. O estado pode mudar ao longo do tempo.

### Fusão e separação
- **O quê**: corrigir à mão entidades juntas por engano (dois homónimos) ou separadas por engano (o mesmo partido
  duas vezes), via [backoffice](backoffice.md).

### Localização geográfica
- **O quê**: locais normalizados com hierarquia freguesia > concelho > distrito. Permite análises como "crimes em
  Lisboa vs Porto".

## Modelo de dados
Conceptual:
- **Entidade**: nome canónico, aliases, tipo (pessoa, organização, partido, instituição, meio, local…),
  público/privado, identificador externo, estado.
- **Notícia↔Entidade**: versão, papel(éis), cargo à data, sentimento, debug.
- **Facto da timeline**: entidade, cargo/evento, início, fim, URLs de origem, debug, estado de validação.
- **Local**: hierarquia geográfica (freguesia, concelho, distrito).

## Endpoints
`/api/entities/`, `/api/entities/review-queue`, `/api/entities/<id>/aliases`, `/api/entities/merge` (dry-run por omissão). Ver [backoffice](backoffice.md#endpoints).

### Fotógrafos e assinaturas colectivas
- **O quê**: os fotógrafos são registados a partir do crédito das imagens (ex.: "ESTELA SILVA/LUSA",
  "Foto: Pedro Granadeiro"), com a agência ou o banco de imagens. As assinaturas colectivas ("JN/Agências",
  "Redação", "Agência Lusa") são aceites como autores. Ver [parsers](parsers.md#campos-extraídos).
- **Adicionado/alterado em**: 2026-10-13 (decisão do utilizador).

## Por fazer
- Rever as 620 entidades `por_rever` do smoke test (623 no total, 910 menções), em lotes pela skill/CLI.
- Timelines e enriquecimento (agente com internet) por implementar; entidades públicas/privadas ainda sem perfil.
- Escolher as fontes externas de referência (Wikidata, Wikipedia, parlamento.pt, base.gov…).
- Regra de conflito quando duas fontes se contradizem.
- Resolução para além do alias exacto (embeddings, contexto, homónimos).
- Prompt: o Haiku expandiu "SIRESP" para um nome completo que não está no texto (conhecimento de treino); afinar para só factos do texto.
- Fonte de dados geográficos (lista oficial de freguesias, concelhos e distritos).

## Notas e limitações
- Pessoas privadas em processos-crime têm implicações RGPD (art. 10.º); fica para a fase legal
  (ver [README](../README.md#adiado)).
