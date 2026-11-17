from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    QuerySet,
    Value,
    Window,
)
from django.db.models.functions import Coalesce, Rank
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from reviews.forms import ReviewForm
from reviews.models import ReviewPhoto, Reviews

from .busqueda import buscar_productos, con_imagen
from .models import (
    Brands,
    Categories,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
)


def _anotar_precio_final(queryset: QuerySet) -> QuerySet:
    """Agrega el precio final después de aplicar el descuento."""
    return queryset.annotate(
        final_price=ExpressionWrapper(
            F("price")
            * (
                Value(Decimal("1"))
                - Coalesce(F("discount"), Value(Decimal("0")))
            ),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )


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
        _anotar_precio_final(
            Prices.objects.filter(gtin__product_id=producto.pk).select_related(
                "id_store", "currency", "gtin"
            )
        ).order_by(
            "gtin_id",
            F("is_available").desc(),
            F("final_price").asc(nulls_last=True),
            "id_store__name",
            "id",
        )
    )
    for precio in precios:
        precio.tienda = precio.id_store.name.strip()  # algunos nombres traen un salto de línea
        if precio.final_price is not None:
            precio.final = int(round(precio.final_price))

    mejor_por_gtin = {}
    for precio in precios:
        if precio.is_available and precio.final_price is not None:
            mejor_por_gtin.setdefault(precio.gtin_id, precio)
    for precio in precios:
        mejor = mejor_por_gtin.get(precio.gtin_id)
        precio.es_mejor = mejor is not None and mejor.pk == precio.pk
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
                            review_photo = ReviewPhoto(review_id=resena)
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
            "precios": precios,
            "precios": precios,
            "resenas": resenas,
            "review_form": review_form,
            "ya_reseño": ya_reseño,
        },
    )


PRODUCTOS_POR_PAGINA = 24


