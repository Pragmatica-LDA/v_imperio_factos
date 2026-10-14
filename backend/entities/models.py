from django.db import models


class Entity(models.Model):
    """Pessoa, organização, partido, instituição, meio ou local. Criada 'por rever' quando não há correspondência.

    Tipos alinhados com o schema da análise (ENTITY_TYPES); o `meio_comunicacao` do LLM grava-se como `meio`.
    """

    TYPE_CHOICES = [
        ("pessoa", "Pessoa"),
        ("organizacao", "Organização"),
        ("partido", "Partido"),
        ("governo", "Governo / ministério"),
        ("instituicao", "Instituição"),
        ("empresa", "Empresa"),
        ("meio", "Meio de comunicação"),
        ("local", "Local"),
        ("outro", "Outro"),
    ]
    STATUS_CHOICES = [("active", "Activa"), ("por_rever", "Por rever"), ("merged", "Fundida")]
    # Inclui os níveis do schema da análise (benchmark/bench/schema.py LOCATION_LEVELS).
    PLACE_LEVELS = [("internacional", "Internacional"), ("pais", "País"), ("regiao", "Região"),
                    ("distrito", "Distrito"), ("concelho", "Concelho"), ("freguesia", "Freguesia"),
                    ("localidade", "Localidade"), ("outro", "Outro")]

    canonical_name = models.CharField(max_length=300)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    is_public = models.BooleanField(null=True, help_text="Figura/entidade pública (só estas têm timeline)")
    external_id = models.CharField(max_length=50, blank=True, help_text="Ex.: Wikidata QID")
    description = models.TextField(blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children",
                               help_text="Hierarquia de locais (freguesia > concelho > distrito)")
    place_level = models.CharField(max_length=20, choices=PLACE_LEVELS, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="por_rever", db_index=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from")
    created_at = models.DateTimeField(auto_now_add=True)
    debug = models.JSONField(default=dict, blank=True, help_text="Porque foi criada (análise, candidatos)")

    class Meta:
        ordering = ["canonical_name"]
        verbose_name_plural = "entities"

    def __str__(self):
        return f"{self.canonical_name} ({self.type})"


class EntityAlias(models.Model):
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=300)
    normalized = models.CharField(max_length=300, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["entity", "normalized"], name="uniq_alias_entity_normalized")]


class ArticleEntity(models.Model):
    """Entidade numa versão (via análise): papéis, cargo à data (segundo o texto), sentimento e debug."""

    SENTIMENT_CHOICES = [("positivo", "Positivo"), ("negativo", "Negativo"), ("neutro", "Neutro")]

    analysis = models.ForeignKey("analysis.Analysis", on_delete=models.CASCADE, related_name="entities")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="mentions")
    name_in_text = models.CharField(max_length=300)
    roles = models.JSONField(default=list, blank=True)
    position_at_time = models.CharField(max_length=300, blank=True)
    sentiment = models.CharField(max_length=10, choices=SENTIMENT_CHOICES, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True, help_text="-1 a 1")
    is_location = models.BooleanField(default=False)
    evidence = models.TextField(blank=True)
    debug = models.JSONField(default=dict, blank=True)
