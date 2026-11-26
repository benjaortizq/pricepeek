"""Registro y consulta sanitizada del historial de cambios de precios."""

import calendar
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.translations import translate_text

from .models import AuditPriceChanges


MESES_HISTORIAL_PUBLICO = 6


def _descuento(valor):
    if valor is None:
        return Decimal("0.00")
    try:
        return Decimal(valor).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def registrar_cambio_precio(precio, antes, despues, id_requested_by=None):
    """Registra un cambio real de un precio existente.

    ``antes`` y ``despues`` contienen ``price``, ``discount`` e
    ``is_available``. No se registran altas, bajas ni un precio que pase por
    ``NULL``. El autor es opcional porque las actualizaciones automáticas del
    scraper no tienen un usuario asociado.
    """
    precio_anterior = antes.get("price")
    precio_nuevo = despues.get("price")
    if precio_anterior is None or precio_nuevo is None:
        return None

    descuento_anterior = _descuento(antes.get("discount"))
    descuento_nuevo = _descuento(despues.get("discount"))
    disponible_anterior = bool(antes.get("is_available"))
    disponible_nuevo = bool(despues.get("is_available"))

    if (
        int(precio_anterior) == int(precio_nuevo)
        and descuento_anterior == descuento_nuevo
        and disponible_anterior == disponible_nuevo
    ):
        return None

    return AuditPriceChanges.objects.create(
        old_price=int(precio_anterior),
        new_price=int(precio_nuevo),
        old_discount=descuento_anterior,
        new_discount=descuento_nuevo,
        id_requested_by=id_requested_by,
        created_at=timezone.now(),
        is_active=disponible_nuevo,
        gtin_id=precio.gtin_id,
        id_store_id=precio.id_store_id,
    )


def _valor_cambio(cambio, campo):
    if isinstance(cambio, dict):
        return cambio[campo]
    return getattr(cambio, campo)


def es_cambio_solo_disponibilidad(cambio):
    """Indica si el registro no cambió el precio base ni el descuento."""
    return (
        _valor_cambio(cambio, "old_price") == _valor_cambio(cambio, "new_price")
        and _descuento(_valor_cambio(cambio, "old_discount"))
        == _descuento(_valor_cambio(cambio, "new_discount"))
    )


def etiqueta_cambio_disponibilidad(cambio):
    """Devuelve la etiqueta pública de una reactivación o desactivación."""
    return translate_text(
        "Reactivación" if _valor_cambio(cambio, "is_active") else "Desactivación"
    )


def restar_meses_calendarios(fecha, meses):
    """Resta meses calendario conservando el día y la zona horaria.

    Si el mes destino tiene menos días, se usa su último día. Por ejemplo,
    31 de agosto menos seis meses calendario es 28 de febrero.
    """
    total_meses = fecha.year * 12 + fecha.month - 1 - meses
    anio, mes_indice = divmod(total_meses, 12)
    mes = mes_indice + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)


def limite_historial_publico(ahora=None):
    """Devuelve el límite aware de exactamente seis meses calendarios."""
    ahora = ahora or timezone.now()
    if timezone.is_naive(ahora):
        ahora = timezone.make_aware(ahora, timezone.get_current_timezone())
    return restar_meses_calendarios(
        timezone.localtime(ahora),
        MESES_HISTORIAL_PUBLICO,
    )


def historiales_publicos(precios, ahora=None):
    """Prepara historiales públicos sin actor ni identificadores internos.

    A cada precio se le asigna una clave pública secuencial. Los datos que se
    entregan al navegador se limitan a fecha, precios, descuentos y la
    etiqueta de un cambio exclusivo de disponibilidad.
    """
    precios = list(precios)
    if not precios:
        return {}

    ahora = ahora or timezone.now()
    if timezone.is_naive(ahora):
        ahora = timezone.make_aware(ahora, timezone.get_current_timezone())
    limite = limite_historial_publico(ahora)

    registros = (
        AuditPriceChanges.objects.filter(
            id_store_id__in={precio.id_store_id for precio in precios},
            gtin_id__in={precio.gtin_id for precio in precios},
            created_at__gte=limite,
            created_at__lte=ahora,
        )
        .values(
            "id_store_id",
            "gtin_id",
            "created_at",
            "old_price",
            "new_price",
            "old_discount",
            "new_discount",
            "is_active",
        )
        .order_by("-created_at", "-id")
    )

    por_precio = {}
    for registro in registros:
        clave_precio = (registro["id_store_id"], registro["gtin_id"])
        por_precio.setdefault(clave_precio, []).append(registro)

    historiales = {}
    for indice, precio in enumerate(precios, start=1):
        clave = f"precio-{indice}"
        precio.historial_clave = clave
        elementos = []
        for registro in por_precio.get((precio.id_store_id, precio.gtin_id), []):
            fecha = timezone.localtime(registro["created_at"])
            elemento = {
                "fecha": fecha.isoformat(),
                "precio_anterior": registro["old_price"],
                "precio_nuevo": registro["new_price"],
                "descuento_anterior": str(_descuento(registro["old_discount"])),
                "descuento_nuevo": str(_descuento(registro["new_discount"])),
            }
            if es_cambio_solo_disponibilidad(registro):
                elemento["cambio_disponibilidad"] = etiqueta_cambio_disponibilidad(
                    registro
                )
            elementos.append(elemento)
        historiales[clave] = elementos

    return historiales
