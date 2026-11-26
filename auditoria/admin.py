"""Configuración del panel de Django para la aplicación auditoria."""

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Solo lectura: la bitácora no se edita ni se borra desde el panel de Django."""

    list_display = ("created_at", "user", "action", "target_name", "store")
    list_filter = ("action",)
    search_fields = ("user__email", "target_name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
