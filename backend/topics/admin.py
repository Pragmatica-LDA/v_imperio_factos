from django.contrib import admin

from .models import ArticleTopic, Edition, Topic, TopicTemperature


class EditionInline(admin.TabularInline):
    model = Edition
    extra = 0
    fields = ("label", "starts_at", "ends_at", "temperature")
    readonly_fields = ("temperature",)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "parent", "kind", "recurrence", "status", "temperature", "temperature_at")
    list_filter = ("status", "kind", "recurrence")
    search_fields = ("name", "slug")
    raw_id_fields = ("parent", "merged_into")
    readonly_fields = ("temperature", "temperature_at", "created_at", "debug")
    inlines = [EditionInline]


@admin.register(Edition)
class EditionAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "label", "starts_at", "ends_at", "temperature")
    search_fields = ("label", "topic__name")
    raw_id_fields = ("topic",)


@admin.register(ArticleTopic)
class ArticleTopicAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "topic", "edition", "weight", "created_topic")
    list_filter = ("created_topic", "topic__status")
    search_fields = ("topic__name",)
    raw_id_fields = ("analysis", "topic", "edition")
    readonly_fields = ("debug",)


@admin.register(TopicTemperature)
class TopicTemperatureAdmin(admin.ModelAdmin):
    list_display = ("topic", "at", "value", "articles", "sites")
    raw_id_fields = ("topic",)
    date_hierarchy = "at"
