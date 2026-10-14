# Duplicados — Documentação

> Estado: ⚠️ parcial  ·  Última actualização: 2026-10-13

## Visão geral
Muitas notícias são takes da Lusa ou press releases publicados quase iguais em vários meios. Sem os agrupar, o
mesmo conteúdo conta várias vezes e distorce as estatísticas.

## Funcionalidades

### Detecção por similaridade
- **O quê**: compara o conteúdo extraído entre notícias de meios diferentes.
- **Método implementado** (`duplicates/service.py`): MinHash de 128 permutações sobre shingles de 5 palavras
  (`duplicates.shingle_size`), janela de ±48 h, limiar `duplicates.threshold` = **0,75**. Baixado dos 80–85% iniciais porque o par
  BE/MAI (Observador 8365764 vs JN 18136568) mede 0,836 de Jaccard exacto e 0,867 por MinHash.
- **Adicionado/alterado em**: 2026-10-13 (conceito).

### Cluster: original e réplicas
- **Original**: a primeira publicação (`published` mais antigo). A origem é `lusa` se houver agências na assinatura; senão desconhecida.
- **Diferenças**: as diferenças textuais entre membros ficam em `Cluster.debug.differences` ("acima"/"abaixo").
- **Réplicas**: relação "derivada de" com a % de similaridade, não só sim/não. Um meio que pega no take e
  acrescenta 2 parágrafos fica abaixo do limiar, mas continua a ser derivado.

## Modelo de dados
Conceptual:
- **Cluster**: notícia original, origem identificada (Lusa, press release, desconhecida).
- **Réplica**: cluster, notícia, % de similaridade.

## Endpoints
`/api/duplicates/clusters/` (ver [backoffice](backoffice.md#endpoints)).

## Por fazer
- Validar o limiar com mais clusters reais (smoke test: 4 clusters Lusa Observador+JN).
- Original Lusa quando a assinatura é genérica ("JN/Agências"): inferir da comparação entre réplicas.
- Efeito dos duplicados na temperatura dos temas (contam uma vez ou por meio?).

## Notas e limitações
- As regras são para revisitar com dados reais.
- Ficheiros-chave: `backend/duplicates/service.py`, `backend/duplicates/tasks.py`.
- **Primeiro caso real (2026-10-13)**: o mesmo take da Lusa sobre o BE e o MAI saiu no Observador (8365764,
  assinado "Agência Lusa") e no JN (18136568, assinado "JN/Agências", sem dizer que é Lusa). Similaridade de cerca
  de 95% (leitura inicial; medida: Jaccard 0,836 / MinHash 0,867), com uma **diferença factual**: o Observador escreve "abaixo do valor previsto na lei" e o JN "acima".
  Comparar réplicas pode revelar erros e edições entre meios.
- Assinaturas genéricas ("JN/Agências") não identificam a agência: a origem Lusa tem de vir da comparação com
  outras réplicas.
