from django.db import models


class Site(models.Model):
    """Um meio de comunicação monitorizado. O parser é `parsers/<parser_module>.py`."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    base_url = models.URLField()
    parser_module = models.CharField(max_length=50)
    active = models.BooleanField(default=True)
    skip_premium_on_discovery = models.BooleanField(
        default=False, help_text="Premium marcado na descoberta não é descarregado (o site corta o texto)")
    min_delay_s = models.FloatField(null=True, blank=True, help_text="Intervalo mínimo entre pedidos (vazio = parâmetro global)")
    # O meio como entidade (para ligar fontes citadas "outro meio").
    entity = models.ForeignKey("entities.Entity", null=True, blank=True, on_delete=models.SET_NULL, related_name="sites")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self):
        return self.name


class EntryPoint(models.Model):
    """Ponto de entrada da descoberta: homepage, sitemap, news sitemap, índice, sitemap diário ou feed."""

    KIND_CHOICES = [
        ("homepage", "Homepage"),
        ("sitemap", "Sitemap"),
        ("sitemap_news", "News sitemap"),
        ("sitemap_index", "Índice de sitemaps"),
        ("sitemap_daily", "Sitemap diário (template {yyyy}{mm}{dd})"),
        ("feed", "RSS/Atom"),
    ]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="entrypoints")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    url = models.CharField(max_length=500, help_text="URL; no sitemap_daily aceita {yyyy}, {mm}, {dd}")
    config = models.JSONField(default=dict, blank=True)
    interval_s = models.PositiveIntegerField(help_text="Cadência da descoberta (segundos)")
    active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["site__slug", "name"]
        constraints = [models.UniqueConstraint(fields=["site", "name"], name="uniq_entrypoint_site_name")]

    def __str__(self):
        return f"{self.site.slug}:{self.name}"


class DiscoveryRun(models.Model):
    """Uma execução da descoberta num ponto de entrada (sinal de fiabilidade: itens encontrados, erros)."""

    entrypoint = models.ForeignKey(EntryPoint, on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    urls_fetched = models.JSONField(default=list, blank=True)
    found = models.PositiveIntegerField(default=0)
    excluded = models.PositiveIntegerField(default=0)
    new = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped_old = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    debug = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
