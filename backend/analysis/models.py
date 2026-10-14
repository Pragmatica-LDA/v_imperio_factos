from django.db import models


class Analysis(models.Model):
    """Análise LLM de uma versão. Guarda o modelo, o prompt, o consumo e o debug de cada decisão."""

    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("running", "A correr"),
        ("done", "Feita"),
        ("failed", "Falhou"),
        ("skipped_budget", "Adiada (limite diário)"),
        ("skipped", "Ignorada"),
    ]

    version = models.ForeignKey("crawl.Version", on_delete=models.CASCADE, related_name="analyses")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    provider = models.CharField(max_length=20, blank=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=20, blank=True)
    piece_type = models.CharField(max_length=30, blank=True)
    piece_type_reasoning = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    usage = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(null=True, blank=True)
    debug = models.JSONField(default=dict, blank=True)
    diff_from_previous = models.JSONField(null=True, blank=True)
    ai_indicator = models.JSONField(null=True, blank=True, help_text="Indicador de escrita por IA {score 0–100, signals}")
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "analyses"


class CitedSource(models.Model):
    """Fonte citada na notícia (anónima, oficial, documento, agência, redes sociais, especialista, outro meio)."""

    TYPE_CHOICES = [
        ("anonima", "Anónima"),
        ("oficial", "Oficial"),
        ("documento", "Documento"),
        ("agencia", "Agência"),
        ("redes_sociais", "Redes sociais"),
        ("especialista", "Especialista"),
        ("outro_meio", "Outro meio"),
        ("testemunha", "Testemunha"),
        ("outro", "Outro"),
    ]

    analysis = models.ForeignKey(Analysis, on_delete=models.CASCADE, related_name="sources")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    name = models.CharField(max_length=300, blank=True)
    partial_attribute = models.CharField(max_length=300, blank=True, help_text='Ex.: "fonte próxima do Governo"')
    entity = models.ForeignKey("entities.Entity", null=True, blank=True, on_delete=models.SET_NULL, related_name="cited_as_source")
    excerpt = models.TextField(blank=True)
    debug = models.JSONField(default=dict, blank=True)
