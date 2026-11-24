from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from products.models import Products
from .forms import ModerationForm, ReviewForm, ReviewReportForm
from .models import ReviewPhoto, ReviewReport, Reviews


def _delete_review_photo(photo):
    if not photo:
        return
    filename = photo.image.name
    if filename:
        photo.image.storage.delete(filename)
    photo.delete()


def _owned_review(request, pk):
    if not request.user.is_authenticated or request.user.role != "client":
        raise PermissionDenied
    return get_object_or_404(Reviews.objects.select_related("variant"), pk=pk, user_id=request.user.pk)


@login_required
def editar_resena(request, pk):
    resena = _owned_review(request, pk)
    producto_id = resena.variant.product_id
    foto = ReviewPhoto.objects.filter(review_id=resena.pk).first()
    if request.method == "POST":
        form = ReviewForm(request.POST, request.FILES)
        if form.is_valid():
            resena.content = form.cleaned_data["content"]
            resena.score = form.cleaned_data["rating"]
            resena.updated_at = timezone.now()
            resena.save(update_fields=["content", "score", "updated_at"])
            nueva_foto = form.cleaned_data["photo"]
            if nueva_foto:
                if foto:
                    _delete_review_photo(foto)
                foto = ReviewPhoto(review_id=resena.pk)
                foto.image.save(nueva_foto.name, nueva_foto, save=False)
                foto.save()
            elif request.POST.get("remove_photo") == "on" and foto:
                _delete_review_photo(foto)
            return redirect("detalle_producto", pk=producto_id)
    else:
        form = ReviewForm(initial={"rating": resena.score, "content": resena.content})
    producto = get_object_or_404(Products, pk=producto_id)
    return render(
        request,
        "reviews/editar_resena.html",
        {"form": form, "resena": resena, "producto": producto, "foto": foto},
    )


@login_required
def eliminar_resena(request, pk):
    resena = _owned_review(request, pk)
    producto_id = resena.variant.product_id
    if request.method != "POST":
        raise PermissionDenied
    foto = ReviewPhoto.objects.filter(review_id=resena.pk).first()
    if foto:
        _delete_review_photo(foto)
    resena.delete()
    return redirect("detalle_producto", pk=producto_id)


def producto_reseñas(request, pk):
    producto = get_object_or_404(Products, pk=pk)
    reviewsProducto = (
        Reviews.objects.select_related("variant")
        .filter(variant__product_id=producto.pk)
        .order_by("-created_at")
    )
    return render(
        request,
        "reviews/producto_reseñas.html",
        {
            "producto": producto,
            "reviews": reviewsProducto,
        },
    )


@role_required(User.Role.CLIENT)
@require_POST
def reportar_resena(request, review_id):
    """El cliente reporta una reseña ajena como inapropiada (RF-28)."""
    resena = get_object_or_404(Reviews.objects.select_related("variant"), pk=review_id)
    destino = redirect("detalle_producto", pk=resena.variant.product_id)

    if resena.user_id == request.user.pk:
        messages.error(request, "No se envió el reporte porque corresponde a su propia reseña. Solo puede reportar reseñas de otras personas.")
        return destino

    form = ReviewReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "No se envió el reporte porque el motivo está vacío o supera los 500 caracteres. Escriba un motivo de hasta 500 caracteres e inténtelo de nuevo.")
        return destino

    _, creado = ReviewReport.objects.get_or_create(
        review_id=resena.pk,
        reporter=request.user,
        defaults={"reason": form.cleaned_data["reason"], "review_author_id": resena.user_id},
    )
    if creado:
        messages.success(request, "Gracias. Su reporte fue enviado y el equipo de PricePeek lo revisará.")
    else:
        messages.info(request, "Esta reseña ya fue reportada por usted; no necesita enviarla de nuevo.")
    return destino


