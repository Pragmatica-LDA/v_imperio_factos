from django.contrib import admin

from .models import Cluster, ClusterMember


class ClusterMemberInline(admin.TabularInline):
    model = ClusterMember
    extra = 0
    fields = ("article", "version", "similarity", "is_original", "added_at")
    readonly_fields = ("added_at",)
    raw_id_fields = ("article", "version")


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "original", "origin", "created_at", "updated_at")
    list_filter = ("origin",)
    search_fields = ("original__title", "members__article__title")
    raw_id_fields = ("original",)
    readonly_fields = ("created_at", "updated_at", "debug")
    inlines = [ClusterMemberInline]


@admin.register(ClusterMember)
class ClusterMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "cluster", "article", "similarity", "is_original", "added_at")
    list_filter = ("is_original",)
    raw_id_fields = ("cluster", "article", "version")
