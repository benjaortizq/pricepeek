from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from products.models import Products
from .forms import ModerationForm, ReviewReportForm
from .models import ReviewPhoto, ReviewReport, Reviews

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
        messages.error(request, "No puede reportar su propia reseña.")
        return destino

    form = ReviewReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indique el motivo del reporte (máximo 500 caracteres).")
        return destino

    _, creado = ReviewReport.objects.get_or_create(
        review_id=resena.pk,
        reporter=request.user,
        defaults={"reason": form.cleaned_data["reason"]},
    )
    if creado:
        messages.success(request, "Gracias. Su reporte fue enviado y el equipo de PricePeek lo revisará.")
    else:
        messages.error(request, "Usted ya reportó esta reseña.")
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
    for review_id, grupo in grupos.items():
        grupo["foto"] = fotos.get(review_id)
    return render(request, "reviews/resenas_reportadas.html", {"grupos": list(grupos.values())})


@role_required(User.Role.ADMIN)
@require_POST
def moderar_resena(request, review_id):
    """El administrador mantiene o elimina una reseña reportada (RF-41) y puede suspender al autor (RF-42)."""
    pendientes = ReviewReport.objects.filter(
        review_id=review_id, status=ReviewReport.Status.PENDING
    )
    if not pendientes.exists():
        messages.error(request, "Esa reseña ya no tiene reportes pendientes.")
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
        if eliminar:
            resena = Reviews.objects.filter(pk=review_id).first()
            if resena:
                foto = ReviewPhoto.objects.filter(review_id=review_id).first()
                if foto:
                    foto_almacenada = (foto.image.storage, foto.image.name)
                    foto.delete()
                if form.cleaned_data["suspend"]:
                    suspendido = bool(
                        User.objects.filter(pk=resena.user_id, role=User.Role.CLIENT).update(
                            is_active=False
                        )
                    )
                resena.delete()
        estado = ReviewReport.Status.DELETED if eliminar else ReviewReport.Status.KEPT
        pendientes.update(
            status=estado,
            resolved_by_id=request.user.pk,
            resolved_at=timezone.now(),
            resolution_note=nota,
        )

    if foto_almacenada:
        almacenamiento, nombre = foto_almacenada
        try:
            almacenamiento.delete(nombre)
        except Exception:
            messages.warning(request, "La reseña se eliminó, pero no se pudo borrar su foto del almacenamiento.")

    if eliminar:
        mensaje = "Reseña eliminada."
        if suspendido:
            mensaje += " La cuenta del autor fue suspendida."
    else:
        mensaje = "La reseña se mantiene y los reportes quedaron resueltos."
    messages.success(request, mensaje)
    return redirect("resenas_reportadas")
