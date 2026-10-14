from django.contrib import admin, messages

from sources.models import DiscoveryRun, EntryPoint, Site


class EntryPointInline(admin.TabularInline):
    model = EntryPoint
    extra = 0
    fields = ["name", "kind", "url", "interval_s", "active", "last_run_at", "next_run_at"]
    readonly_fields = ["last_run_at", "next_run_at"]


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "parser_module", "active", "skip_premium_on_discovery", "min_delay_s"]
    list_filter = ["active", "parser_module"]
    search_fields = ["slug", "name", "base_url"]
    raw_id_fields = ["entity"]
    inlines = [EntryPointInline]


@admin.action(description="Correr agora")
def run_now(modeladmin, request, queryset):
    from sources.tasks import discover_entrypoint

    for ep in queryset:
        discover_entrypoint.apply_async(args=[ep.pk], queue="discovery")
    messages.success(request, f"{queryset.count()} ponto(s) de entrada na fila discovery.")


@admin.register(EntryPoint)
class EntryPointAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "url", "interval_s", "active", "last_run_at", "next_run_at"]
    list_filter = ["site", "kind", "active"]
    search_fields = ["name", "url", "site__slug"]
    readonly_fields = ["last_run_at"]
    actions = [run_now]


@admin.register(DiscoveryRun)
class DiscoveryRunAdmin(admin.ModelAdmin):
    list_display = ["started_at", "entrypoint", "ok", "http_status", "found", "new", "updated", "excluded",
                    "skipped_old"]
    list_filter = ["ok", "entrypoint__site", "entrypoint__kind"]
    search_fields = ["entrypoint__name", "error"]
    date_hierarchy = "started_at"
    list_select_related = ["entrypoint__site"]
    readonly_fields = [f.name for f in DiscoveryRun._meta.fields]

    def has_add_permission(self, request):
        return False
