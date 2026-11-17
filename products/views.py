from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from .busqueda import buscar_productos, con_imagen
from .models import Prices, ProductImages, ProductVariants, Products
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
    precios = list(
        Prices.objects.filter(gtin__product_id=producto.pk)
        .select_related("id_store", "currency", "gtin")
        .order_by("id_store__name", "gtin__name")
    )
    for precio in precios:
        precio.tienda = precio.id_store.name.strip()  # algunos nombres traen un salto de línea
        if precio.price is not None:
            precio.final = round(precio.price * (1 - precio.discount))  
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
            "precios": precios,
            "resenas": resenas,
        },
    )


PRODUCTOS_POR_PAGINA = 24


def buscar(request):
    palabra = request.GET.get("q", "").strip()
    pagina = Paginator(buscar_productos(palabra), PRODUCTOS_POR_PAGINA).get_page(request.GET.get("pagina"))
    return render(
        request,
        "products/buscar.html",
        {"palabra": palabra, "pagina": pagina, "productos": con_imagen(pagina)},
    )
