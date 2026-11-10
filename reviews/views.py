from django.shortcuts import get_object_or_404, render

from products.models import Products
from .models import Reviews

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
