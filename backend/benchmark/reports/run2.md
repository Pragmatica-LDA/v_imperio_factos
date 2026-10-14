# Benchmark 2 · baseline `opus-5.5-cc-2026-10-13` · prompt analise v1

29 artigos · repetições: 1 · scoring `default-v1` · estado: done · 2026-10-13 15:27

## Resumo

| modelo | score | mín | válidos | à 1.ª | p50 | p95 | tok/s | tok in/out | $/artigo | $/1000 | Pareto |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama-deepseek-v4-1-flash | 0.867 | 0.703 | 100% | 100% | 11.2s | 22.0s | 277 | 4061/3588 | 0.00000 | 0.00 | ★ |
| ollama-gemma4-31b | 0.851 | 0.703 | 100% | 100% | 4.8s | 9.8s | 255 | 3675/1359 | 0.00000 | 0.00 | ★ |
| sonnet-5-5-low | 0.831 | 0.000 | 97% | 69% | 11.3s | 17.5s | 131 | 8907/1481 | 0.03262 | 32.62 |  |
| ollama-glm-5-3-flash | 0.824 | 0.000 | 97% | 97% | 49.8s | 102.4s | 159 | 3927/9260 | 0.00000 | 0.00 |  |
| gpt-5-4-mini | 0.819 | 0.697 | 100% | 100% | 7.0s | 11.5s | 177 | 3129/1316 | 0.00827 | 8.27 |  |
| haiku-5-5-medium | 0.791 | 0.603 | 100% | 83% | 8.9s | 23.8s | 206 | 7606/2535 | 0.00203 | 2.03 |  |
| gpt-5-4-nano | 0.753 | 0.579 | 100% | 100% | 10.2s | 17.8s | 149 | 3129/1604 | 0.00263 | 2.63 |  |
| haiku-5-5-low | 0.745 | 0.600 | 100% | 93% | 6.8s | 11.4s | 188 | 7213/1334 | 0.00139 | 1.39 |  |

## Score por métrica (0–1, vs baseline)

| modelo | tipo | entid. | tipo ent. | púb. | papéis | sentim. | fontes | tipos fonte | temas | edição | locais | IA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama-deepseek-v4-1-flash | 1.00 | 0.94 | 0.97 | 1.00 | 0.78 | 0.95 | 0.69 | 0.69 | 0.80 | 0.90 | 0.82 | 0.97 |
| ollama-gemma4-31b | 1.00 | 0.97 | 0.95 | 0.99 | 0.77 | 0.94 | 0.67 | 0.70 | 0.72 | 0.90 | 0.74 | 0.95 |
| sonnet-5-5-low | 0.93 | 0.88 | 0.95 | 0.96 | 0.73 | 0.92 | 0.70 | 0.73 | 0.76 | 0.70 | 0.77 | 0.95 |
| ollama-glm-5-3-flash | 0.97 | 0.89 | 0.87 | 0.95 | 0.70 | 0.93 | 0.63 | 0.67 | 0.74 | 0.75 | 0.82 | 0.96 |
| gpt-5-4-mini | 0.97 | 0.89 | 0.96 | 0.99 | 0.69 | 0.91 | 0.58 | 0.63 | 0.73 | 0.40 | 0.86 | 0.97 |
| haiku-5-5-medium | 0.93 | 0.86 | 0.99 | 0.96 | 0.74 | 0.94 | 0.64 | 0.67 | 0.58 | 0.75 | 0.64 | 0.99 |
| gpt-5-4-nano | 1.00 | 0.85 | 0.92 | 0.97 | 0.55 | 0.90 | 0.52 | 0.53 | 0.63 | 0.50 | 0.66 | 0.91 |
| haiku-5-5-low | 0.90 | 0.77 | 0.98 | 0.96 | 0.73 | 0.96 | 0.67 | 0.70 | 0.43 | 0.75 | 0.48 | 0.99 |

## Piores artigos por modelo (top 5)

**ollama-deepseek-v4-1-flash**
- jn_18135667 · 0.703 · a mais: Aliança Democrática, União Europeia, Assembleia da República, Jorge Palma
- observador_8363879 · 0.710 · —
- jn_18136490 · 0.726 · a mais: Agência para a Integração, Migrações e Asilo, Unidade de Estrangeiros e Fronteiras
- observador_8365425 · 0.733 · faltam: Polícia de Segurança Pública; a mais: Governo PSD/CDS, Partido Social Democrata
- observador_8365113 · 0.792 · a mais: Observador

