from django.contrib import admin

from .models import ArticleEntity, Entity, EntityAlias


class EntityAliasInline(admin.TabularInline):
    model = EntityAlias
    extra = 0
    fields = ("alias", "normalized")


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("id", "canonical_name", "type", "status", "is_public", "place_level", "parent", "merged_into",
                    "created_at")
    list_filter = ("status", "type", "is_public", "place_level")
    search_fields = ("canonical_name", "aliases__normalized", "external_id")
    raw_id_fields = ("parent", "merged_into")
    readonly_fields = ("created_at", "debug")
    inlines = [EntityAliasInline]


@admin.register(EntityAlias)
class EntityAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "normalized", "entity")
    search_fields = ("alias", "normalized")
    raw_id_fields = ("entity",)


@admin.register(ArticleEntity)
class ArticleEntityAdmin(admin.ModelAdmin):
    list_display = ("id", "analysis", "entity", "name_in_text", "roles", "sentiment", "is_location",
                    "position_at_time")
    list_filter = ("sentiment", "is_location", "entity__type")
    search_fields = ("name_in_text", "entity__canonical_name", "evidence")
    raw_id_fields = ("analysis", "entity")
    readonly_fields = ("debug",)
