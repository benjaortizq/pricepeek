from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from products.models import Products
from .forms import ReviewForm
from .models import ReviewPhoto, Reviews


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
