"""Historial de precios de cada tienda (issue «Historial de precios»).

prices guarda solo el precio vigente de cada tienda y presentación. Cada vez
que cambia el precio de lista, el descuento o la disponibilidad, registrar()
agrega una fila a price_history (products.models.PriceHistory). Lo llaman
todos los lugares que escriben en prices: la obtención de datos
(ingestion/actualizacion.py), la vinculación de productos
(ingestion/productos_tienda.py) y el portal de empresas
(enterprise/services.py).

Con esas filas se dibuja el gráfico del detalle del producto (los últimos
MESES_DEL_GRAFICO meses) y la comparativa del panel de administración
(products/vistas_historial.py).
"""

import calendar
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import F, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.formats import date_format

from .models import PriceHistory, Prices, Stores
from .templatetags.precios import miles

MESES_DEL_GRAFICO = 6
# Colores de las líneas: frontend/css/historial-precios.css (--serie-1 a 8).
COLORES = 8

# Qué pasó en cada registro (tipo_de_cambio y filtro_de_cambio).
NUEVO = "nuevo"
BAJO = "bajo"
SUBIO = "subio"
DISPONIBLE = "disponible"
AGOTADO = "agotado"
OTRO = "otro"

_MISMA_DISPONIBILIDAD = Q(was_available=True, is_available=True) | Q(
    was_available=False, is_available=False
)
_FILTROS = {
    NUEVO: Q(was_available__isnull=True),
    BAJO: _MISMA_DISPONIBILIDAD & Q(final_price__lt=F("previous_final_price")),
    SUBIO: _MISMA_DISPONIBILIDAD
    & Q(final_price__gt=F("previous_final_price")),
    DISPONIBLE: Q(was_available=False, is_available=True),
    AGOTADO: Q(was_available=True, is_available=False),
}


def filtro_de_cambio(tipo):
    """El filtro de la base para los registros de ese tipo de cambio: el
    mismo criterio de tipo_de_cambio, para las pestañas del panel."""
    return _FILTROS[tipo]


def tipo_de_cambio(registro):
    """NUEVO, BAJO, SUBIO, DISPONIBLE, AGOTADO u OTRO (cambió el precio de
    lista o el descuento, pero no lo que paga el cliente)."""
    if registro.was_available is None:
        return NUEVO
    if registro.is_available != registro.was_available:
        return DISPONIBLE if registro.is_available else AGOTADO
    antes, ahora = registro.previous_final_price, registro.final_price
    if antes is None or ahora is None or antes == ahora:
        return OTRO
    return BAJO if ahora < antes else SUBIO


