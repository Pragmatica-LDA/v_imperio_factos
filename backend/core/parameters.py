"""Parâmetros configuráveis do Factos (limiares, tempos, pesos).

Regra do projecto: nada disto é hardcoded. Os valores vivem no modelo `Parameter` (editável pela API);
`DEFAULTS` só serve para criar os parâmetros em falta (`manage.py bootstrap`) e como fallback.
"""

from __future__ import annotations

from django.core.cache import cache

CACHE_PREFIX = "param:"
CACHE_TIMEOUT = 60

# chave: (valor por omissão, descrição)
DEFAULTS: dict[str, tuple[object, str]] = {
    # Crawl
    "crawl.user_agent": ("FactosBot/0.1 (prova de conceito interna)", "User-Agent dos pedidos HTTP"),
    "crawl.timeout_s": (30, "Timeout de cada pedido HTTP (segundos)"),
    "crawl.default_min_delay_s": (1.0, "Intervalo mínimo entre pedidos ao mesmo site, se o site não definir outro"),
    "crawl.max_bytes": (10_000_000, "Tamanho máximo de uma resposta HTTP"),
    # Descoberta
    "discovery.max_item_age_h": (24, "Itens descobertos mais antigos que isto são ignorados (sem backfill)"),
    "discovery.tick_batch": (50, "Máximo de pontos de entrada postos na fila por tick"),
    # Falhas técnicas
    "failures.max_attempts": (5, "Tentativas antes de desistir de uma falha técnica"),
    "failures.backoff_s": ([60, 300, 900, 3600, 21600], "Espera antes de cada nova tentativa (segundos)"),
    # Revisitas
    "revisit.sweep_batch": (500, "Máximo de revisitas postas na fila por sweep"),
    "revisit.min_interval_h": (2, "Intervalo mínimo de revisita (tema quente)"),
    "revisit.max_interval_h": (12, "Intervalo máximo de revisita antes do corte (tema a arrefecer)"),
    "revisit.no_topic_interval_h": (6, "Intervalo de revisita de notícias sem tema"),
    "revisit.no_topic_max_age_h": (48, "Idade máxima para revisitar notícias sem tema"),
    "revisit.late_days": (7, "Revisita tardia, N dias depois da publicação"),
    "revisit.on_lastmod_change": (True, "Revisitar já quando o lastmod do sitemap muda"),
    # Temas e temperatura
    "topics.window_h": (72, "Janela temporal da temperatura (horas)"),
    "topics.half_life_h": (24, "Meia-vida do decaimento da temperatura (horas)"),
    "topics.media_weight": (0.5, "Peso extra por cada meio adicional a cobrir o tema"),
    "topics.hot_threshold": (5.0, "Temperatura a partir da qual o tema é quente"),
    "topics.cold_threshold": (0.5, "Temperatura abaixo da qual o tema é frio (revisitas param)"),
    # Análise LLM
    "llm.provider": ("anthropic", "Fornecedor do LLM: anthropic | openai | ollama | fake"),
    "llm.model": ("claude-haiku-5-5", "Modelo do LLM"),
    "llm.temperature": (0.0, "Temperatura do LLM"),
    "llm.max_output_tokens": (12000, "Máximo de tokens na resposta do LLM"),
    "analysis.enabled": (True, "Análise automática de cada versão nova"),
    "analysis.daily_limit": (500, "Máximo de análises LLM por dia (UTC)"),
    "analysis.max_chars": (20000, "Texto máximo enviado ao LLM por notícia"),
    "analysis.topic_candidates": (50, "Nº de temas activos (mais quentes) enviados ao LLM como candidatos"),
    "analysis.drain_batch": (50, "Análises pendentes retomadas por execução do drain"),
    # Duplicados
    "duplicates.threshold": (0.75, "Similaridade (Jaccard estimado) a partir da qual duas notícias são duplicados"),
    "duplicates.window_h": (48, "Janela temporal para procurar duplicados (horas)"),
    "duplicates.shingle_size": (5, "Tamanho dos shingles (palavras)"),
    "duplicates.min_words": (60, "Mínimo de palavras para entrar na detecção de duplicados"),
    # Qualidade / fiabilidade do crawl
    "quality.min_words": (120, "Corpo com menos palavras conta como curto"),
    "quality.success_warn": (0.9, "Taxa de sucesso abaixo da qual o site fica em aviso"),
    "quality.success_alert": (0.7, "Taxa de sucesso abaixo da qual o site fica em alerta"),
    "quality.drop_alert": (0.15, "Queda face à média móvel que dispara alerta"),
    "quality.moving_avg_buckets": (6, "Nº de períodos anteriores na média móvel"),
    # Cache do front-office
    "cache.stats_s": (120, "Cache das estatísticas (segundos)"),
    # API e dashboard de fiabilidade
    "cache.crawl_health_s": (30, "Cache do /api/stats/crawl-health/ (segundos)"),
    "quality.min_bucket_fetches": (5, "Mínimo de leituras num período para contar no estado do site"),
    "quality.top_fields": (10, "Nº de códigos de qualidade (erros/avisos) mostrados por site"),
    "stats.hour_window_h": (48, "Janela por omissão do crawl-health com bucket=hour (horas)"),
    "stats.day_window_d": (30, "Janela por omissão do crawl-health com bucket=day (dias)"),
    "stats.daily_days": (14, "Nº de dias das séries diárias em /api/stats/"),
    "topics.hot_limit": (20, "Nº de temas devolvidos por /api/topics/hot/"),
    # Análise LLM (produção): extras do provider, tentativas e reparação
    "llm.base_url": ("", "URL base do provider (vazio = por omissão)"),
    "llm.params": ({}, "Parâmetros extra do provider (anthropic: effort, thinking; openai: reasoning_effort; ollama: num_ctx…)"),
    "analysis.max_attempts": (3, "Tentativas de uma análise que falhou antes de desistir (drain)"),
    "analysis.repair_attempts": (1, "Novos pedidos com os erros do schema quando a resposta é inválida"),
    "analysis.stale_running_min": (30, "Uma análise 'a correr' há mais do que isto é considerada morta e retomada"),
    "analysis.min_words_expect_entities": (80, "Notícia com mais palavras do que isto e resposta sem entidades nem temas = resposta inválida (stub)"),
    # Duplicados: diferenças textuais entre membros do cluster
    "duplicates.diff_max_items": (20, "Máximo de diferenças textuais guardadas por membro do cluster"),
    "duplicates.diff_context_words": (6, "Palavras de contexto à volta de cada diferença"),
    # Front-office (/api/front/)
    "cache.front_s": (60, "Cache do /api/front/overview/ (segundos)"),
    "front.window_h": (24, "Janela do 'agora' no front-office: histórias, entidades em destaque, totais (horas)"),
    "front.max_window_articles": (800, "Máximo de notícias da janela consideradas no agrupamento em histórias"),
    "front.story_min_shared": (2, "Entidades salientes partilhadas para duas notícias contarem como a mesma história"),
    "front.story_min_similarity": (0.5, "Sobreposição mínima (pesada pelo IDF na janela) das entidades salientes para a mesma história"),
    "front.story_entity_types": (["pessoa", "partido", "governo", "instituicao", "empresa", "organizacao", "outro"],
                                 "Tipos de entidade salientes para agrupar histórias e ligar notícias semelhantes"),
    "front.story_half_life_h": (12, "Meia-vida da actualidade no ranking das histórias (horas)"),
    "front.story_weight_coverage": (0.6, "Peso de cada notícia/meio adicional na mesma história"),
    "front.story_weight_temperature": (1.0, "Peso da temperatura do tema (normalizada 0–1) no ranking das histórias"),
    "front.story_weight_homepage": (0.3, "Bónus de uma notícia que esteve em destaque numa homepage"),
    "front.stories_limit": (12, "Nº de histórias principais"),
    "front.hot_topics_limit": (10, "Nº de temas quentes no front-office"),
    "front.entity_limit": (30, "Nº de entidades em destaque"),
    "front.entity_exclude_types": (["meio"], "Tipos de entidade fora do destaque de entidades"),
    "front.entity_exclude_roles": (["autor"], "Menções só com estes papéis não contam para o destaque"),
    "front.places_limit": (12, "Nº de locais em destaque"),
    "front.latest_per_site": (8, "Últimas notícias por meio"),
    "front.tone_threshold": (0.25, "Média do sentimento por entidade acima/abaixo da qual a notícia é positiva/negativa"),
    "front.ai_threshold": (50, "Indicador de IA (0–100) a partir do qual a notícia conta como 'com IA'"),
    "front.related_limit": (8, "Nº de notícias relacionadas em cada lista do detalhe"),
    "front.entity_days": (14, "Dias da série de menções no detalhe da entidade e do tema"),
}


def get(key: str, default: object = None) -> object:
    """Valor do parâmetro (cache Redis → BD → DEFAULTS)."""
    ck = CACHE_PREFIX + key
    try:
        cached = cache.get(ck)
    except Exception:  # noqa: BLE001 — a cache nunca pode partir o pipeline
        cached = None
    if cached is not None:
        return cached["v"]
    from core.models import Parameter

    row = Parameter.objects.filter(key=key).values_list("value", flat=True).first()
    if row is None and key in DEFAULTS:
        value = DEFAULTS[key][0]
    elif row is None:
        value = default
    else:
        value = row
    try:
        cache.set(ck, {"v": value}, CACHE_TIMEOUT)
    except Exception:  # noqa: BLE001
        pass
    return value


def invalidate(key: str) -> None:
    try:
        cache.delete(CACHE_PREFIX + key)
    except Exception:  # noqa: BLE001
        pass


def ensure_defaults() -> int:
    """Cria os parâmetros em falta. Nunca altera valores existentes."""
    from core.models import Parameter

    created = 0
    for key, (value, desc) in DEFAULTS.items():
        _, was_created = Parameter.objects.get_or_create(key=key, defaults={"value": value, "description": desc})
        created += was_created
    return created
