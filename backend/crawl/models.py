from django.contrib.postgres.fields import ArrayField
from django.db import models


class Article(models.Model):
    """Uma notícia. Identificada pelo ID interno do site quando existe; pode ter vários URLs."""

    STATUS_CHOICES = [
        ("discovered", "Descoberta (por descarregar)"),
        ("active", "Activa"),
        ("out_of_scope", "Fora de âmbito"),
        ("deleted", "Apagada"),
        ("failed", "Falha técnica"),
    ]

    site = models.ForeignKey("sources.Site", on_delete=models.PROTECT, related_name="articles")
    site_article_id = models.CharField(max_length=50, null=True, blank=True)
    canonical_url = models.URLField(max_length=1000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="discovered", db_index=True)
    out_of_scope_reason = models.CharField(max_length=100, blank=True)
    deleted_reason = models.CharField(max_length=100, blank=True)

    title = models.TextField(blank=True)
    section = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    access = models.CharField(max_length=20, blank=True)
    piece_type = models.CharField(max_length=30, blank=True)
    agencies = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    discovery_meta = models.JSONField(default=dict, blank=True, help_text="Dados vindos da descoberta (lastmod, keywords…)")

    first_seen_at = models.DateTimeField(auto_now_add=True, db_index=True)
    first_seen_via = models.ForeignKey("sources.EntryPoint", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_fetched_at = models.DateTimeField(null=True, blank=True)

    next_revisit_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revisit_reason = models.CharField(max_length=200, blank=True)
    revisit_topic = models.ForeignKey("topics.Topic", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    late_revisit_done = models.BooleanField(default=False)

    version_count = models.PositiveIntegerField(default=0)
    change_ratio_total = models.FloatField(default=0.0)

    class Meta:
        ordering = ["-published_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "site_article_id"],
                condition=models.Q(site_article_id__isnull=False),
                name="uniq_article_site_id",
            )
        ]

    def __str__(self):
        return f"{self.site.slug}:{self.site_article_id or self.pk} {self.title[:60]}"

    @property
    def current_version(self):
        return self.versions.order_by("-number").first()


class ArticleURL(models.Model):
    KIND_CHOICES = [
        ("canonical", "Canónico"),
        ("alias", "Alias"),
        ("redirect", "Redirect"),
        ("discovered", "Descoberto"),
    ]
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="urls")
    url = models.URLField(max_length=1000, unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="discovered")
    first_seen_at = models.DateTimeField(auto_now_add=True)


class Fetch(models.Model):
    """Uma leitura HTTP de uma notícia. O HTML fica em gzip em RAW_HTML_ROOT (raw_path)."""

    REASON_CHOICES = [("new", "Nova"), ("revisit", "Revisita"), ("late", "Revisita tardia"),
                      ("manual", "Manual"), ("retry", "Nova tentativa"), ("lastmod", "lastmod alterado")]
    OUTCOME_CHOICES = [
        ("ok", "OK"),
        ("unchanged", "Sem alterações"),
        ("out_of_scope", "Fora de âmbito"),
        ("deleted", "Apagada"),
        ("redirect", "Redirect para outro artigo"),
        ("technical_failure", "Falha técnica"),
        ("parse_error", "Erro de parse"),
        ("rate_limited", "Adiada (rate limit)"),
    ]

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="fetches")
    url = models.URLField(max_length=1000)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    final_url = models.URLField(max_length=1000, blank=True)
    redirect_chain = models.JSONField(default=list, blank=True)
    raw_path = models.CharField(max_length=500, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, db_index=True)
    error = models.TextField(blank=True)
    # Diagnóstico da extracção (crawl/quality.py): campos em falta, corpo curto, ruído…
    quality = models.JSONField(default=dict, blank=True)
    quality_ok = models.BooleanField(null=True)

    class Meta:
        ordering = ["-requested_at"]


