"""Eliminación de reseñas por incumplir las políticas de uso (issue «Eliminación de reseñas»).

La usan las dos pantallas del panel: reseñas reportadas y todas las reseñas. Una reseña solo se
elimina indicando qué política de uso incumple y por qué; eso queda en ReviewDeletion junto con
lo que decía la reseña, aunque ella ya no exista.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count

from accounts.models import User

from .models import ReviewDeletion, ReviewPhoto, ReviewReport

POLITICAS = dict(ReviewDeletion.SELECTABLE)


class NoSePuedeEliminar(Exception):
    pass


@dataclass
class Eliminacion:
    registro: ReviewDeletion
    suspendido: bool
    foto_sin_borrar: bool  # el archivo de la foto no se pudo borrar del almacenamiento


def eliminar_resena(resena, administrador, politica, razon, suspender=False):
    """Elimina la reseña, registra la política y la razón, y resuelve sus reportes pendientes.

    resena: la fila de Reviews, con variant__product y user cargados.
    """
    razon = (razon or "").strip()
    if politica not in POLITICAS:
        raise NoSePuedeEliminar("Elija la política de uso que incumple la reseña.")
    if not razon:
        raise NoSePuedeEliminar("Indique el motivo de la eliminación.")

    archivo = None
    with transaction.atomic():
        pendientes = ReviewReport.objects.filter(review_id=resena.pk, status=ReviewReport.Status.PENDING)
        reportes = pendientes.count()
        suspendido = bool(suspender) and User.objects.suspender_cliente(resena.user_id, administrador, razon)
        registro = ReviewDeletion.objects.create(
            review_id=resena.pk,
            author_id=resena.user_id,
            deleted_by=administrador,
            policy=politica,
            reason=razon,
            product_name=resena.variant.product.name[:255],
            variant_name=resena.variant.name[:255],
            content=resena.content,
            score=resena.score,
            reports=reportes,
            author_suspended=suspendido,
        )
        pendientes.update(
            status=ReviewReport.Status.DELETED,
            resolved_by=administrador,
            resolved_at=registro.deleted_at,
            resolution_note=razon,
            # Por si el reporte se creó antes de guardar el autor.
            review_author_id=resena.user_id,
        )
        foto = ReviewPhoto.objects.filter(review_id=resena.pk).first()
        if foto:
            archivo = (foto.image.storage, foto.image.name)
            foto.delete()
        resena.delete()

    # El archivo se borra después: si fallara la base, la foto no debe quedar perdida.
    foto_sin_borrar = False
    if archivo:
        almacenamiento, nombre = archivo
        try:
            almacenamiento.delete(nombre)
        except Exception:
            foto_sin_borrar = True
    return Eliminacion(registro, suspendido, foto_sin_borrar)


def infracciones_por_autor(autores):
    """{autor_id: cuántas reseñas suyas se eliminaron por incumplir las políticas}."""
    return dict(
        ReviewDeletion.objects.filter(author_id__in=list(autores))
        .values("author_id")
        .annotate(total=Count("id"))
        .values_list("author_id", "total")
    )
