from django.contrib import admin

from core.models import Actor, AuditLog, IdempotencyKey, Parameter


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at", "updated_by"]
    search_fields = ["key", "description"]
    readonly_fields = ["updated_at", "updated_by"]

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)   # Parameter.save invalida a cache


@admin.register(Actor)
class ActorAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "description"]
    list_filter = ["kind"]
    search_fields = ["user__username", "description"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Só leitura: a auditoria nunca se edita."""

    list_display = ["at", "actor", "action", "object_type", "object_id"]
    list_filter = ["action", "object_type", "actor"]
    search_fields = ["object_id", "object_type"]
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ["at", "actor", "key", "method", "path", "status_code"]
    list_filter = ["method", "status_code"]
    search_fields = ["key", "path"]
    readonly_fields = ["key", "actor", "method", "path", "status_code", "response", "at"]

    def has_add_permission(self, request):
        return False
