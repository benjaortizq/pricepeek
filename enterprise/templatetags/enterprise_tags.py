"""Filtros de presentación del portal de empresas."""

import json
from decimal import Decimal

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

register = template.Library()


def _formatear_numero(valor, decimales):
    texto = f"{valor:,.{decimales}f}"
    if (get_language() or "es").lower().startswith("es"):
        return (
            texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        )
    return texto


@register.filter
def clean_text(value):
    """Quita espacios iniciales y finales de un texto."""
    return "" if value is None else str(value).strip()


@register.filter
def percent_of(value, total):
    """Calcula el porcentaje de una parte respecto a un total."""
    try:
        return round((float(value or 0) / float(total or 1)) * 100, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def money(value, symbol="₡"):
    """Presenta un monto con separador de miles y símbolo de la moneda."""
    if value is None or value == "":
        return "—"
    try:
        monto = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return str(value)
    if monto == monto.to_integral_value():
        return f"{symbol}{_formatear_numero(monto, 0)}"
    return f"{symbol}{_formatear_numero(monto, 2)}"


@register.filter
def percent(value):
    """Presenta un porcentaje sin decimales innecesarios."""
    if value is None or value == "":
        return "—"
    try:
        porcentaje = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return str(value)
    texto = _formatear_numero(porcentaje, 1)
    if "." in texto:
        return texto.rstrip("0").rstrip(".")
    return texto.rstrip("0").rstrip(",")


@register.filter
def json_pretty(value):
    """Muestra un JSON legible y escapado para evitar HTML ejecutable."""
    if value in (None, ""):
        return ""
    try:
        contenido = json.dumps(
            value, ensure_ascii=False, indent=2, sort_keys=True
        )
    except (TypeError, ValueError):
        return escape(str(value))
    return mark_safe(escape(contenido))
