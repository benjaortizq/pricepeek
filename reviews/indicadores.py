"""Indicadores de la moderación de reseñas para las tarjetas del panel de administración."""

from datetime import timedelta

from django.utils import timezone

from core.panel import duracion_aproximada, inicio_de_hoy, inicio_del_mes

from .models import ReviewDeletion, ReviewReport

DIAS_DEL_PROMEDIO = 30

Status = ReviewReport.Status


def resenas_en_cola():
    """Cuántas reseñas tienen reportes pendientes (cuando el autor borra su reseña, sus reportes
    pendientes se borran con ella: ver reviews.views.eliminar_resena)."""
    return (
        ReviewReport.objects.filter(status=Status.PENDING)
        .values("review_id")
        .distinct()
        .count()
    )


def resumen_de_moderacion():
    pendientes = ReviewReport.objects.filter(status=Status.PENDING)
    # Las decisiones de los últimos 30 días: cuánto tardaron y en qué terminaron.
    recientes = ReviewReport.objects.exclude(status=Status.PENDING).filter(
        resolved_at__gte=timezone.now() - timedelta(days=DIAS_DEL_PROMEDIO)
    )
    duraciones = [
        resuelto - creado
        for creado, resuelto in recientes.values_list(
            "created_at", "resolved_at"
        )
    ]
    eliminadas = (
        recientes.filter(status=Status.DELETED)
        .values("review_id")
        .distinct()
        .count()
    )
    mantenidas = (
        recientes.filter(status=Status.KEPT)
        .values("review_id")
        .distinct()
        .count()
    )
    decididas = eliminadas + mantenidas
    return {
        "en_cola": resenas_en_cola(),
        "reportes_pendientes": pendientes.count(),
        "reportes_hoy": pendientes.filter(
            created_at__gte=inicio_de_hoy()
        ).count(),
        "tiempo_promedio": duracion_aproximada(
            sum(duraciones, timedelta()) / len(duraciones)
        )
        if duraciones
        else None,
        # Todas las eliminaciones, vengan o no de un reporte.
        "eliminadas_mes": ReviewDeletion.objects.filter(
            deleted_at__gte=inicio_del_mes()
        ).count(),
        "eliminadas_30": eliminadas,
        "mantenidas_30": mantenidas,
        "tasa_eliminacion": round(100 * eliminadas / decididas)
        if decididas
        else None,
    }