class Version(models.Model):
    """Versão do conteúdo extraído. Só há versão nova quando o conteúdo extraído muda."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    fetch = models.ForeignKey(Fetch, on_delete=models.PROTECT, related_name="versions")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    content = models.JSONField(help_text="Article.to_dict() do parser")
    content_hash = models.CharField(max_length=64, db_index=True)
    text = models.TextField(help_text="Título + lead + corpo, em texto simples")
    word_count = models.PositiveIntegerField(default=0)
    change_ratio = models.FloatField(default=0.0, help_text="0 = igual à versão anterior, 1 = totalmente diferente")
    diff = models.JSONField(default=dict, blank=True)
    minhash = ArrayField(models.BigIntegerField(), null=True, blank=True)

    class Meta:
        ordering = ["article", "number"]
        constraints = [models.UniqueConstraint(fields=["article", "number"], name="uniq_version_article_number")]


class HomepageAppearance(models.Model):
    """A notícia apareceu na homepage (sinal de destaque: zona e posição)."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="homepage_appearances")
    entrypoint = models.ForeignKey("sources.EntryPoint", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey("sources.DiscoveryRun", null=True, on_delete=models.SET_NULL, related_name="+")
    seen_at = models.DateTimeField(auto_now_add=True, db_index=True)
    zone = models.CharField(max_length=100, blank=True)
    zones = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    rank = models.PositiveIntegerField(null=True)


class TechnicalFailure(models.Model):
    """Falha técnica (timeout, 5xx, 403/429, rede, parse). Não é dado editorial: retry e revisão à parte."""

    KIND_CHOICES = [("timeout", "Timeout"), ("http_5xx", "5xx"), ("http_403", "403"), ("http_429", "429"),
                    ("http_other", "Outro HTTP"), ("network", "Rede"), ("parse", "Parse"), ("other", "Outro")]
    STATUS_CHOICES = [("open", "Aberta"), ("retrying", "Em nova tentativa"),
                      ("given_up", "Desistida"), ("resolved", "Resolvida")]

    article = models.ForeignKey(Article, null=True, blank=True, on_delete=models.CASCADE, related_name="failures")
    entrypoint = models.ForeignKey("sources.EntryPoint", null=True, blank=True, on_delete=models.CASCADE, related_name="failures")
    url = models.URLField(max_length=1000)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=1)
    last_error = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open", db_index=True)
    first_at = models.DateTimeField(auto_now_add=True)
    last_at = models.DateTimeField(auto_now=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    fetch_reason = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-last_at"]


class ArticleLink(models.Model):
    """Ligação editorial no corpo de uma versão (inline ou embed): outra notícia, outro site, rede social…"""

    KIND_CHOICES = [("inline", "Ligação no texto"), ("embed", "Conteúdo embebido")]
    SCOPE_CHOICES = [("internal", "Interna (mesmo site)"), ("media", "Outro meio monitorizado"),
                     ("external", "Externa")]

    version = models.ForeignKey(Version, on_delete=models.CASCADE, related_name="links")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    position = models.PositiveIntegerField(help_text="Ordem da ligação no corpo")
    block_index = models.PositiveIntegerField(null=True, blank=True)
    url = models.URLField(max_length=2000)
    normalized_url = models.URLField(max_length=2000, db_index=True, help_text="Sem parâmetros de tracking nem fragmento")
    domain = models.CharField(max_length=255, db_index=True)
    text = models.TextField(blank=True, help_text="Texto da âncora ou legenda do embed")
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, db_index=True)
    platform = models.CharField(max_length=30, db_index=True,
                                help_text="facebook, instagram, x, youtube, tiktok, …, encurtador, documento, site")
    is_document = models.BooleanField(default=False)
    target_site = models.ForeignKey("sources.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_article = models.ForeignKey(Article, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="incoming_links")

    class Meta:
        ordering = ["version", "position"]
        constraints = [models.UniqueConstraint(fields=["version", "position"], name="uniq_link_version_position")]
