"""Alertas de baja de precio de la lista de deseos (RF-24, UC-06)."""

import logging
from collections import defaultdict
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from products.models import Prices

from .models import WishlistItem

logger = logging.getLogger(__name__)


@dataclass
class ResultadoAlertas:
    revisados: int = 0
    productos_con_baja: int = 0
    correos_enviados: int = 0
    errores: int = 0


def precio_final(precio):
    return round(precio.price * (1 - (precio.discount or 0)))


def mejores_precios(items):
    """{(gtin, id de la moneda): (precio final, tienda)} con el precio disponible más bajo."""
    precios = (
        Prices.visibles.filter(
            gtin__in={item.variant.gtin for item in items},
            currency_id__in={item.currency_id for item in items},
            is_available=True,
        )
        .exclude(price__isnull=True)
        .select_related("id_store")
    )
    mejores = {}
    for precio in precios:
        clave = (precio.gtin_id, precio.currency_id)
        candidato = (precio_final(precio), precio.id_store.name.strip())
        if clave not in mejores or candidato < mejores[clave]:
            mejores[clave] = candidato
    return mejores


def colones(monto):
    return f"₡{monto:,}".replace(",", ".")


def enviar_correo(cliente, bajas):
    sitio = settings.SITE_URL.rstrip("/")
    lineas = []
    for item, anterior, nuevo, tienda in bajas:
        enlace = reverse("detalle_producto", kwargs={"pk": item.variant.product_id})
        lineas.append(
            f"- {item.variant.product.name}: de {colones(anterior)} a {colones(nuevo)} en {tienda}\n"
            f"  {sitio}{enlace}#precio-{item.variant.gtin}"
        )
    una_sola = len(bajas) == 1
    asunto = (
        "Bajó el precio de un producto de su lista de deseos"
        if una_sola
        else f"Bajó el precio de {len(bajas)} productos de su lista de deseos"
    )
    mensaje = (
        f"Hola{' ' + cliente.first_name if cliente.first_name else ''},\n\n"
        f"{'Bajó el precio de un producto' if una_sola else 'Bajó el precio de varios productos'} "
        "de su lista de deseos:\n\n"
        + "\n".join(lineas)
        + "\n\nPuede desactivar estas alertas en cualquier momento desde su perfil:\n"
        f"{sitio}{reverse('editar_perfil')}\n\n"
        "El equipo de PricePeek\n"
    )
    send_mail(asunto, mensaje, None, [cliente.email])


def revisar_alertas_de_baja_de_precio(ahora=None):
    """Avisa por correo a los clientes cuando baja el precio más bajo de un producto de su lista.

    Compara el precio más bajo disponible con el último precio registrado (`baseline_price`).
    Cada cliente recibe un solo correo por revisión, con todos sus productos que bajaron.
    """
    ahora = ahora or timezone.now()
    resultado = ResultadoAlertas()
    items = list(
        WishlistItem.objects.filter(
            alert_enabled=True, user__is_active=True, user__active_alerts=True
        )
        .select_related("user", "variant__product", "currency")
        .order_by("user_id", "id")
    )
    if not items:
        return resultado

    mejores = mejores_precios(items)
    por_actualizar = []
    bajas_por_cliente = defaultdict(list)

    for item in items:
        resultado.revisados += 1
        actual = mejores.get((item.variant.gtin, item.currency_id))
        if actual is None:
            continue  # sin precio disponible: se conserva el último precio registrado
        nuevo, tienda = actual
        anterior = item.baseline_price
        if anterior is not None and nuevo < anterior:
            bajas_por_cliente[item.user].append((item, anterior, nuevo, tienda))
        elif anterior != nuevo:
            item.baseline_price = nuevo  # primer precio registrado, o el precio subió
            por_actualizar.append(item)

    for cliente, bajas in bajas_por_cliente.items():
        try:
            enviar_correo(cliente, bajas)
        except Exception:
            # No se actualiza nada: la baja se vuelve a detectar en la próxima revisión.
            resultado.errores += 1
            logger.exception("No se pudo enviar la alerta de baja de precio a %s", cliente.email)
            continue
        for item, _anterior, nuevo, _tienda in bajas:
            item.baseline_price = nuevo
            item.last_notified_price = nuevo
            item.last_notified_at = ahora
            por_actualizar.append(item)
        resultado.correos_enviados += 1
        resultado.productos_con_baja += len(bajas)

    WishlistItem.objects.bulk_update(
        por_actualizar, ["baseline_price", "last_notified_price", "last_notified_at"]
    )
    return resultado
