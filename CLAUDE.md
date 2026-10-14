# Factos — Instruções para o Claude

## Antes de planear ou implementar
1. Lê `docs/README.md` (visão, princípios, parâmetros, estado das áreas).
2. Lê o `docs/features/<area>.md` da área em que vais trabalhar.
3. Consulta `docs/ROADMAP.md` para saber o que já foi feito.

## Áreas
- [arquitectura](docs/features/arquitectura.md): stack, broker e filas, API-first, agentes
- [fontes](docs/features/fontes.md): sites, secções, RSS e sitemaps
- [crawl](docs/features/crawl.md): descoberta, fila, extracção do artigo
- [parsers](docs/features/parsers.md): contrato comum, parsers por site, scripts PoC (notas por site em docs/sites/)
- [versoes](docs/features/versoes.md): revisitas, versões, HTTP, volatilidade
- [temas](docs/features/temas.md): temas, hierarquia, edições, temperatura
- [entidades](docs/features/entidades.md): entidades, papéis, timeline, localização
- [analise](docs/features/analise.md): sentimento, fontes da notícia, tipo de peça, detecção IA
- [duplicados](docs/features/duplicados.md): clusters, original e réplicas
- [backoffice](docs/features/backoffice.md): revisão humana e parâmetros
- [frontend](docs/features/frontend.md): estatísticas, temas quentes, pesquisa histórica

## Regras do projecto
- Português de Portugal; termos técnicos em inglês quando apropriado.
- **Tudo o que é limiar, tempo ou peso é configurável**, nunca hardcoded.
- **Cada decisão de um modelo guarda uma linha de debug** com o raciocínio, as fontes usadas e as fontes descartadas.
- Os modelos nunca usam conhecimento de treino para factos sobre entidades: usam pesquisa fresca com URLs de origem.
- Depois de uma sessão de desenvolvimento, actualiza os docs (skill `document-progress`).
