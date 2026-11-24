"""Generación del reporte PDF de competitiveness para empresas."""

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.formats import date_format

from .selectors import (
    COMPETITIVIDAD_ROJO,
    catalogo_base,
    estadisticas_catalogo,
    limite_precio_desactualizado,
    _anotar_competitividad,
)


def datos_reporte(store):
    """Reúne estadísticas y productos que requieren revisión."""
    ahora = timezone.now()
    queryset = _anotar_competitividad(catalogo_base(store))
    limite = limite_precio_desactualizado(ahora)
    estadisticas = estadisticas_catalogo(store, ahora=ahora)
    total = estadisticas["total"] or 1

    def porcentaje(cantidad):
        return round((cantidad / total) * 100, 1)

    return {
        "store": store,
        "generated_at": ahora,
        "generated_date": date_format(ahora, "d/m/Y H:i"),
        "language": (translation.get_language() or "es").split("-", 1)[0],
        "stale_price_days": settings.STALE_PRICE_DAYS,
        "stats": estadisticas,
        "percentages": {
            "verde": porcentaje(estadisticas["verde"]),
            "amarillo": porcentaje(estadisticas["amarillo"]),
            "rojo": porcentaje(estadisticas["rojo"]),
            "neutro": porcentaje(estadisticas["neutro"]),
        },
        "above_market": queryset.filter(
            competitiveness=COMPETITIVIDAD_ROJO
        ).order_by("gtin__product__name", "gtin_id"),
        "stale": queryset.filter(updated_at__lte=limite).order_by(
            "updated_at", "gtin__product__name", "gtin_id"
        ),
    }


def _renderer_html():
    """Importa WeasyPrint solo cuando se solicita el reporte.

    De esta forma el resto del portal funciona aunque el servidor todavía no
    tenga instaladas las bibliotecas de sistema Pango requeridas por PDF.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "WeasyPrint no puede cargar Pango. Instale las bibliotecas Pango/Cairo del servidor."
        ) from error
    return HTML


def generar_pdf_empresa(store):
    """Genera el PDF en memoria usando el idioma de la petición activa."""
    contexto = datos_reporte(store)
    html = render_to_string("enterprise/reporte_pdf.html", contexto)
    pdf = _renderer_html()(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    return pdf
