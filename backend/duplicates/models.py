from django.db import models


class Cluster(models.Model):
    """Grupo de notícias com o mesmo texto de origem (take da Lusa, comunicado…)."""

    ORIGIN_CHOICES = [("lusa", "Lusa"), ("agencia", "Outra agência"), ("press_release", "Comunicado"),
                      ("desconhecida", "Desconhecida")]

    original = models.ForeignKey("crawl.Article", on_delete=models.CASCADE, related_name="original_of_clusters")
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default="desconhecida")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    debug = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]


class ClusterMember(models.Model):
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name="members")
    article = models.OneToOneField("crawl.Article", on_delete=models.CASCADE, related_name="cluster_membership")
    version = models.ForeignKey("crawl.Version", on_delete=models.CASCADE, related_name="+")
    similarity = models.FloatField(help_text="Similaridade com o original (Jaccard estimado)")
    is_original = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)
