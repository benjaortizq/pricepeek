"""Registro y consulta sanitizada del historial de cambios de precios."""

import calendar
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import get_language

from core.translations import translate_text

from .models import AuditPriceChanges


MESES_HISTORIAL_PUBLICO = 6

_ANCHO_GRAFICA = 960
_ALTO_GRAFICA = 360
_MARGEN_IZQUIERDO_GRAFICA = 86
_MARGEN_DERECHO_GRAFICA = 28
_MARGEN_SUPERIOR_GRAFICA = 28
_MARGEN_INFERIOR_GRAFICA = 56
_COLORES_GRAFICA = 10


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


def _ahora_local(ahora=None):
    ahora = ahora or timezone.now()
    if timezone.is_naive(ahora):
        ahora = timezone.make_aware(ahora, timezone.get_current_timezone())
    return timezone.localtime(ahora)


def _fecha_local(fecha):
    if timezone.is_naive(fecha):
        fecha = timezone.make_aware(fecha, timezone.get_current_timezone())
    return timezone.localtime(fecha)


def _precio_final(precio, descuento):
    """Calcula el precio final con el mismo redondeo del detalle público.

    El detalle muestra ``ROUND(price * (1 - discount))`` como entero. La
    función conserva ese resultado para que el modal y la gráfica representen
    exactamente el mismo monto.
    """
    if precio is None:
        return None
    try:
        monto = Decimal(precio) * (Decimal("1") - _descuento(descuento))
        return int(monto.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _nombre_tienda(precio):
    nombre = getattr(precio, "tienda", None)
    if not nombre:
        nombre = getattr(getattr(precio, "id_store", None), "name", "")
    return " ".join(str(nombre or "").split())


def _consultar_auditorias_publicas(precios, inicio, fin):
    """Consulta una sola vez los cambios públicos del rango compartido."""
    if not precios:
        return []

    return list(
        AuditPriceChanges.objects.filter(
            id_store_id__in={precio.id_store_id for precio in precios},
            gtin_id__in={precio.gtin_id for precio in precios},
            created_at__gte=inicio,
            created_at__lte=fin,
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
        .order_by("created_at", "id")
    )


def _preparar_historiales(precios, registros):
    """Construye el modal B3 a partir de la consulta ya realizada."""
    por_precio = defaultdict(list)
    for registro in registros:
        clave = (registro["id_store_id"], registro["gtin_id"])
        por_precio[clave].append(registro)

    historiales = {}
    for indice, precio in enumerate(precios, start=1):
        clave = f"precio-{indice}"
        precio.historial_clave = clave
        elementos = []
        registros_precio = por_precio.get((precio.id_store_id, precio.gtin_id), [])
        for registro in reversed(registros_precio):
            fecha = _fecha_local(registro["created_at"])
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


def _eventos_de_precio(registros):
    eventos = []
    for registro in registros:
        eventos.append(
            {
                "fecha": _fecha_local(registro["created_at"]),
                "precio_anterior": _precio_final(
                    registro["old_price"], registro["old_discount"]
                ),
                "precio_nuevo": _precio_final(
                    registro["new_price"], registro["new_discount"]
                ),
                "disponible": bool(registro["is_active"]),
                "solo_disponibilidad": es_cambio_solo_disponibilidad(registro),
            }
        )
    return eventos


def _preparar_serie(precio, registros, inicio_ventana, fin_ventana):
    """Reconstruye los tramos y cambios conocidos de una oferta."""
    introduccion = _fecha_local(precio.created_at)
    if introduccion > fin_ventana:
        return None

    inicio_visible = max(introduccion, inicio_ventana)
    eventos = [
        evento
        for evento in _eventos_de_precio(registros)
        if evento["fecha"] >= introduccion and evento["fecha"] <= fin_ventana
    ]

    if eventos:
        precio_anterior = eventos[0]["precio_anterior"]
        if eventos[0]["solo_disponibilidad"]:
            disponible_anterior = not eventos[0]["disponible"]
        else:
            disponible_anterior = eventos[0]["disponible"]
    else:
        precio_anterior = _precio_final(precio.price, precio.discount)
        disponible_anterior = bool(precio.is_available)

    if precio_anterior is None and not eventos:
        return None

    tramos = []
    conectores = []
    tiempo_anterior = inicio_visible

    for evento in eventos:
        fecha_evento = evento["fecha"]
        if fecha_evento < tiempo_anterior:
            continue

        if fecha_evento > tiempo_anterior and precio_anterior is not None:
            tramos.append(
                {
                    "desde": tiempo_anterior,
                    "hasta": fecha_evento,
                    "precio_final": precio_anterior,
                    "disponible": disponible_anterior,
                }
            )

        if disponible_anterior != evento["disponible"]:
            evento["tipo"] = (
                "reactivacion" if evento["disponible"] else "desactivacion"
            )
        else:
            evento["tipo"] = "precio"

        if (
            disponible_anterior
            and evento["disponible"]
            and precio_anterior is not None
            and evento["precio_nuevo"] is not None
            and precio_anterior != evento["precio_nuevo"]
        ):
            conectores.append(
                {
                    "fecha": fecha_evento,
                    "precio_anterior": precio_anterior,
                    "precio_nuevo": evento["precio_nuevo"],
                }
            )

        precio_anterior = evento["precio_nuevo"]
        disponible_anterior = evento["disponible"]
        tiempo_anterior = fecha_evento

    if fin_ventana > tiempo_anterior and precio_anterior is not None:
        tramos.append(
            {
                "desde": tiempo_anterior,
                "hasta": fin_ventana,
                "precio_final": precio_anterior,
                "disponible": disponible_anterior,
            }
        )

    if not tramos and not eventos:
        return None

    return {
        "clave": precio.historial_clave,
        "tienda": _nombre_tienda(precio),
        "moneda": getattr(getattr(precio, "currency", None), "symbol", ""),
        "introduccion": introduccion,
        "inicio_visible": inicio_visible,
        "tramos": tramos,
        "conectores": conectores,
        "cambios": eventos,
    }


def _formatear_monto(valor, simbolo):
    try:
        numero = f"{int(valor):,}"
    except (TypeError, ValueError):
        numero = str(valor)
    else:
        if (get_language() or "es").lower().startswith("es"):
            numero = numero.replace(",", ".")
    return f"{simbolo}{numero}"


def _formatear_fecha(fecha):
    return date_format(fecha, "d M Y H:i")


def _etiqueta_accesible_cambio(serie, evento):
    tipo = translate_text(
        {
            "precio": "Cambio de precio",
            "desactivacion": "Desactivación",
            "reactivacion": "Reactivación",
        }[evento["tipo"]]
    )
    estado = translate_text("Disponible" if evento["disponible"] else "No disponible")
    anterior = _formatear_monto(evento["precio_anterior"], serie["moneda"])
    nuevo = _formatear_monto(evento["precio_nuevo"], serie["moneda"])
    return translate_text(
        (
            "{tienda}, {fecha}. {tipo}. Precio final anterior: {anterior}. "
            "Precio final nuevo: {nuevo}. {estado}."
        ),
        tienda=serie["tienda"],
        fecha=_formatear_fecha(evento["fecha"]),
        tipo=tipo,
        anterior=anterior,
        nuevo=nuevo,
        estado=estado,
    )


def _x_grafica(fecha, inicio, fin, x_inicio, x_fin):
    duracion = (fin - inicio).total_seconds()
    if duracion <= 0:
        return x_inicio
    proporcion = (fecha - inicio).total_seconds() / duracion
    proporcion = max(0.0, min(1.0, proporcion))
    return x_inicio + proporcion * (x_fin - x_inicio)


def _ajustar_marcadores_mismo_dia(serie, x_inicio, x_fin):
    """Separa visualmente cambios registrados el mismo día."""
    por_dia = defaultdict(list)
    for cambio in serie["cambios"]:
        por_dia[cambio["fecha"].date()].append(cambio)

    for cambios in por_dia.values():
        if len(cambios) < 2:
            continue
        centro = sum(cambio["x_base"] for cambio in cambios) / len(cambios)
        separacion = 16
        ancho = separacion * (len(cambios) - 1)
        for indice, cambio in enumerate(cambios):
            x = centro - ancho / 2 + indice * separacion
            cambio["x"] = max(x_inicio, min(x_fin, x))


def _decorar_grafica(grafica, inicio_ventana, fin_ventana):
    x_inicio = _MARGEN_IZQUIERDO_GRAFICA
    x_fin = _ANCHO_GRAFICA - _MARGEN_DERECHO_GRAFICA
    y_inicio = _MARGEN_SUPERIOR_GRAFICA
    y_fin = _ALTO_GRAFICA - _MARGEN_INFERIOR_GRAFICA

    valores = []
    for serie in grafica["series"]:
        for tramo in serie["tramos"]:
            if tramo["precio_final"] is not None:
                valores.append(tramo["precio_final"])
        for cambio in serie["cambios"]:
            valores.extend(
                valor
                for valor in (
                    cambio["precio_anterior"],
                    cambio["precio_nuevo"],
                )
                if valor is not None
            )

    if not valores:
        return None

    minimo = min(valores)
    maximo = max(valores)
    if minimo == maximo:
        margen = max(1, int(round(abs(minimo) * 0.05)))
        minimo -= margen
        maximo += margen
    else:
        margen = max(1, int(round((maximo - minimo) * 0.08)))
        minimo = max(0, minimo - margen)
        maximo += margen

    def y_precio(precio):
        if maximo == minimo:
            return (y_inicio + y_fin) / 2
        return y_fin - ((precio - minimo) / (maximo - minimo)) * (y_fin - y_inicio)

    moneda = grafica["series"][0]["moneda"]
    grafica.update(
        {
            "ancho": _ANCHO_GRAFICA,
            "alto": _ALTO_GRAFICA,
            "x_inicio": x_inicio,
            "x_fin": x_fin,
            "y_inicio": y_inicio,
            "y_fin": y_fin,
            "minimo": minimo,
            "maximo": maximo,
            "eje_y": [
                {
                    "y": y_inicio,
                    "etiqueta": _formatear_monto(maximo, moneda),
                },
                {
                    "y": (y_inicio + y_fin) / 2,
                    "etiqueta": _formatear_monto(round((minimo + maximo) / 2), moneda),
                },
                {
                    "y": y_fin,
                    "etiqueta": _formatear_monto(minimo, moneda),
                },
            ],
            "eje_x": [
                {
                    "x": x_inicio,
                    "etiqueta": date_format(inicio_ventana, "d M Y"),
                    "anclaje": "start",
                },
                {
                    "x": (x_inicio + x_fin) / 2,
                    "etiqueta": date_format(
                        inicio_ventana + (fin_ventana - inicio_ventana) / 2,
                        "d M Y",
                    ),
                    "anclaje": "middle",
                },
                {
                    "x": x_fin,
                    "etiqueta": date_format(fin_ventana, "d M Y"),
                    "anclaje": "end",
                },
            ],
        }
    )

    for indice, serie in enumerate(grafica["series"]):
        serie["color"] = indice % _COLORES_GRAFICA
        serie["introduccion"] = serie["introduccion"].isoformat()
        serie["inicio_visible"] = serie["inicio_visible"].isoformat()
        for tramo in serie["tramos"]:
            tramo["x1"] = _x_grafica(
                tramo["desde"], inicio_ventana, fin_ventana, x_inicio, x_fin
            )
            tramo["x2"] = _x_grafica(
                tramo["hasta"], inicio_ventana, fin_ventana, x_inicio, x_fin
            )
            tramo["y"] = y_precio(tramo["precio_final"])
            tramo["desde_texto"] = tramo["desde"].isoformat()
            tramo["hasta_texto"] = tramo["hasta"].isoformat()

        for conector in serie["conectores"]:
            conector["x"] = _x_grafica(
                conector["fecha"], inicio_ventana, fin_ventana, x_inicio, x_fin
            )
            conector["y_anterior"] = y_precio(conector["precio_anterior"])
            conector["y_nuevo"] = y_precio(conector["precio_nuevo"])

        for cambio in serie["cambios"]:
            cambio["x_base"] = _x_grafica(
                cambio["fecha"], inicio_ventana, fin_ventana, x_inicio, x_fin
            )
            cambio["x"] = cambio["x_base"]
            cambio["y"] = y_precio(cambio["precio_nuevo"])
            cambio["fecha_texto"] = _formatear_fecha(cambio["fecha"])
            cambio["fecha_texto_iso"] = cambio["fecha"].isoformat()
            cambio["precio_anterior_texto"] = _formatear_monto(
                cambio["precio_anterior"], serie["moneda"]
            )
            cambio["precio_nuevo_texto"] = _formatear_monto(
                cambio["precio_nuevo"], serie["moneda"]
            )
            cambio["tipo_texto"] = translate_text(
                {
                    "precio": "Cambio de precio",
                    "desactivacion": "Desactivación",
                    "reactivacion": "Reactivación",
                }[cambio["tipo"]]
            )
            cambio["estado"] = translate_text(
                "Disponible" if cambio["disponible"] else "No disponible"
            )
            cambio["aria_label"] = _etiqueta_accesible_cambio(serie, cambio)

        _ajustar_marcadores_mismo_dia(serie, x_inicio, x_fin)
        for cambio in serie["cambios"]:
            if cambio["tipo"] == "desactivacion":
                cambio["figura"] = "cuadrado"
                cambio["rectangulo"] = {
                    "x": cambio["x"] - 6,
                    "y": cambio["y"] - 6,
                    "ancho": 12,
                    "alto": 12,
                }
            elif cambio["tipo"] == "reactivacion":
                cambio["figura"] = "triangulo"
                cambio["puntos"] = (
                    f"{cambio['x']},{cambio['y'] - 8} "
                    f"{cambio['x'] + 7},{cambio['y'] + 6} "
                    f"{cambio['x'] - 7},{cambio['y'] + 6}"
                )
            else:
                cambio["figura"] = "circulo"

    return grafica


def _preparar_graficas(precios, registros, inicio_ventana, fin_ventana):
    por_precio = defaultdict(list)
    for registro in registros:
        clave = (registro["id_store_id"], registro["gtin_id"])
        por_precio[clave].append(registro)

    grupos = defaultdict(list)
    for precio in precios:
        grupos[precio.gtin_id].append(precio)

    graficas = []
    for indice, grupo in enumerate(grupos.values(), start=1):
        series = []
        for precio in grupo:
            serie = _preparar_serie(
                precio,
                por_precio.get((precio.id_store_id, precio.gtin_id), []),
                inicio_ventana,
                fin_ventana,
            )
            if serie is not None:
                series.append(serie)

        if not series:
            continue

        variante = getattr(getattr(grupo[0], "gtin", None), "name", "")
        grafica = {
            "clave": f"grafica-{indice}",
            "variante": variante or translate_text("Producto"),
            "series": series,
        }
        grafica = _decorar_grafica(grafica, inicio_ventana, fin_ventana)
        if grafica is not None:
            graficas.append(grafica)

    return graficas


def datos_historicos_publicos(precios, ahora=None):
    """Prepara B3 y la gráfica C con una sola consulta de auditoría.

    El resultado comparte la misma ventana de seis meses calendarios. Los
    datos públicos usan claves secuenciales y nunca incluyen actores ni
    identificadores internos.
    """
    precios = list(precios)
    ahora = _ahora_local(ahora)
    inicio_ventana = limite_historial_publico(ahora)
    registros = _consultar_auditorias_publicas(precios, inicio_ventana, ahora)

    historiales = _preparar_historiales(precios, registros)
    graficas = _preparar_graficas(
        precios,
        registros,
        inicio_ventana,
        ahora,
    )
    return {
        "historiales": historiales,
        "grafica": {
            "ventana": {
                "inicio": inicio_ventana.isoformat(),
                "fin": ahora.isoformat(),
                "meses": MESES_HISTORIAL_PUBLICO,
            },
            "graficas": graficas,
        },
    }


def historiales_publicos(precios, ahora=None):
    """Prepara historiales públicos sin actor ni identificadores internos.

    A cada precio se le asigna una clave pública secuencial. Los datos que se
    entregan al navegador se limitan a fecha, precios, descuentos y la
    etiqueta de un cambio exclusivo de disponibilidad.
    """
    return datos_historicos_publicos(precios, ahora)["historiales"]
