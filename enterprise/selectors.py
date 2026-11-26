"""Consultas de catálogo y comparación competitiva del portal de empresas."""

from datetime import timedelta

from django.conf import settings
from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.utils import timezone

from core.translations import translate_text_lazy
from products.models import Prices
from products.precios import expresion_precio_final

COMPETITIVIDAD_VERDE = "green"
COMPETITIVIDAD_AMARILLO = "yellow"
COMPETITIVIDAD_ROJO = "red"
COMPETITIVIDAD_NEUTRO = "neutral"

PRODUCTOS_POR_PAGINA = 20


def _competidor_menor(store_id):
    competidores = (
        Prices.visibles.filter(
            gtin_id=OuterRef("gtin_id"),
            is_available=True,
            price__isnull=False,
        )
        .exclude(id_store_id=store_id)
        .annotate(final_price=expresion_precio_final())
        .order_by("final_price", "id")
    )
    return Subquery(
        competidores.values("final_price")[:1],
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def catalogo_base(store):
    """Catálogo de una tienda con precio final y mínimo competidor anotados."""
    return (
        Prices.objects.filter(id_store_id=store.pk)
        .select_related(
            "gtin__product__brand",
            "gtin__product__category",
            "currency",
        )
        .annotate(
            final_price=expresion_precio_final(),
            competitor_price=_competidor_menor(store.pk),
        )
    )


def _anotar_competitividad(queryset):
    return queryset.annotate(
        competitiveness=Case(
            When(
                Q(is_available=False)
                | Q(price__isnull=True)
                | Q(final_price__isnull=True)
                | Q(competitor_price__isnull=True),
                then=Value(COMPETITIVIDAD_NEUTRO),
            ),
            When(
                Q(final_price__lt=F("competitor_price")),
                then=Value(COMPETITIVIDAD_VERDE),
            ),
            When(
                Q(final_price=F("competitor_price")),
                then=Value(COMPETITIVIDAD_AMARILLO),
            ),
            default=Value(COMPETITIVIDAD_ROJO),
            output_field=CharField(),
        )
    )


def filtrar_catalogo(queryset, busqueda="", estado="", competitividad="", categoria="", marca="", orden=""):
    """Aplica búsqueda, filtros y orden del catálogo."""
    if busqueda:
        queryset = queryset.filter(
            Q(gtin__gtin__icontains=busqueda)
            | Q(gtin__name__icontains=busqueda)
            | Q(gtin__product__name__icontains=busqueda)
            | Q(gtin__product__brand__name__icontains=busqueda)
        )
    if estado == "available":
        queryset = queryset.filter(is_available=True)
    elif estado == "unavailable":
        queryset = queryset.filter(is_available=False)
    if competitividad:
        queryset = queryset.filter(competitiveness=competitividad)
    if categoria:
        try:
            categoria = int(categoria)
        except (TypeError, ValueError):
            return queryset.none()
        if categoria <= 0 or categoria > 2**63 - 1:
            return queryset.none()
        queryset = queryset.filter(gtin__product__category_id=categoria)
    if marca:
        try:
            marca = int(marca)
        except (TypeError, ValueError):
            return queryset.none()
        if marca <= 0 or marca > 2**63 - 1:
            return queryset.none()
        queryset = queryset.filter(gtin__product__brand_id=marca)

    ordenes = {
        "name": ("gtin__product__name", "gtin__name"),
        "price_asc": ("final_price", "pk"),
        "price_desc": ("-final_price", "pk"),
        "updated": ("-updated_at", "pk"),
    }
    return queryset.order_by(*ordenes.get(orden, ordenes["updated"]))


def catalogo_de_tienda(store, parametros=None):
    parametros = parametros or {}
    queryset = _anotar_competitividad(catalogo_base(store))
    return filtrar_catalogo(
        queryset,
        busqueda=parametros.get("q", ""),
        estado=parametros.get("estado", ""),
        competitividad=parametros.get("competitividad", ""),
        categoria=parametros.get("categoria", ""),
        marca=parametros.get("marca", ""),
        orden=parametros.get("orden", ""),
    )


def obtener_precio_de_tienda(store, price_id):
    """Devuelve un precio únicamente si pertenece a la tienda indicada."""
    return (
        _anotar_competitividad(catalogo_base(store))
        .filter(pk=price_id)
        .first()
    )


def limite_precio_desactualizado(ahora=None):
    """Devuelve el límite timezone-aware para considerar un precio antiguo."""
    ahora = ahora or timezone.now()
    if timezone.is_naive(ahora):
        ahora = timezone.make_aware(ahora, timezone.get_current_timezone())
    return ahora - timedelta(days=settings.STALE_PRICE_DAYS)


def estadisticas_catalogo(store, ahora=None):
    """Totales y clasificación competitiva de la tienda."""
    ahora = ahora or timezone.now()
    queryset = _anotar_competitividad(catalogo_base(store))
    conteos = {
        fila["competitiveness"]: fila["total"]
        for fila in queryset.values("competitiveness").annotate(total=Count("id"))
    }
    total = queryset.count()
    activos = queryset.filter(is_available=True).count()
    inactivos = total - activos
    limite = limite_precio_desactualizado(ahora)
    sin_cambios = queryset.filter(updated_at__lte=limite).count()
    sobre_mercado = conteos.get(COMPETITIVIDAD_ROJO, 0)
    requiere_atencion = queryset.filter(
        Q(competitiveness=COMPETITIVIDAD_ROJO)
        | Q(is_available=False)
        | Q(price__isnull=True)
        | Q(updated_at__lte=limite)
        | Q(product_web_url__isnull=True)
        | Q(product_web_url="")
    ).count()
    return {
        "total": total,
        "activos": activos,
        "inactivos": inactivos,
        "verde": conteos.get(COMPETITIVIDAD_VERDE, 0),
        "amarillo": conteos.get(COMPETITIVIDAD_AMARILLO, 0),
        "rojo": sobre_mercado,
        "neutro": conteos.get(COMPETITIVIDAD_NEUTRO, 0),
        "sin_cambios": sin_cambios,
        "sobre_mercado": sobre_mercado,
        "requieren_atencion": requiere_atencion,
    }


def problemas_de_precio(precio, ahora=None):
    """Detecta problemas del precio propio y propone una acción."""
    ahora = ahora or timezone.now()
    problemas = []
    if not precio.is_available:
        problemas.append(
            {
                "key": "unavailable",
                "title": translate_text_lazy("El producto no está disponible"),
                "description": translate_text_lazy(
                    "Active la oferta o actualice su precio."
                ),
                "action_label": translate_text_lazy("Editar disponibilidad"),
            }
        )
    if precio.price is None:
        problemas.append(
            {
                "key": "missing_price",
                "title": translate_text_lazy("No hay un precio registrado"),
                "description": translate_text_lazy(
                    "Agregue un precio válido para volver a comparar la oferta."
                ),
                "action_label": translate_text_lazy("Agregar precio"),
            }
        )
    if precio.competitiveness == COMPETITIVIDAD_ROJO:
        problemas.append(
            {
                "key": "above_market",
                "title": translate_text_lazy("El precio está por encima del mercado"),
                "description": translate_text_lazy(
                    "Revise el precio o aplique un descuento para competir."
                ),
                "action_label": translate_text_lazy("Revisar precio"),
            }
        )
    if precio.updated_at and precio.updated_at <= limite_precio_desactualizado(ahora):
        problemas.append(
            {
                "key": "stale",
                "title": translate_text_lazy(
                    "El precio no cambia desde hace {dias} días o más",
                    dias=settings.STALE_PRICE_DAYS,
                ),
                "description": translate_text_lazy(
                    "Confirme que la oferta y el precio siguen vigentes."
                ),
                "action_label": translate_text_lazy("Actualizar precio"),
            }
        )
    if not (precio.product_web_url or "").strip():
        problemas.append(
            {
                "key": "missing_url",
                "title": translate_text_lazy("Falta el enlace del producto"),
                "description": translate_text_lazy(
                    "Agregue el enlace donde el cliente puede encontrar la oferta."
                ),
                "action_label": translate_text_lazy("Agregar enlace"),
            }
        )
    producto = precio.gtin.product
    if not (producto.description or "").strip():
        problemas.append(
            {
                "key": "missing_description",
                "title": translate_text_lazy(
                    "La descripción del producto está incompleta"
                ),
                "description": translate_text_lazy(
                    "La información canónica es compartida y debe revisarse en el catálogo."
                ),
                "action_label": translate_text_lazy("Ver catálogo"),
            }
        )
    if not precio.gtin.attributes:
        problemas.append(
            {
                "key": "missing_attributes",
                "title": translate_text_lazy("Faltan características del producto"),
                "description": translate_text_lazy(
                    "La información canónica es compartida y debe revisarse en el catálogo."
                ),
                "action_label": translate_text_lazy("Ver catálogo"),
            }
        )
    return problemas