def buscar(request):
    palabra = request.GET.get("q", "").strip()
    categoria = _parametro_de_consulta(
        request, "categoria", "category", "categoria_id", "category_id"
    )
    marca = _parametro_de_consulta(
        request, "marca", "brand", "marca_id", "brand_id"
    )
    categoria_actual = _categoria_por_filtro(categoria)
    marca_actual = _marca_por_filtro(marca)
    productos = buscar_productos_con_filtros(palabra, categoria, marca)
    pagina = Paginator(productos, PRODUCTOS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    return render(
        request,
        "products/buscar.html",
        {
            "palabra": palabra,
            "categoria_seleccionada": (
                str(categoria_actual.pk) if categoria_actual is not None else ""
            ),
            "marca_seleccionada": (
                str(marca_actual.pk) if marca_actual is not None else ""
            ),
            "categorias": Categories.objects.order_by("name"),
            "marcas": Brands.objects.order_by("name"),
            "pagina": pagina,
            "productos": con_imagen(pagina),
        },
    )


def _prefijo_de_filtro(queryset: QuerySet) -> str:
    """Usa la relación ``product`` cuando el queryset contiene variantes."""
    return "product__" if queryset.model is ProductVariants else ""


def _valor_de_filtro(valor):
    """Normaliza un filtro de relación a un objeto, un ID o un texto."""
    if valor is None:
        return None

    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None

    return valor


def _categoria_por_filtro(categoria):
    """Resuelve una categoría por ID o nombre para canonicalizar la URL."""
    categoria = _valor_de_filtro(categoria)
    if categoria is None:
        return None
    if isinstance(categoria, Categories):
        return categoria

    texto = str(categoria)
    if texto.isdecimal():
        por_id = Categories.objects.filter(pk=int(texto)).first()
        if por_id is not None:
            return por_id

    return Categories.objects.filter(name__iexact=texto).order_by("name").first()


def _marca_por_filtro(marca):
    """Resuelve una marca por ID, nombre o slug para canonicalizar la URL."""
    marca = _valor_de_filtro(marca)
    if marca is None:
        return None
    if isinstance(marca, Brands):
        return marca

    texto = str(marca)
    if texto.isdecimal():
        por_id = Brands.objects.filter(pk=int(texto)).first()
        if por_id is not None:
            return por_id

    return (
        Brands.objects.filter(Q(name__iexact=texto) | Q(slug__iexact=texto))
        .order_by("name")
        .first()
    )


def filtrar_por_categoria(queryset: QuerySet, categoria=None) -> QuerySet:
    """Filtra Products o ProductVariants opcionalmente por categoría.

    ``categoria`` puede ser una instancia de ``Categories``, su ID o su nombre.
    """
    categoria = _valor_de_filtro(categoria)
    if categoria is None:
        return queryset

    prefijo = _prefijo_de_filtro(queryset)
    if isinstance(categoria, Categories):
        return queryset.filter(**{f"{prefijo}category": categoria})

    texto = str(categoria)
    if texto.isdecimal() and Categories.objects.filter(pk=int(texto)).exists():
        return queryset.filter(**{f"{prefijo}category_id": int(texto)})

    return queryset.filter(**{f"{prefijo}category__name__iexact": texto})


def filtrar_por_marca(queryset: QuerySet, marca=None) -> QuerySet:
    """Filtra Products o ProductVariants opcionalmente por marca.

    ``marca`` puede ser una instancia de ``Brands``, su ID, su nombre o su
    ``slug``. La marca está relacionada con el producto de la variante.
    """
    marca = _valor_de_filtro(marca)
    if marca is None:
        return queryset

    prefijo = _prefijo_de_filtro(queryset)
    if isinstance(marca, Brands):
        return queryset.filter(**{f"{prefijo}brand": marca})

    texto = str(marca)
    if texto.isdecimal() and Brands.objects.filter(pk=int(texto)).exists():
        return queryset.filter(**{f"{prefijo}brand_id": int(texto)})

    return queryset.filter(
        Q(**{f"{prefijo}brand__name__iexact": texto})
        | Q(**{f"{prefijo}brand__slug__iexact": texto})
    )


def buscar_productos_con_filtros(
    palabra: str, categoria=None, marca=None
) -> QuerySet[Products]:
    """Combina la búsqueda existente con los filtros opcionales del catálogo."""
    productos = buscar_productos(palabra)
    productos = filtrar_por_categoria(productos, categoria)
    return filtrar_por_marca(productos, marca)


def buscar_variantes_por_nombre(
    nombre: str, categoria=None, marca=None
) -> QuerySet[ProductVariants]:
    """Busca variantes cuyo nombre contiene ``nombre``.

    La búsqueda no distingue mayúsculas de minúsculas y puede acotarse con
    una categoría y una marca, ambas opcionales. Los filtros pertenecen al
    producto asociado a cada variante.
    """
    nombre = (nombre or "").strip()
    variantes = ProductVariants.objects.select_related(
        "product", "product__brand", "product__category"
    ).filter(name__icontains=nombre)

    variantes = filtrar_por_categoria(variantes, categoria)
    variantes = filtrar_por_marca(variantes, marca)
    return variantes.order_by("name", "gtin")


def obtener_precios_por_gtin(gtin: str, solo_disponibles: bool = True) -> QuerySet:
    """Obtiene y rankea los precios de un GTIN, de menor a mayor.

    ``Prices`` garantiza un único precio por tienda y GTIN. Se excluyen los
    precios nulos y, por defecto, los productos que no están disponibles.
    Los precios empatados reciben el mismo puesto de ranking.
    """
    if not gtin:
        return Prices.objects.none()
    
    precios = _anotar_precio_final(
        Prices.objects.select_related("id_store", "currency")
    ).filter(
        gtin_id=gtin,
        price__isnull=False,
    )

    # Excluimos los precios que no están disponibles si se solicita.
    if solo_disponibles:
        precios = precios.filter(is_available=True)

    return precios.annotate(
        ranking=Window(Rank(), order_by=F("final_price").asc())
    ).order_by("final_price", "id_store__name", "id")


def _parametro_de_consulta(request, *nombres: str) -> str | None:
    """Devuelve el primer parámetro GET informado entre varios alias."""
    for nombre in nombres:
        valor = request.GET.get(nombre, "").strip()
        if valor:
            return valor
    return None


def _serializar_precio(precio: Prices) -> dict:
    return {
        "ranking": precio.ranking,
        "tienda": precio.id_store.name.strip(),
        "precio": float(precio.final_price),
        "moneda": precio.currency.symbol,
        "descuento": float(precio.discount or 0),
        "disponible": precio.is_available,
        "url": precio.product_web_url,
    }


@require_GET
def comparar_precios(request):
    """Busca variantes y devuelve sus precios ordenados por ranking.

    Parámetros GET opcionales:

    * ``nombre`` (alias: ``name`` o ``q``): texto de búsqueda obligatorio.
    * ``categoria`` (alias: ``category``, ``categoria_id`` o ``category_id``):
      ID o nombre de la categoría.
    * ``marca`` (alias: ``brand``, ``marca_id`` o ``brand_id``): ID, nombre o
      slug de la marca.
    """
    nombre = _parametro_de_consulta(request, "nombre", "name", "q")
    if not nombre:
        return JsonResponse(
            {"error": "Debe indicar el nombre del producto a comparar."},
            status=400,
        )

    categoria = _parametro_de_consulta(
        request, "categoria", "category", "categoria_id", "category_id"
    )
    marca = _parametro_de_consulta(
        request, "marca", "brand", "marca_id", "brand_id"
    )
    variantes = buscar_variantes_por_nombre(nombre, categoria, marca)

    resultados = []
    for variante in variantes:
        precios = obtener_precios_por_gtin(variante.gtin)
        resultados.append(
            {
                "id": variante.pk,
                "nombre": variante.name,
                "gtin": variante.gtin,
                "producto": {
                    "id": variante.product.pk,
                    "nombre": variante.product.name,
                    "categoria": variante.product.category.name,
                    "marca": variante.product.brand.name,
                },
                "precios": [
                    _serializar_precio(precio) for precio in precios
                ],
            }
        )

    return JsonResponse({"resultados": resultados, "total": len(resultados)})


@require_GET
def filtros_productos(request):
    """Devuelve las categorías y marcas disponibles para filtrar."""
    categorias = Categories.objects.order_by("name").values("id", "name")
    marcas = Brands.objects.order_by("name").values("id", "name", "slug")
    return JsonResponse(
        {
            "categorias": list(categorias),
            "marcas": list(marcas),
        }
    )
