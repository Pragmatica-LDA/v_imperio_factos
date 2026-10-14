from django.contrib import admin

from .models import BenchmarkRun, BenchmarkScore, BenchResult, ModelConfig, PromptVersion, SampleArticle, ScoringConfig


@admin.register(SampleArticle)
class SampleArticleAdmin(admin.ModelAdmin):
    list_display = ("site", "site_article_id", "title", "piece_type_site", "word_count", "published_at")
    list_filter = ("site", "piece_type_site")
    search_fields = ("title", "site_article_id")


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "model_id", "concurrency", "price_input_per_mtok", "price_output_per_mtok", "active")
    list_filter = ("provider", "active")
    list_editable = ("active",)


@admin.register(PromptVersion)
class PromptVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "created_at")


@admin.register(ScoringConfig)
class ScoringConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at")


@admin.register(BenchmarkRun)
class BenchmarkRunAdmin(admin.ModelAdmin):
    list_display = ("id", "baseline_label", "prompt_version", "status", "repeat", "started_at", "finished_at")
    list_filter = ("status", "baseline_label")


@admin.register(BenchResult)
class BenchResultAdmin(admin.ModelAdmin):
    list_display = ("id", "model_config", "article", "is_baseline", "baseline_label", "run", "valid_schema", "latency_ms")
    list_filter = ("is_baseline", "valid_schema", "model_config")
    raw_id_fields = ("article", "run")


@admin.register(BenchmarkScore)
class BenchmarkScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "result", "total")
    list_filter = ("run",)
    raw_id_fields = ("result", "baseline_result")
