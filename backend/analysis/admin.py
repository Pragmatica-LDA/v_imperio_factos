from django.contrib import admin

from .models import Analysis, CitedSource


class CitedSourceInline(admin.TabularInline):
    model = CitedSource
    extra = 0
    fields = ("type", "name", "partial_attribute", "entity", "excerpt")
    raw_id_fields = ("entity",)
    show_change_link = True


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = ("id", "version", "status", "provider", "model", "prompt_version", "piece_type", "attempts",
                    "started_at", "finished_at")
    list_filter = ("status", "provider", "model", "prompt_version", "piece_type")
    search_fields = ("version__article__title", "version__article__site_article_id", "error")
    raw_id_fields = ("version",)
    readonly_fields = ("created_at", "started_at", "finished_at", "usage", "raw_response", "debug",
                       "diff_from_previous", "ai_indicator")
    date_hierarchy = "created_at"
    inlines = [CitedSourceInline]


@admin.register(CitedSource)
class CitedSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "type", "name", "partial_attribute", "entity")
    list_filter = ("type",)
    search_fields = ("name", "partial_attribute", "excerpt")
    raw_id_fields = ("analysis", "entity")
