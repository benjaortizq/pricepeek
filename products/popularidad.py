"""Qué productos son populares ahora: cuántas personas distintas vieron cada uno esta semana.

Cada vez que alguien abre el detalle de un producto se guarda una visita (ProductView), una sola
por cliente, producto y hora: recargar la página no suma. No se registran visitas anónimas. La
popularidad de un producto es cuántos clientes distintos lo vieron en los últimos días.

Solo cuentan los clientes con sesión; los administradores, las empresas y los robots tampoco.
"""

import logging
import re
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import ProductView

DIAS_DE_POPULARIDAD = 7

_ROBOT = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|curl|wget|python-requests|headless",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _visitante(request):
    """«u<id>» para el cliente que inició sesión y «s<clave>» para el anónimo; None si no cuenta."""
    # Las visitas anónimas dejaron de guardarse; solo se procesa la sesión del cliente.
    if _ROBOT.search(request.headers.get("User-Agent", "")):
        return None
    usuario = request.user
    if usuario.is_authenticated and usuario.role == "client":
        return f"u{usuario.pk}"
    return None


def registrar_visita(request, producto_id):
    """Guarda que el visitante vio el producto en esta hora; si ya estaba guardado, no hace nada."""
    visitante = _visitante(request)
    if visitante is None:
        return
    visita = ProductView(
        product_id=producto_id,
        visitor=visitante,
        user=request.user if request.user.is_authenticated else None,
        hour=timezone.now().replace(minute=0, second=0, microsecond=0),
    )
    try:
        with transaction.atomic():
            # ignore_conflicts: si ya lo vio en esta hora, la base no guarda otra fila.
            ProductView.objects.bulk_create([visita], ignore_conflicts=True)
    except DatabaseError:
        # Contar la visita no puede dejar a la persona sin ver el producto.
        logger.exception("No se pudo guardar la visita al producto %s", producto_id)


def popularidad_reciente(producto="pk"):
    """Cuántos clientes distintos tuvieron el producto en los últimos días.

    ``producto`` es dónde está el id del producto en la consulta de afuera: "pk" en una de
    productos, "gtin__product_id" en una de precios.
    """
    desde = timezone.now() - timedelta(days=DIAS_DE_POPULARIDAD)
    visitantes = (
        ProductView.objects.filter(product_id=OuterRef(producto), hour__gte=desde)
        .values("product_id")
        .annotate(total=Count("visitor", distinct=True))
        .values("total")
    )
    return Coalesce(Subquery(visitantes, output_field=IntegerField()), Value(0))


def mas_populares(productos):
    """Ordena los productos del más popular al menos; los empates y los que nadie vio, por nombre.

    Le pone a cada uno ``.popularidad``. No agrega consultas: la popularidad va dentro de la misma
    consulta de los productos.
    """
    return productos.annotate(popularidad=popularidad_reciente()).order_by("-popularidad", "name")
