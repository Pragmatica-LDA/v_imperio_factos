from django.apps import AppConfig


class BenchmarkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "benchmark"
    verbose_name = "Benchmark de LLMs da análise"
