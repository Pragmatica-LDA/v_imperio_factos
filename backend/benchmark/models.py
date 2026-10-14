"""Benchmark de LLMs para a análise das notícias.

Uma baseline é um conjunto de resultados de referência (`BenchResult.is_baseline`) identificado por um
`baseline_label`. Cada `BenchmarkRun` corre um ou mais modelos sobre uma amostra de artigos e pontua cada
resultado contra a baseline com a `ScoringConfig` activa. Pesos, limiares e preços vivem na BD.

A amostra (`SampleArticle`) vem dos JSON dos parsers da PoC (sites/out), independente do pipeline de crawl,
para a comparação ser reprodutível com os mesmos textos.
"""

from django.db import models


class SampleArticle(models.Model):
    """Artigo extraído pelos parsers (contrato v2.1 de parsers/base.py), na forma que vai para o LLM."""

    site = models.CharField(max_length=50)
    site_article_id = models.CharField(max_length=100)
    url = models.URLField(max_length=1000)
    title = models.TextField()
    lead = models.TextField(blank=True)
    body = models.TextField(help_text="Corpo em texto, um bloco por parágrafo.")
    byline = models.CharField(max_length=500, blank=True)
    section = models.CharField(max_length=200, blank=True)
    tags = models.JSONField(default=list, blank=True)
    piece_type_site = models.CharField(max_length=50, blank=True, help_text="Tipo de peça segundo o site.")
    published_at = models.DateTimeField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    raw = models.JSONField(default=dict, help_text="Saída integral do parser.")
    source_file = models.CharField(max_length=500, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "site_article_id"], name="bench_article_site_id_unique")]
        ordering = ["site", "site_article_id"]

    def __str__(self):
        return f"{self.key} {self.title[:60]}"

    @property
    def key(self) -> str:
        return f"{self.site}_{self.site_article_id}"


class PromptVersion(models.Model):
    """Prompt + schema de saída. Imutável depois de usado: uma alteração é uma versão nova."""

    name = models.CharField(max_length=100, default="analise")
    version = models.CharField(max_length=20)
    system_prompt = models.TextField()
    user_template = models.TextField(help_text="Template do pedido por artigo (str.format com os campos do artigo).")
    output_schema = models.JSONField()
    taxonomy = models.JSONField(default=list, help_text="Taxonomia-semente de temas incluída no prompt.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["name", "version"], name="bench_prompt_name_version_unique")]

    def __str__(self):
        return f"{self.name} {self.version}"


class ModelConfig(models.Model):
    """Um modelo + parâmetros a testar. O mesmo modelo pode ter várias configs (ex.: effort low vs medium)."""

    PROVIDER_ANTHROPIC = "anthropic"
    PROVIDER_OPENAI = "openai"
    PROVIDER_OLLAMA = "ollama"
    PROVIDER_MANUAL = "manual"
    PROVIDERS = [
        (PROVIDER_ANTHROPIC, "Anthropic"),
        (PROVIDER_OPENAI, "OpenAI"),
        (PROVIDER_OLLAMA, "Ollama"),
        (PROVIDER_MANUAL, "Manual (resultados importados)"),
    ]

    name = models.SlugField(max_length=100, unique=True, help_text="Identificador curto usado nos comandos.")
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    model_id = models.CharField(max_length=200)
    base_url = models.CharField(max_length=500, blank=True, help_text="Vazio = valor por omissão do provider.")
    params = models.JSONField(
        default=dict, blank=True,
        help_text="Parâmetros do provider: max_tokens, effort, reasoning_effort, temperature, num_ctx, think…",
    )
    price_input_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    price_output_per_mtok = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    concurrency = models.PositiveSmallIntegerField(default=1, help_text="Pedidos em paralelo no benchmark.")
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["provider", "name"]

    def __str__(self):
        return self.name

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * float(self.price_input_per_mtok) + tokens_out * float(self.price_output_per_mtok)) / 1e6


class ScoringConfig(models.Model):
    """Pesos e limiares do scoring. A activa é a mais recente com active=True."""

    name = models.CharField(max_length=100, unique=True)
    weights = models.JSONField(help_text="Peso de cada métrica no score total.")
    thresholds = models.JSONField(help_text="Limiares de matching (fuzzy de nomes, excertos…) e créditos parciais.")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @classmethod
    def current(cls) -> "ScoringConfig":
        config = cls.objects.filter(active=True).first()
        if config is None:
            raise cls.DoesNotExist("Sem ScoringConfig activa: corre `manage.py bench_seed`.")
        return config


class BenchmarkRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUSES = [(STATUS_RUNNING, "A correr"), (STATUS_DONE, "Concluído"), (STATUS_FAILED, "Falhou")]

    baseline_label = models.CharField(max_length=100)
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.PROTECT)
    scoring_config = models.ForeignKey(ScoringConfig, on_delete=models.PROTECT)
    model_configs = models.ManyToManyField(ModelConfig, related_name="runs")
    articles = models.ManyToManyField(SampleArticle, related_name="runs")
    repeat = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_RUNNING)
    summary = models.JSONField(default=dict, blank=True, help_text="Agregados por modelo (score, latência, custo).")
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"run {self.pk} vs {self.baseline_label}"


class BenchResult(models.Model):
    """Saída de um modelo para um artigo. Guarda a resposta crua e o debug do modelo (dentro de `output`)."""

    article = models.ForeignKey(SampleArticle, on_delete=models.CASCADE, related_name="results")
    model_config = models.ForeignKey(ModelConfig, on_delete=models.PROTECT, related_name="results")
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.PROTECT, related_name="results")
    run = models.ForeignKey(BenchmarkRun, on_delete=models.CASCADE, null=True, blank=True, related_name="results")
    attempt = models.PositiveSmallIntegerField(default=1)
    is_baseline = models.BooleanField(default=False)
    baseline_label = models.CharField(max_length=100, blank=True, db_index=True)
    output = models.JSONField(null=True, blank=True)
    raw_response = models.TextField(blank=True)
    valid_schema = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    tokens_in = models.PositiveIntegerField(null=True, blank=True)
    tokens_out = models.PositiveIntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    provider_meta = models.JSONField(default=dict, blank=True, help_text="stop_reason, tokens/s do provider, ids…")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "baseline_label"], condition=models.Q(is_baseline=True),
                name="bench_one_baseline_per_article_label",
            ),
        ]

    def __str__(self):
        tag = f"baseline {self.baseline_label}" if self.is_baseline else f"run {self.run_id}"
        return f"{self.model_config} · {self.article.key} · {tag}"


class BenchmarkScore(models.Model):
    """Pontuação de um resultado contra o resultado da baseline para o mesmo artigo."""

    run = models.ForeignKey(BenchmarkRun, on_delete=models.CASCADE, related_name="scores")
    result = models.OneToOneField(BenchResult, on_delete=models.CASCADE, related_name="score")
    baseline_result = models.ForeignKey(BenchResult, on_delete=models.PROTECT, related_name="+")
    metrics = models.JSONField(help_text="Score 0–1 por métrica.")
    total = models.FloatField()
    details = models.JSONField(default=dict, blank=True, help_text="Emparelhamentos e diferenças, para revisão.")

    class Meta:
        ordering = ["run", "-total"]
