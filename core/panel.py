"""Utilidades de las pantallas del panel de administración (templates/panel/).

Los textos van en español: las plantillas los traducen con {% t %}.
"""

from urllib.parse import urlencode

from django.utils import timezone


def plural(cantidad, singular, plural_):
    """plural(1, "reseña", "reseñas") -> "1 reseña"; con 3 -> "3 reseñas"."""
    return f"{cantidad} {singular if cantidad == 1 else plural_}"


def indicador(
    etiqueta,
    valor,
    unidad="",
    insignia="",
    tono="",
    icono="",
    pie_izq="",
    pie_der="",
    destacada=False,
):
    """Una tarjeta de templates/panel/kpi.html. tono de la insignia: alerta, bien, marca o neutro."""
    return {
        "etiqueta": etiqueta,
        "valor": valor,
        "unidad": unidad,
        "insignia": insignia,
        "tono": tono,
        "icono": icono,
        "pie_izq": pie_izq,
        "pie_der": pie_der,
        "destacada": destacada,
    }


def pestanas(url, parametro, opciones, actual, conservar=None):
    """Las pestañas de filtro de una tabla (templates/panel/pestana.html).

    opciones: [(valor, texto, cantidad)]; el valor "" es la pestaña sin filtro.
    conservar: otros parámetros de la consulta que se mantienen al cambiar de pestaña.
    """
    resultado = []
    for valor, texto, cantidad in opciones:
        consulta = {
            clave: dato for clave, dato in (conservar or {}).items() if dato
        }
        if valor:
            consulta[parametro] = valor
        resultado.append(
            {
                "url": f"{url}?{urlencode(consulta)}" if consulta else url,
                "texto": texto,
                "cantidad": cantidad,
                "activa": valor == actual,
            }
        )
    return resultado


def inicio_de_hoy():
    """Las 00:00 de hoy en la hora de Costa Rica."""
    return timezone.localtime().replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def inicio_del_mes():
    return inicio_de_hoy().replace(day=1)


def duracion_aproximada(duracion):
    """timedelta -> (cantidad, unidad) para las tarjetas: (12, "min"), (3, "h"), (2, "días")."""
    if duracion is None:
        return None
    minutos = round(duracion.total_seconds() / 60)
    if minutos < 1:
        return ("<1", "min")
    if minutos < 60:
        return (minutos, "min")
    horas = round(minutos / 60)
    if horas < 48:
        return (horas, "h")
    return (round(horas / 24), "días")
