"""El historial de precios en el panel de administración.

Issue «Historial de precios». Dos pantallas: todos los cambios de precio de
las tiendas, con filtros, y la comparativa de una presentación (el precio de
cada tienda en cada actualización, con el gráfico de los últimos 6 meses).
Los registros salen de price_history (products/historial.py).
"""

from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import User
from core.panel import indicador, pestanas, plural

from .historial import (
    AGOTADO,
    BAJO,
    DISPONIBLE,
    NUEVO,
    SUBIO,
    colores_de_tiendas,
    comparativa,
    diferencia,
    filtro_de_cambio,
    graficos_del_producto,
    inicio_del_grafico,
    nombre_de_tienda,
    precio_final,
    tipo_de_cambio,
)
from .models import PriceHistory, Prices, ProductVariants, Stores
from .templatetags.precios import miles

CAMBIOS_POR_PAGINA = 25
FILAS_POR_PAGINA = 25

# Pestañas de la lista: valor del parámetro «cambio» -> filtro.
TIPOS = {
    "bajaron": filtro_de_cambio(BAJO),
    "subieron": filtro_de_cambio(SUBIO),
    "disponibilidad": filtro_de_cambio(DISPONIBLE) | filtro_de_cambio(AGOTADO),
    "nuevos": filtro_de_cambio(NUEVO),
}
# Periodo: valor del parámetro -> (días, texto). None: todo el historial.
PERIODOS = {
    "7": (7, "Últimos 7 días"),
    "30": (30, "Últimos 30 días"),
    "180": (180, "Últimos 6 meses"),
    "todo": (None, "Todo el historial"),
}
PERIODO_INICIAL = "30"


@role_required(User.Role.ADMIN)
def historial_de_precios(request):
    """Cada cambio de precio de las tiendas, el más reciente primero."""
    busqueda = request.GET.get("q", "").strip()
    tipo = request.GET.get("cambio", "")
    if tipo not in TIPOS:
        tipo = ""
    periodo = request.GET.get("periodo", PERIODO_INICIAL)
    if periodo not in PERIODOS:
        periodo = PERIODO_INICIAL
    tiendas = sorted(Stores.objects.all(), key=nombre_de_tienda)
    for opcion in tiendas:
        opcion.nombre = nombre_de_tienda(opcion)
    tienda = request.GET.get("tienda", "")
    if tienda not in {str(opcion.pk) for opcion in tiendas}:
        tienda = ""

    # El precio con que empezó el historial no es un cambio: está en la
    # comparativa de cada presentación, no aquí.
    cambios = PriceHistory.objects.exclude(source=PriceHistory.Source.INICIAL)
    dias = PERIODOS[periodo][0]
    if dias is not None:
        cambios = cambios.filter(
            recorded_at__gte=timezone.now() - timedelta(days=dias)
        )
    if tienda:
        cambios = cambios.filter(store_id=tienda)
    if busqueda:
        cambios = cambios.filter(
            Q(gtin__gtin__icontains=busqueda)
            | Q(gtin__name__icontains=busqueda)
            | Q(gtin__product__name__icontains=busqueda)
        )

    total = cambios.count()
    cantidades = {
        clave: cambios.filter(filtro).count()
        for clave, filtro in TIPOS.items()
    }
    lista = cambios.filter(TIPOS[tipo]) if tipo else cambios
    pagina = Paginator(
        lista.select_related("store", "gtin", "currency").order_by(
            "-recorded_at", "-id"
        ),
        CAMBIOS_POR_PAGINA,
    ).get_page(request.GET.get("pagina"))
    for registro in pagina.object_list:
        registro.tienda = nombre_de_tienda(registro.store)
        registro.cambio = tipo_de_cambio(registro)
        registro.diferencia = diferencia(registro)

    filtros = {"q": busqueda, "tienda": tienda}
    if periodo != PERIODO_INICIAL:
        filtros["periodo"] = periodo
    texto_periodo = PERIODOS[periodo][1]
    return render(
        request,
        "products/historial_admin.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "tipo": tipo,
            "periodo": periodo,
            "periodos": [
                (valor, texto) for valor, (_, texto) in PERIODOS.items()
            ],
            "tiendas": tiendas,
            "tienda": tienda,
            "filtrado": bool(busqueda or tienda or periodo != PERIODO_INICIAL),
            "kpis": [
                indicador(
                    "Cambios de precio",
                    total,
                    pie_izq=texto_periodo,
                    destacada=True,
                ),
                indicador(
                    "Bajaron",
                    cantidades["bajaron"],
                    icono="arrow_downward",
                    insignia="Más baratos" if cantidades["bajaron"] else "",
                    tono="bien",
                    pie_izq="El precio final bajó",
                ),
                indicador(
                    "Subieron",
                    cantidades["subieron"],
                    icono="arrow_upward",
                    insignia="Más caros" if cantidades["subieron"] else "",
                    tono="alerta",
                    pie_izq="El precio final subió",
                ),
                indicador(
                    "Presentaciones con cambios",
                    cambios.values("gtin_id").distinct().count(),
                    pie_izq="Productos y tamaños distintos",
                ),
            ],
            "pestanas": pestanas(
                reverse("historial_de_precios"),
                "cambio",
                [
                    ("", "Todos los cambios", total),
                    ("bajaron", "Bajaron", cantidades["bajaron"]),
                    ("subieron", "Subieron", cantidades["subieron"]),
                    (
                        "disponibilidad",
                        "Disponibilidad",
                        cantidades["disponibilidad"],
                    ),
                    ("nuevos", "Precios nuevos", cantidades["nuevos"]),
                ],
                tipo,
                conservar=filtros,
            ),
            "total_texto": plural(
                pagina.paginator.count, "cambio de precio", "cambios de precio"
            ),
        },
    )