def precio_final(precio, descuento):
    """Lo que paga el cliente, redondeado como en el detalle del producto."""
    if precio is None:
        return None
    final = Decimal(precio) * (1 - Decimal(descuento or 0))
    return int(final.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def nombre_de_tienda(tienda):
    """«Walmart\\n» -> «Walmart»: algunos nombres traen saltos de línea."""
    return " ".join(tienda.name.split())


def registrar(precios, origen, cuando=None):
    """Agrega al historial los precios que cambiaron desde su último registro.

    precios: filas de Prices o sus ids. Se lee de la base cómo quedaron, así
    sirve igual después de un save() que de un update(). Si nada cambió no se
    agrega nada, así que llamarla de más no repite registros. Devuelve las
    filas nuevas.
    """
    ids = [getattr(precio, "pk", precio) for precio in precios]
    filas = list(
        Prices.objects.filter(pk__in=ids).values(
            "id_store_id",
            "gtin_id",
            "currency_id",
            "price",
            "discount",
            "is_available",
        )
    )
    if not filas:
        return []
    ultimos = ultimos_registros(
        {(fila["id_store_id"], fila["gtin_id"]) for fila in filas}
    )
    cuando = cuando or timezone.now()
    nuevas = []
    for fila in filas:
        anterior = ultimos.get((fila["id_store_id"], fila["gtin_id"]))
        descuento = fila["discount"] or Decimal("0")
        estado = (fila["price"], descuento, fila["is_available"])
        if anterior is not None and estado == (
            anterior.price,
            anterior.discount,
            anterior.is_available,
        ):
            continue
        nuevas.append(
            PriceHistory(
                store_id=fila["id_store_id"],
                gtin_id=fila["gtin_id"],
                currency_id=fila["currency_id"],
                price=fila["price"],
                discount=descuento,
                final_price=precio_final(fila["price"], descuento),
                is_available=fila["is_available"],
                previous_final_price=(
                    anterior.final_price if anterior else None
                ),
                was_available=anterior.is_available if anterior else None,
                source=origen,
                recorded_at=cuando,
            )
        )
    return PriceHistory.objects.bulk_create(nuevas)


def ultimos_registros(claves, antes_de=None):
    """{(tienda, gtin): el último registro} de cada par de claves.

    Con antes_de, el último registro anterior a esa fecha (el precio que
    tenía la tienda cuando empieza el gráfico).
    """
    if not claves:
        return {}
    anteriores = PriceHistory.objects.filter(
        store_id=OuterRef("store_id"), gtin_id=OuterRef("gtin_id")
    )
    registros = PriceHistory.objects.select_related("currency").filter(
        store_id__in={tienda for tienda, _ in claves},
        gtin_id__in={gtin for _, gtin in claves},
    )
    if antes_de is not None:
        anteriores = anteriores.filter(recorded_at__lt=antes_de)
        registros = registros.filter(recorded_at__lt=antes_de)
    ultimo = anteriores.order_by("-recorded_at", "-id").values("pk")[:1]
    return {
        (registro.store_id, registro.gtin_id): registro
        for registro in registros.filter(pk=Subquery(ultimo))
        if (registro.store_id, registro.gtin_id) in claves
    }


def inicio_del_grafico(ahora=None):
    """Hace MESES_DEL_GRAFICO meses, a la misma hora de Costa Rica.

    Del 31 de agosto se va al 28 o 29 de febrero: el día se recorta al
    último del mes.
    """
    ahora = timezone.localtime(ahora or timezone.now())
    mes = ahora.month - MESES_DEL_GRAFICO
    anio = ahora.year + (mes - 1) // 12
    mes = (mes - 1) % 12 + 1
    dia = min(ahora.day, calendar.monthrange(anio, mes)[1])
    return ahora.replace(year=anio, month=mes, day=dia)


def colores_de_tiendas(tiendas):
    """{id de la tienda: (número de color, punteada)}.

    El color sigue a la tienda, no a su precio: se reparte por id, así una
    tienda tiene el mismo color en todas las presentaciones del producto.
    Pasadas las 8 tiendas los colores se repiten con la línea punteada.
    """
    return {
        tienda: (posicion % COLORES + 1, posicion >= COLORES)
        for posicion, tienda in enumerate(sorted(tiendas))
    }


def marcas_de_meses(desde, hasta):
    """[{"t": milisegundos, "texto": "Jun"}, …]: el primer día de cada mes
    entre las dos fechas (hora de Costa Rica), para el eje del gráfico."""
    fecha = timezone.localtime(desde).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    marcas = []
    while fecha <= hasta:
        if fecha >= desde:
            marcas.append(
                {"t": _milisegundos(fecha), "texto": date_format(fecha, "M")}
            )
        siguiente = fecha.month % 12 + 1
        fecha = fecha.replace(
            year=fecha.year + (fecha.month == 12), month=siguiente
        )
    return marcas


def _milisegundos(fecha):
    return int(fecha.timestamp() * 1000)


def _valor(registro):
    """El precio que se dibuja: ninguno si la tienda no lo tenía disponible."""
    return registro.final_price if registro.is_available else None


def registros_del_periodo(claves, desde):
    """{(tienda, gtin): [registros]} desde esa fecha, del más viejo al más
    nuevo, empezando por el que estaba vigente en esa fecha."""
    resultado = defaultdict(list)
    for clave, registro in ultimos_registros(claves, antes_de=desde).items():
        resultado[clave].append(registro)
    for registro in (
        PriceHistory.objects.select_related("currency")
        .filter(
            gtin_id__in={gtin for _, gtin in claves}, recorded_at__gte=desde
        )
        .order_by("recorded_at", "id")
    ):
        clave = (registro.store_id, registro.gtin_id)
        if clave in claves:
            resultado[clave].append(registro)
    return resultado


def graficos_del_producto(precios_actuales, ahora=None, colores=None):
    """Los datos del gráfico de cada presentación: {gtin: grafico}.

    precios_actuales: las filas de prices que muestra el detalle del producto
    (con id_store y currency cargados). Hay una línea por cada una de esas
    tiendas, así el gráfico muestra las mismas que la tabla de precios.
    colores: los de colores_de_tiendas, si ya se repartieron.
    """
    ahora = ahora or timezone.now()
    desde = inicio_del_grafico(ahora)
    precios_actuales = list(precios_actuales)
    claves = {
        (precio.id_store_id, precio.gtin_id) for precio in precios_actuales
    }
    registros = registros_del_periodo(claves, desde)
    colores = colores or colores_de_tiendas({tienda for tienda, _ in claves})

    por_gtin = defaultdict(list)
    for precio in precios_actuales:
        por_gtin[precio.gtin_id].append(precio)
    graficos = {}
    for gtin, precios in por_gtin.items():
        precios.sort(key=lambda precio: colores[precio.id_store_id])
        series, columnas = [], []
        for precio in precios:
            puntos = _puntos(
                registros.get((precio.id_store_id, gtin), []),
                precio,
                desde,
                ahora,
            )
            color, punteada = colores[precio.id_store_id]
            nombre = nombre_de_tienda(precio.id_store)
            series.append(
                {
                    "tienda": nombre,
                    "color": color,
                    "punteada": punteada,
                    "puntos": puntos,
                    "actual": puntos[-1][1],
                }
            )
            columnas.append(
                {
                    "id": precio.id_store_id,
                    "nombre": nombre,
                    "color": color,
                    "punteada": punteada,
                }
            )
        inicio = min(serie["puntos"][0][0] for serie in series)
        graficos[gtin] = {
            "datos": {
                "desde": _milisegundos(desde),
                "hasta": _milisegundos(ahora),
                "simbolo": precios[0].currency.symbol,
                "series": series,
                "meses": marcas_de_meses(desde, ahora),
            },
            "series": series,
            "simbolo": precios[0].currency.symbol,
            # La misma información en una tabla, para leerla sin el gráfico.
            "tabla": armar_comparativa(
                {
                    clave: lista
                    for clave, lista in registros.items()
                    if clave[1] == gtin
                },
                columnas,
                desde,
            ),
            "con_precio": any(
                valor is not None
                for serie in series
                for _, valor in serie["puntos"]
            ),
            # Si el historial empezó después del inicio del gráfico, desde
            # cuándo hay datos.
            "empieza_el": (
                datetime.fromtimestamp(
                    inicio / 1000, tz=timezone.get_current_timezone()
                )
                if inicio > _milisegundos(desde)
                else None
            ),
        }
    return graficos


def _puntos(registros, precio, desde, ahora):
    """[[milisegundos, precio final o None], …]: la línea escalonada de una
    tienda, desde su primer registro (o el inicio del gráfico) hasta ahora."""
    if registros:
        cambios = [
            (max(registro.recorded_at, desde), _valor(registro))
            for registro in registros
        ]
    else:
        # Tiene precio pero todavía no tiene historial (por ejemplo, si se
        # cargó directo en la base): se toma el precio actual.
        valor = (
            precio_final(precio.price, precio.discount)
            if precio.is_available
            else None
        )
        cambios = [(max(min(precio.updated_at, ahora), desde), valor)]
    cambios.append((ahora, cambios[-1][1]))
    puntos = []
    for fecha, valor in cambios:
        momento = _milisegundos(fecha)
        if puntos and puntos[-1][0] == momento:
            puntos[-1][1] = valor  # en el mismo instante vale el último
        else:
            puntos.append([momento, valor])
    return puntos


def comparativa(gtin, desde=None, colores=None):
    """El precio de cada tienda en cada actualización de una presentación.

    Con desde, solo los registros desde esa fecha. colores: los de
    colores_de_tiendas, si ya se repartieron. Devuelve lo mismo que
    armar_comparativa.
    """
    registros = PriceHistory.objects.select_related("currency").filter(
        gtin_id=gtin
    )
    tiendas = set(registros.values_list("store_id", flat=True).distinct())
    claves = {(tienda, gtin) for tienda in tiendas}
    if desde is None:
        por_clave = defaultdict(list)
        for registro in registros.order_by("recorded_at", "id"):
            por_clave[(registro.store_id, gtin)].append(registro)
    else:
        por_clave = registros_del_periodo(claves, desde)
    colores = colores or colores_de_tiendas(tiendas)
    nombres = {
        tienda.pk: nombre_de_tienda(tienda)
        for tienda in Stores.objects.filter(pk__in=tiendas)
    }
    columnas = [
        {
            "id": tienda,
            "nombre": nombres.get(tienda, f"#{tienda}"),
            "color": colores[tienda][0],
            "punteada": colores[tienda][1],
        }
        for tienda in sorted(tiendas, key=colores.get)
    ]
    return armar_comparativa(por_clave, columnas, desde)


def armar_comparativa(por_clave, columnas, desde=None):
    """(columnas, filas) de la comparativa.

    por_clave: {(tienda, gtin): [registros]} de una sola presentación.
    columnas: las tiendas ({"id", "nombre", "color", "punteada"}), en el
    orden de sus colores. filas: una por registro del historial, la más
    reciente primero, con la tienda que cambió y «celdas»: el precio que
    tenía cada tienda en ese momento. Los registros anteriores a desde no son
    filas: solo dan el precio con el que empieza cada tienda.
    """
    nombres = {columna["id"]: columna["nombre"] for columna in columnas}
    eventos = sorted(
        (
            registro
            for (tienda, _), lista in por_clave.items()
            if tienda in nombres
            for registro in lista
        ),
        key=lambda registro: (registro.recorded_at, registro.pk),
    )
    estado = {}
    filas = []
    for registro in eventos:
        estado[registro.store_id] = registro
        if desde is not None and registro.recorded_at < desde:
            continue
        disponibles = [
            actual.final_price
            for actual in estado.values()
            if actual.is_available and actual.final_price is not None
        ]
        mejor = min(disponibles) if disponibles else None
        filas.append(
            {
                "registro": registro,
                "tienda": nombres[registro.store_id],
                "cambio": tipo_de_cambio(registro),
                "mejor": mejor,
                "celdas": [
                    _celda(estado.get(columna["id"]), registro, mejor)
                    for columna in columnas
                ],
            }
        )
    filas.reverse()
    return columnas, filas


def _celda(actual, registro, mejor):
    if actual is None:
        return {"sin_datos": True}
    cambio = tipo_de_cambio(actual) if actual is registro else ""
    return {
        "final": actual.final_price,
        "disponible": actual.is_available,
        "cambio": cambio,
        "diferencia": diferencia(actual) if cambio else None,
        "es_mejor": (
            actual.is_available
            and actual.final_price is not None
            and actual.final_price == mejor
        ),
    }


def diferencia(registro):
    """{"monto": "₡60", "porcentaje": "3"} de un registro que bajó o subió;
    None en los demás."""
    if tipo_de_cambio(registro) not in (BAJO, SUBIO):
        return None
    cambio = abs(registro.final_price - registro.previous_final_price)
    porcentaje = round(cambio * 100 / registro.previous_final_price)
    return {
        "monto": f"{registro.currency.symbol}{miles(cambio)}",
        "porcentaje": str(porcentaje) if porcentaje else "<1",
    }
