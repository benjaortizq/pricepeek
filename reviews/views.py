from django.shortcuts import render

from .models import Reviews

def producto_reseñas(request, pk):
    reviewsProducto = Reviews.objects.select_related("variant").filter(variant_product_id=pk)
    return render(
        request,
        "reviews/producto_reseñas.html",
        {
            "reviews": reviewsProducto,
        },
    )
