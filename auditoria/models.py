"""Bitácora de auditoría de las acciones de administrador (issue «Bitácora administrativa»).

Cada acción que un administrador hace en el panel queda registrada con quién la hizo, qué hizo,
sobre qué elemento y cuándo, en la tabla audit_admin_changes de Supabase. Los registros no se
modifican y no se pueden borrar antes de cumplir el tiempo mínimo de conservación (RETENCION).
"""

from datetime import timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.urls import reverse
from django.utils import timezone

# Al menos 12 meses: 366 días cubren también un año bisiesto.
RETENCION = timedelta(days=366)
# La clave de details con el id del elemento afectado (la tabla no tiene una columna para él).
ID = "ID"


class RegistroProtegido(Exception):
    """Se intentó modificar un registro de la bitácora o borrarlo antes de tiempo."""


def limite_de_retencion():
    """Los registros posteriores a este momento todavía deben conservarse."""
    return timezone.now() - RETENCION


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RegistroProtegido(
            "Los registros de la bitácora no se modifican."
        )

    def delete(self):
        if self.filter(created_at__gt=limite_de_retencion()).exists():
            raise RegistroProtegido(
                "La bitácora se conserva al menos 12 meses: "
                "no se pueden borrar registros más recientes."
            )
        return super().delete()


class AuditLog(models.Model):
    class Target(models.TextChoices):
        CLIENT = "cliente", "Cuenta de cliente"
        STORE = "comercio", "Comercio"
        ENTERPRISE_ACCOUNT = "cuenta_empresa", "Cuenta de empresa"
        PRODUCT = "producto", "Producto"
        REVIEW = "resena", "Reseña"
        INCIDENT = "incidencia", "Incidencia de datos"
        DATA_RUN = "obtencion", "Obtención de datos"

    class Action(models.TextChoices):
        # El valor empieza con el tipo de elemento que afecta (un valor de Target).
        CLIENT_SUSPEND = "cliente.suspender", "Suspendió la cuenta"
        CLIENT_REACTIVATE = "cliente.reactivar", "Reactivó la cuenta"
        STORE_REGISTER = "comercio.registrar", "Registró el comercio"
        STORE_EDIT = "comercio.editar", "Editó los datos del comercio"
        STORE_ACTIVATE = "comercio.activar", "Activó el comercio"
        STORE_DEACTIVATE = "comercio.desactivar", "Desactivó el comercio"
        ACCOUNT_CREATE = "cuenta_empresa.crear", "Creó la cuenta de empresa"
        ACCOUNT_SEND_ACCESS = (
            "cuenta_empresa.reenviar_acceso",
            "Reenvió el acceso a la cuenta",
        )
        PRODUCT_EDIT = "producto.editar", "Editó el producto"
        REVIEW_KEEP = "resena.mantener", "Mantuvo la reseña reportada"
        REVIEW_DELETE = "resena.eliminar", "Eliminó la reseña"
        INCIDENT_RESOLVE = "incidencia.resolver", "Resolvió la incidencia"
        DATA_RUN_REQUEST = "obtencion.ejecutar", "Pidió una obtención de datos"

    # La tabla audit_admin_changes de Supabase. Los nombres de las columnas son los suyos.
    id = models.BigAutoField(primary_key=True)
    # PROTECT: no se puede borrar la cuenta de un administrador que tiene acciones registradas.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        on_delete=models.PROTECT,
        db_column="id_requested_by",
        db_index=False,
        related_name="+",
    )
    # Solo en las acciones sobre un comercio o sus cuentas de empresa.
    store = models.ForeignKey(
        "products.Stores",
        verbose_name="comercio",
        on_delete=models.PROTECT,
        db_column="id_store",
        db_constraint=False,  # stores es una tabla de Supabase (managed = False)
        db_index=False,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField("acción", choices=Action.choices)
    # Cómo se llamaba el elemento en ese momento, aunque luego cambie o se elimine.
    target_name = models.CharField(
        "elemento afectado", db_column="element_affected"
    )
    # El id del elemento («ID») y lo necesario para entender la acción, con claves legibles.
    details = models.JSONField(
        "detalles", default=dict, blank=True, encoder=DjangoJSONEncoder
    )
    created_at = models.DateTimeField(
        "fecha y hora", default=timezone.now, editable=False
    )

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        db_table = "audit_admin_changes"
        ordering = ["-created_at", "-id"]
        verbose_name = "registro de la bitácora"
        verbose_name_plural = "bitácora de auditoría"

    def __str__(self):
        return f"{self.user_id} · {self.get_action_display()} · {self.target_name}"

    @property
    def tipo_de_elemento(self):
        """El tipo de elemento afectado, que es el prefijo de la acción («cliente.suspender»)."""
        return self.Target(self.action.split(".", 1)[0])

    @property
    def elemento_id(self):
        return self.details.get(ID)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroProtegido(
                "Los registros de la bitácora no se modifican."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.created_at > limite_de_retencion():
            raise RegistroProtegido(
                "La bitácora se conserva al menos 12 meses: "
                "este registro todavía no se puede borrar."
            )
        return super().delete(*args, **kwargs)

    def detalles_para_mostrar(self):
        """[(etiqueta, valor)] para la tabla de la bitácora, en el idioma de la página."""
        from core.translations import translate_text

        filas = []
        for etiqueta, valor in self.details.items():
            if etiqueta == ID:  # va junto al elemento afectado
                continue
            if isinstance(valor, bool):
                valor = translate_text("Sí" if valor else "No")
            elif isinstance(valor, (list, tuple)):
                valor = ", ".join(str(parte) for parte in valor)
            # El valor se muestra tal cual: puede ser un texto que escribió el administrador.
            filas.append((translate_text(etiqueta), str(valor)))
        return filas

    def url_del_elemento(self):
        """La pantalla del panel donde se ve el elemento afectado, si tiene una."""
        nombre = {
            self.Target.CLIENT: "detalle_cliente",
            self.Target.STORE: "detalle_comercio",
            self.Target.PRODUCT: "editar_producto",
        }.get(self.tipo_de_elemento)
        if nombre and str(self.elemento_id).isdigit():
            return reverse(nombre, args=[self.elemento_id])
        return ""
