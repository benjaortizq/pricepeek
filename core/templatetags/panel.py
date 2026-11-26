"""Etiquetas del panel de administración (templates/panel/)."""

from django import template

register = template.Library()


@register.simple_tag
def pendientes_del_panel():
    """Lo que espera revisión, para los contadores de la barra lateral del panel."""
    from ingestion.models import Incident, ManualRun
    from ingestion.resolucion import EXTRACCION_FALLIDA
    from reviews.indicadores import resenas_en_cola

    return {
        "resenas": resenas_en_cola(),
        "incidencias": Incident.objects.filter(
            kind__in=EXTRACCION_FALLIDA, status=Incident.Status.PENDING
        ).count(),
        # Las ejecuciones manuales de la obtención de datos que todavía no terminan.
        "ejecuciones": ManualRun.objects.filter(
            status__in=ManualRun.ACTIVE
        ).count(),
    }


@register.filter
def estrellas(calificacion):
    """3 -> "★★★☆☆", como en la tabla de reseñas reportadas del diseño."""
    try:
        llenas = max(0, min(5, int(calificacion)))
    except (TypeError, ValueError):
        return ""
    return "★" * llenas + "☆" * (5 - llenas)
