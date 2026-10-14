from django.conf import settings
from django.db import models


class Parameter(models.Model):
    """Parâmetro configurável (limiar, tempo, peso). Ver core/parameters.py."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key}={self.value!r}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from core.parameters import invalidate

        invalidate(self.key)


class Actor(models.Model):
    """Perfil de quem usa a API: humano ou agente. Cada actor tem o seu token (DRF)."""

    KIND_CHOICES = [("human", "Humano"), ("agent", "Agente")]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="actor")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="human")
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.kind})"


class AuditLog(models.Model):
    """Registo de todas as escritas pela API: quem, quando, antes e depois."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=50)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["object_type", "object_id"])]


class IdempotencyKey(models.Model):
    """Resposta guardada de um POST com `Idempotency-Key`, para repetições devolverem o mesmo resultado."""

    key = models.CharField(max_length=200)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    response = models.JSONField(null=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "key"], name="uniq_idempotency_actor_key")]
