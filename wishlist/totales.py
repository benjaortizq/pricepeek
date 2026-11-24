"""Total de la lista de deseos en cada comercio (RF-23)."""

from dataclasses import dataclass

from products.models import Prices


@dataclass
class TotalTienda:
    tienda: str
    total: int  # una unidad de cada producto que el comercio ofrece
    disponibles: int
    faltantes: list  # nombres de los productos que el comercio no tiene disponibles
    completa: bool  # ofrece todos los productos de la lista
    mas_barata: bool = False  # el menor total entre los comercios que ofrecen todo


@dataclass
class ComparativaMoneda:
    moneda: object
    productos: int
    tiendas: list
    hay_completa: bool


def precio_final(precio):
    return round(precio.price * (1 - (precio.discount or 0)))


def totales_por_tienda(items):
    """Compara el costo de la lista de deseos en cada comercio, una moneda a la vez.

    Los totales de monedas distintas no se pueden sumar, por eso se devuelve una
    comparativa por moneda (en la práctica, casi siempre solo colones).
    """
    por_moneda = {}
    for item in items:
        por_moneda.setdefault(item.currency_id, []).append(item)
    return [_comparar(productos) for productos in por_moneda.values()]


def _comparar(productos):
    moneda = productos[0].currency
    precios = (
        Prices.objects.filter(
            gtin__in=[item.variant.gtin for item in productos],
            currency_id=moneda.pk,
            is_available=True,
        )
        .exclude(price__isnull=True)
        .select_related("id_store")
    )
    nombres = {}
    finales = {}  # {id de la tienda: {gtin: precio final}}
    for precio in precios:
        nombres[precio.id_store_id] = precio.id_store.name.strip()
        finales.setdefault(precio.id_store_id, {})[precio.gtin_id] = precio_final(precio)

    filas = []
    for id_tienda, por_gtin in finales.items():
        faltantes = [
            item.variant.product.name for item in productos if item.variant.gtin not in por_gtin
        ]
        filas.append(
            TotalTienda(
                tienda=nombres[id_tienda],
                total=sum(por_gtin.values()),
                disponibles=len(por_gtin),
                faltantes=faltantes,
                completa=not faltantes,
            )
        )

    completas = [fila for fila in filas if fila.completa]
    if completas:
        minimo = min(fila.total for fila in completas)
        for fila in completas:
            fila.mas_barata = fila.total == minimo  # si hay empate, se destacan todos

    filas.sort(key=lambda fila: (len(fila.faltantes), fila.total, fila.tienda))
    return ComparativaMoneda(moneda, len(productos), filas, bool(completas))
