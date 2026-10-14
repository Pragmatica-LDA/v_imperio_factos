from django.contrib import admin

from crawl.models import Article, ArticleURL, Fetch, HomepageAppearance, TechnicalFailure, Version


def _readonly(model):
    return [f.name for f in model._meta.fields]


class ArticleURLInline(admin.TabularInline):
    model = ArticleURL
    extra = 0
    readonly_fields = ["url", "kind", "first_seen_at"]
    can_delete = False


class VersionInline(admin.TabularInline):
    model = Version
    extra = 0
    fields = ["number", "created_at", "word_count", "change_ratio", "content_hash"]
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["id", "site", "site_article_id", "title", "status", "piece_type", "published_at",
                    "version_count", "last_fetched_at"]
    list_filter = ["site", "status", "access", "piece_type"]
    search_fields = ["title", "canonical_url", "site_article_id"]
    date_hierarchy = "published_at"
    list_select_related = ["site"]
    raw_id_fields = ["first_seen_via", "revisit_topic"]
    readonly_fields = ["discovery_meta", "first_seen_at", "version_count", "change_ratio_total", "last_fetched_at"]
    inlines = [ArticleURLInline, VersionInline]


@admin.register(Fetch)
class FetchAdmin(admin.ModelAdmin):
    list_display = ["requested_at", "article_id", "reason", "http_status", "outcome", "quality_ok", "duration_ms"]
    list_filter = ["outcome", "quality_ok", "reason", "article__site"]
    search_fields = ["url", "error"]
    date_hierarchy = "requested_at"
    readonly_fields = _readonly(Fetch)

    def has_add_permission(self, request):
        return False


@admin.register(Version)
class VersionAdmin(admin.ModelAdmin):
    list_display = ["article_id", "number", "created_at", "word_count", "change_ratio"]
    search_fields = ["article__title", "content_hash"]
    date_hierarchy = "created_at"
    readonly_fields = [f for f in _readonly(Version) if f != "minhash"]
    exclude = ["minhash"]

    def has_add_permission(self, request):
        return False


@admin.register(HomepageAppearance)
class HomepageAppearanceAdmin(admin.ModelAdmin):
    list_display = ["seen_at", "article_id", "entrypoint", "zone", "rank"]
    list_filter = ["entrypoint"]
    readonly_fields = _readonly(HomepageAppearance)

    def has_add_permission(self, request):
        return False


@admin.register(TechnicalFailure)
class TechnicalFailureAdmin(admin.ModelAdmin):
    list_display = ["last_at", "kind", "http_status", "status", "attempts", "url", "next_retry_at"]
    list_filter = ["status", "kind"]
    search_fields = ["url", "last_error"]
    raw_id_fields = ["article", "entrypoint"]
    readonly_fields = ["first_at", "last_at", "last_error"]
