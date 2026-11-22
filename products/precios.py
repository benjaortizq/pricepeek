"""Consultas reutilizables para calcular y comparar los precios finales."""

from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    QuerySet,
    Value,
    Window,
)
from django.db.models.functions import Coalesce, Rank, RowNumber

from .models import Prices


def expresion_precio_final() -> ExpressionWrapper:
    """Expresión SQL reutilizable para calcular el precio con descuento."""
    return ExpressionWrapper(
        F("price")
        * (
            Value(Decimal("1"))
            - Coalesce(F("discount"), Value(Decimal("0")))
        ),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def anotar_precio_final(queryset: QuerySet) -> QuerySet:
    """Agrega el precio final después de aplicar el descuento."""
    return queryset.annotate(final_price=expresion_precio_final())


def precio_minimo_por_gtin(
    gtin: str, solo_disponibles: bool = True
) -> QuerySet:
    """Devuelve únicamente el precio final más bajo de un GTIN.

    Los precios nulos y, por defecto, los no disponibles se excluyen. Si dos
    tiendas ofrecen exactamente el mismo precio final, se elige el registro
    con el identificador más bajo para que el resultado sea determinista.
    """
    if not gtin:
        return Prices.objects.none()

    precios = Prices.objects.select_related("id_store", "currency").filter(
        gtin_id=gtin,
        price__isnull=False,
    )
    if solo_disponibles:
        precios = precios.filter(is_available=True)

    return (
        anotar_precio_final(precios)
        .annotate(ranking=Value(1))
        .order_by("final_price", "id")[:1]
    )


def precios_por_gtin(
    gtin: str, solo_disponibles: bool = True
) -> QuerySet:
    """Devuelve todos los precios de un GTIN ordenados por precio final.

    Los precios nulos y, por defecto, las ofertas no disponibles se excluyen.
    Los precios empatados reciben el mismo puesto de ranking.
    """
    if not gtin:
        return Prices.objects.none()

    precios = Prices.objects.select_related("id_store", "currency").filter(
        gtin_id=gtin,
        price__isnull=False,
    )
    if solo_disponibles:
        precios = precios.filter(is_available=True)

    return anotar_precio_final(precios).annotate(
        ranking=Window(Rank(), order_by=F("final_price").asc())
    ).order_by("final_price", "id_store__name", "id")


def con_precio_minimo(variantes):
    """Asigna a cada variante su precio disponible más bajo.

    La consulta se realiza una sola vez para todas las variantes recibidas.
    Cada variante queda con el atributo ``precio_minimo``; si no tiene un
    precio disponible, el atributo vale ``None``.
    """
    variantes = list(variantes)
    if not variantes:
        return variantes

    gtins = [variante.gtin for variante in variantes]
    precios = (
        Prices.objects.filter(
            gtin_id__in=gtins,
            is_available=True,
            price__isnull=False,
        )
        .select_related("id_store", "currency")
    )
    precios = anotar_precio_final(precios).annotate(
        posicion=Window(
            RowNumber(),
            partition_by=F("gtin_id"),
            order_by=(F("final_price").asc(), F("id")),
        ),
        ranking=Value(1),
    ).filter(posicion=1)

    minimos = {precio.gtin_id: precio for precio in precios}
    for variante in variantes:
        variante.precio_minimo = minimos.get(variante.gtin)
    return variantes


def agrupar_precios_por_gtin(variantes, precios):
    """Agrupa las ofertas por variante y separa el mejor precio del resto.

    Cada grupo contiene como máximo un precio destacado. Las demás ofertas,
    incluidas las que empatan con el mínimo, quedan en ``opciones``.
    """
    grupos = {}
    for variante in variantes:
        grupos[variante.gtin] = {
            "gtin": variante.gtin,
            "variante": variante,
            "mejor": None,
            "opciones": [],
        }

    for precio in precios:
        grupo = grupos.get(precio.gtin_id)
        if grupo is None:
            grupo = {
                "gtin": precio.gtin_id,
                "variante": precio.gtin,
                "mejor": None,
                "opciones": [],
            }
            grupos[precio.gtin_id] = grupo

        if getattr(precio, "es_mejor", False) and grupo["mejor"] is None:
            grupo["mejor"] = precio
        else:
            grupo["opciones"].append(precio)

    return list(grupos.values())
