"""Cómo las vistas del panel anotan en la bitácora lo que hizo el administrador."""

from .models import ID, AuditLog

Accion = AuditLog.Action


def registrar(
    usuario, accion, elemento_id, elemento, detalles=None, comercio=None
):
    """Anota una acción de administrador en la bitácora de auditoría.

    accion: un valor de Accion; su prefijo dice qué tipo de elemento afecta.
    elemento_id y elemento: el id y el nombre de lo afectado (un correo, un comercio...).
    detalles: lo necesario para entender la acción, con claves legibles («Motivo»).
    comercio: el comercio (o su id) cuando la acción es sobre él o sobre una de sus cuentas.
    La fecha y la hora las pone la bitácora al guardar el registro.
    """
    accion = Accion(accion)
    return AuditLog.objects.create(
        user=usuario,
        store_id=getattr(comercio, "pk", comercio),
        action=accion,
        target_name=str(elemento),
        details={ID: elemento_id, **(detalles or {})},
    )
