from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import DatabaseError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .models import ProductImages, ProductVariants, Products
from reviews.forms import ReviewForm
from reviews.models import ReviewPhoto, Reviews


def detalle_producto(request, pk):
    producto = get_object_or_404(Products.objects.select_related("brand", "category"), pk=pk)
    imagen = (
        ProductImages.objects.filter(variant__product_id=producto.pk, is_main=True)
        .order_by("id")
        .values("image_url")
        .first()
    )
    variantes = ProductVariants.objects.filter(product_id=producto.pk).order_by("id")
    resenas = (
        Reviews.objects.select_related("variant", "user")
        .filter(variant__product_id=producto.pk)
        .order_by("-created_at")
    )
    ya_reseño = (
        request.user.is_authenticated
        and request.user.role == "client"
        and Reviews.objects.filter(
            user_id=request.user.pk,
            variant__product_id=producto.pk,
        ).exists()
    )
    review_form = ReviewForm()

    if request.method == "POST":
        if not request.user.is_authenticated or request.user.role != "client":
            raise PermissionDenied

        review_form = ReviewForm(request.POST, request.FILES)
        if review_form.is_valid() and variantes.exists():
            stored_photo_name = None
            try:
                with transaction.atomic():
                    # Lock the product so concurrent submissions cannot pass the duplicate check.
                    Products.objects.select_for_update().get(pk=producto.pk)
                    ya_reseño = Reviews.objects.filter(
                        user_id=request.user.pk,
                        variant__product_id=producto.pk,
                    ).exists()
                    if not ya_reseño:
                        variante = variantes.first()
                        resena = Reviews.objects.create(
                            user_id=request.user.pk,
                            variant=variante,
                            content=review_form.cleaned_data["content"],
                            score=review_form.cleaned_data["rating"],
                            created_at=timezone.now(),
                            updated_at=timezone.now(),
                        )
                        photo = review_form.cleaned_data["photo"]
                        if photo:
                            review_photo = ReviewPhoto(review_id=resena.pk)
                            review_photo.image.save(photo.name, photo, save=False)
                            stored_photo_name = review_photo.image.name
                            review_photo.save()
            except DatabaseError:
                if stored_photo_name:
                    default_storage.delete(stored_photo_name)
                raise

            if not ya_reseño:
                return redirect("detalle_producto", pk=producto.pk)

    resenas = list(resenas)
    fotos = {
        photo.review_id: photo
        for photo in ReviewPhoto.objects.filter(
            review_id__in=[resena.pk for resena in resenas]
        )
    }
    for resena in resenas:
        resena.review_photo = fotos.get(resena.pk)

    return render(
        request,
        "products/detalle_producto.html",
        {
            "producto": producto,
            "imagen": imagen,
            "variantes": variantes,
            "resenas": resenas,
            "review_form": review_form,
            "ya_reseño": ya_reseño,
        },
    )
