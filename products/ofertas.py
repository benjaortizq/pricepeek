"""Las «Mejores ofertas del día» del inicio (frontend/html/index.html).

Una oferta es una presentación (GTIN) que se vende en dos o más comercios: van primero las de
mayor diferencia entre el precio más bajo y el más alto, en porcentaje.
"""

from collections import defaultdict

from django.db.models import Count

from .busqueda import con_imagen_variante
from .models import Categories, Prices, ProductVariants
from .precios import anotar_precio_final

OFERTAS_EN_INICIO = 4
OTROS_COMERCIOS_EN_LA_TARJETA = 2  # además del más barato, como en el diseño
CATEGORIAS_EN_INICIO = 4

ICONOS_DE_CATEGORIA = (
    ("electro", "kitchen"),
    ("abarrote", "shopping_basket"),
    ("super", "shopping_basket"),
    ("hogar", "chair"),
    ("higiene", "clean_hands"),
)


def mejores_ofertas(cantidad=OFERTAS_EN_INICIO):
    """Las presentaciones con más diferencia de precio entre comercios, con sus precios ordenados.

    Solo cuentan los precios disponibles. Si todos los comercios tienen el mismo precio, no es
    una oferta.
    """
    precios = (
        anotar_precio_final(
            Prices.objects.filter(is_available=True, price__isnull=False)
        )
        .select_related("id_store")
        .only(
            "id",
            "gtin",
            "price",
            "discount",
            "updated_at",
            "id_store",
            "id_store__name",
        )
    )
    por_gtin = defaultdict(list)
    for precio in precios:
        por_gtin[precio.gtin_id].append(precio)

    candidatas = []
    for gtin, lista in por_gtin.items():
        lista.sort(
            key=lambda precio: (
                precio.final_price,
                precio.id_store.name.strip().casefold(),
            )
        )
        minimo, maximo = lista[0].final_price, lista[-1].final_price
        if (
            len({precio.id_store_id for precio in lista}) < 2
            or not maximo
            or maximo <= minimo
        ):
            continue
        candidatas.append(
            ((maximo - minimo) / maximo, maximo - minimo, gtin, lista)
        )
    candidatas.sort(
        key=lambda candidata: (-candidata[0], -candidata[1], candidata[2])
    )
    elegidas = candidatas[:cantidad]

    variantes = {
        variante.gtin: variante
        for variante in con_imagen_variante(
            ProductVariants.objects.select_related("product__brand").filter(
                gtin__in=[c[2] for c in elegidas]
            )
        )
    }
    ofertas = []
    for proporcion, ahorro, gtin, lista in elegidas:
        mejor = lista[0]
        ofertas.append(
            {
                "variante": variantes[gtin],
                "mejor": mejor,
                "ahorro": ahorro,
                "porcentaje": round(proporcion * 100),
                "otros": [
                    {
                        "precio": precio,
                        "diferencia": precio.final_price - mejor.final_price,
                    }
                    for precio in lista[1 : 1 + OTROS_COMERCIOS_EN_LA_TARJETA]
                ],
                "comercios": len(lista),
            }
        )
    return ofertas


def ultima_verificacion(ofertas):
    """Cuándo se revisó por última vez alguno de los precios de las ofertas."""
    fechas = [
        precio.updated_at
        for oferta in ofertas
        for precio in [oferta["mejor"]]
        + [o["precio"] for o in oferta["otros"]]
    ]
    return max(fechas) if fechas else None


def icono_de_categoria(nombre):
    nombre = nombre.casefold()
    return next(
        (icono for clave, icono in ICONOS_DE_CATEGORIA if clave in nombre),
        "category",
    )


def categorias_del_inicio(cantidad=CATEGORIAS_EN_INICIO):
    """Las categorías con más productos, para las tarjetas del inicio."""
    categorias = list(
        Categories.objects.annotate(total=Count("products"))
        .filter(total__gt=0)
        .order_by("-total", "name")[:cantidad]
    )
    for categoria in categorias:
        categoria.icono = icono_de_categoria(categoria.name)
    return categorias
