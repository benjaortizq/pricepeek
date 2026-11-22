from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.decorators import role_required
from products.models import ProductImages, ProductVariants, Products, Prices

from .models import WishlistItem


@role_required("client")
def lista_deseos(request):
    items = list(
        WishlistItem.objects.filter(user=request.user)
        .select_related("variant__product__brand", "currency")
        .order_by("-created_at")
    )
    if items:
        variantes = [item.variant for item in items]
        precios_por_variante_y_moneda = {}
        precios = (
            Prices.objects.filter(
                gtin__in=[variante.gtin for variante in variantes],
                currency_id__in={item.currency_id for item in items},
                is_available=True,
            )
            .exclude(price__isnull=True)
            .select_related("currency", "id_store")
        )
        for precio in precios:
            clave = (precio.gtin_id, precio.currency_id)
            precio.final = round(precio.price * (1 - precio.discount))
            precio.tienda = precio.id_store.name.strip()
            actual = precios_por_variante_y_moneda.get(clave)
            if actual is None or (precio.final, precio.tienda) < (actual.final, actual.tienda):
                precios_por_variante_y_moneda[clave] = precio

        imagenes = {}
        for imagen in ProductImages.objects.filter(
            variant_id__in=[variante.pk for variante in variantes]
        ).order_by("-is_main", "id"):
            imagenes.setdefault(imagen.variant_id, imagen.image_url)

        for item in items:
            item.imagen_url = imagenes.get(item.variant_id)
            item.mejor_precio = precios_por_variante_y_moneda.get(
                (item.variant.gtin, item.currency_id)
            )

    return render(request, "wishlist/lista.html", {"items": items})


@role_required("client")
def agregar_a_lista_deseos(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    producto = get_object_or_404(Products, pk=pk)
    variante = ProductVariants.objects.filter(product_id=producto.pk).order_by("id").first()
    if variante is not None:
        try:
            _, creada = WishlistItem.objects.get_or_create(user=request.user, variant=variante)
        except IntegrityError:
            # La restricción única evita duplicados si llegan solicitudes simultáneas.
            creada = False
        if creada:
            messages.success(request, "Producto añadido a tu lista de deseos.")
        else:
            messages.info(request, "Este producto ya está en tu lista de deseos.")
    else:
        messages.error(request, "Este producto todavía no tiene una variante para guardar.")

    siguiente = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        siguiente = "buscar_productos"
    return redirect(siguiente)


@role_required("client")
def eliminar_de_lista_deseos(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    item = get_object_or_404(WishlistItem, pk=pk, user=request.user)
    item.delete()
    messages.success(request, "Producto eliminado de tu lista de deseos.")
    return redirect("wishlist:lista")
