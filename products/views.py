from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .busqueda import buscar_productos, con_imagen
from .correccion import corregir_busqueda
from .models import Prices, ProductImages, ProductVariants, Products
from reviews.forms import ReviewForm
from reviews.models import ReviewPhoto, ReviewReport, Reviews


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
    calificacion_promedio = resenas.aggregate(promedio=Avg("score"))["promedio"]
    estrellas_promedio = int(calificacion_promedio + 0.5) if calificacion_promedio is not None else 0
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

    # Solo el cliente que reportó ve que ya reportó; nadie más ve quién reporta (RNF-32).
    reportadas = set()
    if request.user.is_authenticated and request.user.role == "client":
        reportadas = set(
            ReviewReport.objects.filter(
                reporter=request.user, review_id__in=[resena.pk for resena in resenas]
            ).values_list("review_id", flat=True)
        )
    for resena in resenas:
        resena.ya_reportada = resena.pk in reportadas

    return render(
        request,
        "products/detalle_producto.html",
        {
            "producto": producto,
            "imagen": imagen,
            "variantes": variantes,
            "precios": precios,
            "resenas": resenas,
            "calificacion_promedio": calificacion_promedio,
            "estrellas_promedio": estrellas_promedio,
            "review_form": review_form,
            "ya_reseño": ya_reseño,
        },
    )


PRODUCTOS_POR_PAGINA = 24


def buscar(request):
    palabra = request.GET.get("q", "").strip()
    pagina = Paginator(buscar_productos(palabra), PRODUCTOS_POR_PAGINA).get_page(request.GET.get("pagina"))
    corregida = None
    if palabra and not pagina.paginator.count:
        # «¿Quiso decir…?»: si no hay nada, se busca con las palabras del catálogo más parecidas.
        corregida = corregir_busqueda(palabra)
        if corregida:
            pagina = Paginator(buscar_productos(corregida), PRODUCTOS_POR_PAGINA).get_page(request.GET.get("pagina"))
    return render(
        request,
        "products/buscar.html",
        {"palabra": palabra, "corregida": corregida, "pagina": pagina, "productos": con_imagen(pagina)},
    )