@role_required(User.Role.ADMIN)
def resenas_reportadas(request):
    """Lista de reseñas con reportes pendientes, para que el administrador las revise."""
    pendientes = list(
        ReviewReport.objects.filter(status=ReviewReport.Status.PENDING)
        .select_related("reporter")
        .order_by("created_at")
    )
    resenas = {
        resena.pk: resena
        for resena in Reviews.objects.select_related("variant__product", "user").filter(
            pk__in={reporte.review_id for reporte in pendientes}
        )
    }
    grupos = {}
    for reporte in pendientes:
        resena = resenas.get(reporte.review_id)
        if resena is None:  # la reseña ya no existe (por ejemplo, su autor la borró)
            continue
        grupo = grupos.setdefault(reporte.review_id, {"resena": resena, "reportes": []})
        grupo["reportes"].append(reporte)
    fotos = {foto.review_id: foto for foto in ReviewPhoto.objects.filter(review_id__in=list(grupos))}
    # Reseñas de cada autor que ya se eliminaron antes, para saber si incumple de forma reiterada.
    infracciones = dict(
        ReviewReport.objects.filter(
            review_author_id__in={grupo["resena"].user_id for grupo in grupos.values()},
            status=ReviewReport.Status.DELETED,
        )
        .values("review_author_id")
        .annotate(total=Count("review_id", distinct=True))
        .values_list("review_author_id", "total")
    )
    for review_id, grupo in grupos.items():
        grupo["foto"] = fotos.get(review_id)
        grupo["infracciones"] = infracciones.get(grupo["resena"].user_id, 0)
    return render(request, "reviews/resenas_reportadas.html", {"grupos": list(grupos.values())})


@role_required(User.Role.ADMIN)
@require_POST
def moderar_resena(request, review_id):
    """El administrador mantiene o elimina una reseña reportada (RF-41) y puede suspender al autor (RF-42)."""
    pendientes = ReviewReport.objects.filter(
        review_id=review_id, status=ReviewReport.Status.PENDING
    )
    if not pendientes.exists():
        messages.info(request, "Esta reseña ya no tiene reportes pendientes. Actualice la lista para ver las reseñas que todavía requieren revisión.")
        return redirect("resenas_reportadas")

    form = ModerationForm(request.POST)
    if not form.is_valid():
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
        return redirect("resenas_reportadas")

    eliminar = form.cleaned_data["action"] == ModerationForm.DELETE
    nota = form.cleaned_data["note"]
    suspendido = False
    foto_almacenada = None

    with transaction.atomic():
        resena = Reviews.objects.filter(pk=review_id).first()
        resolucion = {
            "status": ReviewReport.Status.DELETED if eliminar else ReviewReport.Status.KEPT,
            "resolved_by_id": request.user.pk,
            "resolved_at": timezone.now(),
            "resolution_note": nota,
        }
        if resena:
            # Por si el reporte se creó antes de guardar el autor: la infracción debe contarle.
            resolucion["review_author_id"] = resena.user_id
        if eliminar and resena:
            foto = ReviewPhoto.objects.filter(review_id=review_id).first()
            if foto:
                foto_almacenada = (foto.image.storage, foto.image.name)
                foto.delete()
            if form.cleaned_data["suspend"]:
                suspendido = User.objects.suspender_cliente(resena.user_id, request.user, nota)
            resena.delete()
        pendientes.update(**resolucion)

    if foto_almacenada:
        almacenamiento, nombre = foto_almacenada
        try:
            almacenamiento.delete(nombre)
        except Exception:
            messages.warning(request, "La reseña se eliminó, pero no se pudo borrar su foto del almacenamiento. Avise al equipo de soporte para que elimine el archivo pendiente.")

    if eliminar:
        mensaje = "Reseña eliminada."
        if suspendido:
            mensaje += " La cuenta del autor fue suspendida."
    else:
        mensaje = "La reseña se mantiene y los reportes quedaron resueltos."
    messages.success(request, mensaje)
    return redirect("resenas_reportadas")
