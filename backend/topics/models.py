from django.db import models


class Topic(models.Model):
    """Tema, evento ou caso, em árvore. A temperatura só conta no tema-folha/edição."""

    KIND_CHOICES = [("tema", "Tema"), ("evento", "Evento"), ("caso", "Caso")]
    RECURRENCE_CHOICES = [("nenhuma", "Nenhuma"), ("anual", "Anual"), ("por_evento", "Por evento")]
    STATUS_CHOICES = [("active", "Activo"), ("por_rever", "Por rever"), ("merged", "Fundido")]

    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=300, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="tema")
    recurrence = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default="nenhuma")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="por_rever", db_index=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from")
    temperature = models.FloatField(default=0.0, db_index=True)
    temperature_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    debug = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-temperature", "name"]

    def __str__(self):
        return self.name


class Edition(models.Model):
    """Edição de um tema recorrente (ex.: Orçamento do Estado 2027, Autárquicas 2025)."""

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="editions")
    label = models.CharField(max_length=100)
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    temperature = models.FloatField(default=0.0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["topic", "label"], name="uniq_edition_topic_label")]

    def __str__(self):
        return f"{self.topic.name} — {self.label}"


class ArticleTopic(models.Model):
    analysis = models.ForeignKey("analysis.Analysis", on_delete=models.CASCADE, related_name="topics")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="article_links")
    edition = models.ForeignKey(Edition, null=True, blank=True, on_delete=models.SET_NULL, related_name="article_links")
    weight = models.FloatField(default=1.0)
    created_topic = models.BooleanField(default=False, help_text="O tema foi criado por esta análise")
    debug = models.JSONField(default=dict, blank=True)


class TopicTemperature(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="temperature_history")
    at = models.DateTimeField(db_index=True)
    value = models.FloatField()
    articles = models.PositiveIntegerField(default=0)
    sites = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-at"]