**ollama-gemma4-31b**
- jn_18135667 · 0.703 · faltam: Pedro Santana Lopes; a mais: Jorge Palma, União Europeia
- jn_18136490 · 0.705 · —
- publico_2191197 · 0.724 · faltam: Horizonte Europa
- observador_8363521 · 0.751 · faltam: Ministério da Administração Interna; a mais: Tribunal de Contas, Ministério Público
- jn_18136260 · 0.759 · —

**sonnet-5-5-low**
- observador_8365329 · 0.000 · erro: resposta degenerada: sem entidades nem temas num artigo com texto
- jn_18136491 · 0.661 · —
- jn_18135667 · 0.708 · faltam: Pedro Santana Lopes, Fundo Monetário Internacional
- jn_18136463 · 0.712 · faltam: Joaquim Cunha, Governo de Portugal
- publico_2191197 · 0.760 · faltam: Parlamento Europeu, Conselho Europeu, Horizonte Europa, Conny Aerts, Maria Chiara Carrozza; a mais: PÚBLICO

**ollama-glm-5-3-flash**
- jn_18136490 · 0.000 · erro: resposta truncada (done_reason=length): 
- observador_8363879 · 0.698 · a mais: jovens manifestantes em França, jovens eleitores portugueses, União Europeia
- jn_18136260 · 0.753 · a mais: TikTok, Instagram
- observador_8365425 · 0.758 · faltam: Polícia de Segurança Pública
- jn_18135667 · 0.783 · a mais: Aliança Democrática, União Europeia, Jorge Palma, PRR, Assembleia da República

**gpt-5-4-mini**
- jn_18135667 · 0.697 · faltam: Marcelo Rebelo de Sousa, José Sócrates, Mário Soares, Ramalho Eanes, Jorge Sampaio; a mais: Jorge Palma, Assembleia da República
- observador_8363521 · 0.713 · faltam: Ministério da Administração Interna, Guarda Nacional Republicana; a mais: Sistema Integrado de Redes de Emergência e Segurança de Portugal, Tribunal de Contas, Ministério Público
- jn_18136490 · 0.717 · a mais: Agência para a Integração, Migrações e Asilo, Polícia de Segurança Pública
- jn_18136491 · 0.730 · faltam: Governo de Portugal, Partido Social Democrata, Agência Lusa
- publico_2191168 · 0.744 · faltam: Chega, Partido Socialista

**haiku-5-5-medium**
- publico_2191197 · 0.603 · faltam: Conselho da União Europeia, Mario Draghi, Horizonte Europa, Conny Aerts, Maria Chiara Carrozza; a mais: PÚBLICO
- jn_18135667 · 0.616 · faltam: Partido Socialista, Partido Social Democrata, José Sócrates, Mário Soares, Ramalho Eanes; a mais: Jorge Palma
- observador_8365425 · 0.657 · faltam: Unidade de Estrangeiros e Fronteiras da PSP, Governo de Portugal
- jn_18136490 · 0.661 · —
- observador_8365764 · 0.684 · faltam: Sistema Integrado das Redes de Emergência e Segurança de Portugal, Provedoria de Justiça, Assembleia da República; a mais: Agência Lusa

**gpt-5-4-nano**
- jn_18136547 · 0.579 · a mais: Docentes aposentados
- observador_8364379 · 0.589 · faltam: Governo de Portugal, Aliança Democrática, Hillary Clinton, Giorgia Meloni; a mais: Chega
- jn_18135667 · 0.607 · faltam: José Sócrates, Pedro Santana Lopes; a mais: AD, União Europeia, Assembleia da República
- jn_18136490 · 0.638 · a mais: Polícia de Segurança Pública (PSP)
- observador_8365810 · 0.669 · a mais: Vaticano, fieis na Praça de São Pedro

**haiku-5-5-low**
- jn_18136490 · 0.600 · —
- observador_8364379 · 0.612 · faltam: José Manuel Fernandes, Pedro Passos Coelho, Partido Social Democrata, Governo de Portugal, Chega
- observador_8365764 · 0.612 · faltam: Assembleia da República; a mais: Agência Lusa
- observador_8365578 · 0.614 · faltam: Assembleia da República, Polícia Judiciária
- jn_18135667 · 0.620 · faltam: Partido Socialista, Partido Social Democrata, José Sócrates, Mário Soares, Ramalho Eanes

## Erros

**sonnet-5-5-low**
- observador_8365329: resposta degenerada: sem entidades nem temas num artigo com texto

**ollama-glm-5-3-flash**
- jn_18136490: resposta truncada (done_reason=length): 
