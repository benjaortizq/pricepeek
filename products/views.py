from django.shortcuts import get_object_or_404, render

from .models import Product


def detalle_producto(request, pk):
    producto = get_object_or_404(Product.objects.select_related("brand", "category"), pk=pk)
    return render(
        request,
        "products/detalle_producto.html",
        {
            "producto": producto,
            "imagen": producto.main_image(),
            "variantes": producto.variants.order_by("id"),
        },
    )
