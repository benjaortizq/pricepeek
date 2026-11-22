"""Qué productos son populares ahora: cuántas personas distintas vieron cada uno esta semana.

Cada vez que alguien abre el detalle de un producto se guarda una visita (ProductView), una sola
por visitante, producto y hora: recargar la página no suma. La popularidad de un producto es
cuántos visitantes distintos tuvo en los últimos DIAS_DE_POPULARIDAD días.

Solo cuentan los clientes y los visitantes anónimos: los administradores y las empresas no son
interés de compra, y los robots (buscadores, vistas previas de enlaces) tampoco.
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
    if _ROBOT.search(request.headers.get("User-Agent", "")):
        return None
    usuario = request.user
    if usuario.is_authenticated:
        return f"u{usuario.pk}" if usuario.role == "client" else None
    if not request.session.session_key:
        request.session.save()  # le da una sesión para reconocerlo si vuelve
    return f"s{request.session.session_key}"


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


def popularidad_reciente():
    """Cuántos visitantes distintos tuvo el producto (``OuterRef("pk")``) en los últimos días."""
    desde = timezone.now() - timedelta(days=DIAS_DE_POPULARIDAD)
    visitantes = (
        ProductView.objects.filter(product_id=OuterRef("pk"), hour__gte=desde)
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
