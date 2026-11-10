from django.shortcuts import get_object_or_404, render
from .models import ProductImages, ProductVariants, Products
from reviews.models import Reviews


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
    return render(
        request,
        "products/detalle_producto.html",
        {
            "producto": producto,
            "imagen": imagen,
            "variantes": variantes,
            "resenas": resenas,
        },
    )
