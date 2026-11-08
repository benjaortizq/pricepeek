from django.shortcuts import get_object_or_404, render
from django.shortcuts import render

from .models import Reviews

def producto_reseñas(request, pk):
    producto = get_object_or_404(Reviews.objects.select_related("variant"), pk=pk)
    return render(
        request,
        "reviews/producto_reseñas.html",
        {
            "producto": producto,
            "imagen": producto.main_image(),
            "variantes": producto.variants.order_by("id"),
        },
    )