@role_required(User.Role.ADMIN)
def historial_de_presentacion(request, gtin):
    """La comparativa de una presentación: el precio de cada tienda en cada
    actualización, con el gráfico de los últimos 6 meses."""
    variante = get_object_or_404(
        ProductVariants.objects.select_related(
            "product", "product__brand", "product__category"
        ),
        gtin=gtin,
    )
    precios = list(
        Prices.objects.filter(gtin_id=variante.gtin).select_related(
            "id_store", "currency"
        )
    )
    registros = PriceHistory.objects.filter(gtin_id=variante.gtin)
    # Los mismos colores en el gráfico y en la tabla, aunque alguna tienda
    # ya no tenga precio.
    colores = colores_de_tiendas(
        set(registros.values_list("store_id", flat=True))
        | {precio.id_store_id for precio in precios}
    )
    grafico = graficos_del_producto(precios, colores=colores).get(
        variante.gtin
    )
    columnas, filas = comparativa(variante.gtin, colores=colores)
    pagina = Paginator(filas, FILAS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )

    disponibles = [
        (precio_final(precio.price, precio.discount), precio)
        for precio in precios
        if precio.is_available and precio.price is not None
    ]
    mejor = min(disponibles, key=lambda par: par[0], default=None)
    ultimo = registros.order_by("-recorded_at", "-id").first()
    en_el_grafico = registros.filter(
        recorded_at__gte=inicio_del_grafico()
    ).exclude(source=PriceHistory.Source.INICIAL)
    return render(
        request,
        "products/historial_presentacion.html",
        {
            "variante": variante,
            "grafico": grafico,
            "columnas": columnas,
            "pagina": pagina,
            "simbolo": precios[0].currency.symbol if precios else "₡",
            "total_texto": plural(
                pagina.paginator.count,
                "registro del historial",
                "registros del historial",
            ),
            "kpis": [
                indicador(
                    "Mejor precio hoy",
                    (
                        f"{mejor[1].currency.symbol}{miles(mejor[0])}"
                        if mejor
                        else "—"
                    ),
                    pie_izq=(
                        nombre_de_tienda(mejor[1].id_store)
                        if mejor
                        else "Ninguna tienda lo tiene disponible"
                    ),
                    destacada=True,
                ),
                indicador(
                    "Tiendas con precio",
                    len(precios),
                    pie_izq=plural(
                        len(disponibles),
                        "la tiene disponible",
                        "la tienen disponible",
                    ),
                ),
                indicador(
                    "Cambios en 6 meses",
                    en_el_grafico.count(),
                    pie_izq="Sin contar el precio inicial",
                ),
                indicador(
                    "Último registro",
                    (
                        timezone.localtime(ultimo.recorded_at).strftime(
                            "%d/%m/%Y"
                        )
                        if ultimo
                        else "—"
                    ),
                    pie_izq=(
                        timezone.localtime(ultimo.recorded_at).strftime(
                            "%H:%M"
                        )
                        if ultimo
                        else "Todavía no hay historial"
                    ),
                ),
            ],
        },
    )
