"""Vistas HTTP de la aplicación products."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import (
    Avg,
    BooleanField,
    Case,
    CharField,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import (
    Cast,
    NullIf,
    Replace,
    Round,
    Trim,
)
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.translations import translate_text
from reviews.forms import ReviewForm
from reviews.models import ReviewPhoto, ReviewReport, Reviews

from .barcodes import validar_codigo_barras
from .busqueda import (
    buscar_productos,
    buscar_variantes,
    con_imagen,
    con_imagen_variante,
)

from .correccion import corregir_busqueda
from .models import (
    Brands,
    Categories,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
)
from .popularidad import registrar_visita
from .precios import (
    anotar_precio_final as _anotar_precio_final,
    agrupar_precios_por_gtin,
    con_precio_minimo,
    expresion_precio_final as _expresion_precio_final,
    precios_por_gtin,
)

from config.settings import STALE_PRICE_DAYS


def _expresion_tienda_limpia() -> ExpressionWrapper:
    """Normaliza en SQL los saltos de línea que traen algunos nombres."""
    nombre = Trim("id_store__name")
    for caracter in ("\r", "\n", "\t"):
        nombre = Replace(nombre, Value(caracter), Value(""))
    return ExpressionWrapper(nombre, output_field=CharField(max_length=255))


def _existe_precio_mejor_por_gtin() -> QuerySet:
    """Busca en la base otro precio disponible mejor para el mismo GTIN."""
    return (
        Prices.visibles.filter(
            gtin_id=OuterRef("gtin_id"),
            is_available=True,
            price__isnull=False,
            currency__name__iexact="colones",
        )
        .annotate(final_price_otro=_expresion_precio_final())
        .filter(
            Q(final_price_otro__lt=OuterRef("final_price"))
            | Q(
                final_price_otro=OuterRef("final_price"),
                id__lt=OuterRef("id"),
            )
        )
    )


def _precio_minimo_disponible_por_gtin() -> QuerySet:
    """Devuelve el precio disponible más bajo de cada GTIN."""
    return (
        Prices.visibles.filter(
            gtin_id=OuterRef("gtin_id"),
            is_available=True,
            price__isnull=False,
            currency__name__iexact="colones",
        )
        .annotate(final_price_minimo=_expresion_precio_final())
        .order_by("final_price_minimo", "id")
        .values("final_price_minimo")
    )


def _consulta_precios_detalle(producto_id) -> QuerySet:
    """Prepara los precios y las diferencias de cada GTIN para el detalle."""
    precios = _anotar_precio_final(
        Prices.visibles.filter(
            gtin__product_id=producto_id,
            currency__name__iexact="colones",
        ).select_related("id_store", "currency", "gtin")
    ).annotate(
        final=Cast(Round("final_price"), output_field=IntegerField()),
        tienda=_expresion_tienda_limpia(),
    )

    minimo_para_diferencia = Subquery(
        _precio_minimo_disponible_por_gtin()[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    minimo_para_porcentaje = Subquery(
        _precio_minimo_disponible_por_gtin()[:1],
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    precios = precios.annotate(
        es_mejor=Case(
            When(
                Q(is_available=True)
                & Q(price__isnull=False)
                & ~Exists(_existe_precio_mejor_por_gtin()),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
        diferencia_vs_minimo=ExpressionWrapper(
            F("final_price") - minimo_para_diferencia,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        diferencia_porcentaje=ExpressionWrapper(
            (F("final_price") - minimo_para_porcentaje)
            * Value(Decimal("100"))
            / NullIf(minimo_para_porcentaje, Value(Decimal("0"))),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )

    return precios.order_by(
        "gtin_id",
        F("is_available").desc(),
        F("final_price").asc(nulls_last=True),
        "id_store__name",
        "id",
    )


def detalle_producto(request, pk):
    producto = get_object_or_404(
        Products.objects.select_related("brand", "category"), pk=pk
    )
    if request.method == "GET":  # publicar una reseña (POST) no es otra visita
        registrar_visita(request, producto.pk)
    imagen = (
        ProductImages.objects.filter(
            variant__product_id=producto.pk, is_main=True
        )
        .order_by("id")
        .values("image_url")
        .first()
    )
    variantes = ProductVariants.objects.filter(
        product_id=producto.pk
    ).order_by("id")
    precios = list(_consulta_precios_detalle(producto.pk))
    limite_precio_antiguo = timezone.now() - timedelta(
        hours=(24 * STALE_PRICE_DAYS)
    )
    for precio in precios:
        precio.desactualizado = precio.updated_at < limite_precio_antiguo
    grupos_precios = agrupar_precios_por_gtin(variantes, precios)

    resenas = (
        Reviews.objects.select_related("variant", "user")
        .filter(variant__product_id=producto.pk)
        .order_by("-created_at")
    )
    calificacion_promedio = resenas.aggregate(promedio=Avg("score"))[
        "promedio"
    ]
    estrellas_promedio = (
        int(calificacion_promedio + 0.5)
        if calificacion_promedio is not None
        else 0
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
                            review_photo.image.save(
                                photo.name, photo, save=False
                            )
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
                reporter=request.user,
                review_id__in=[resena.pk for resena in resenas],
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
            "grupos_precios": grupos_precios,
            "precios": precios,
            "resenas": resenas,
            "calificacion_promedio": calificacion_promedio,
            "estrellas_promedio": estrellas_promedio,
            "review_form": review_form,
            "ya_reseño": ya_reseño,
        },
    )


PRODUCTOS_POR_PAGINA = 24


def detalle_marca(request, slug):
    """Muestra la información de una marca y el catálogo de sus productos."""
    marca = get_object_or_404(Brands, slug=slug)
    productos = (
        Products.objects.filter(brand_id=marca.pk)
        .select_related("brand", "category")
        .order_by("name")
    )
    pagina = Paginator(productos, PRODUCTOS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    productos_pagina = con_imagen(pagina.object_list)

    return render(
        request,
        "products/detalle_marca.html",
        {
            "marca": marca,
            "productos": productos_pagina,
            "pagina": pagina,
        },
    )


def buscar(request):
    palabra = request.GET.get("q", "").strip()
    codigo_barras = None
    error_codigo = ""
    if palabra and palabra.isascii() and palabra.isdigit():
        codigo_barras = validar_codigo_barras(palabra)
        if codigo_barras:
            variante = (
                ProductVariants.objects.filter(
                    Q(gtin=codigo_barras.normalizado)
                    | Q(gtin=codigo_barras.codigo)
                )
                .only("product_id")
                .first()
            )
            if variante:
                return redirect("detalle_producto", pk=variante.product_id)
            error_codigo = translate_text(
                "No encontramos ningún producto registrado con ese código de barras."
            )
        else:
            error_codigo = codigo_barras.motivo
    categoria = _parametro_de_consulta(
        request, "categoria", "category", "categoria_id", "category_id"
    )
    marca = _parametro_de_consulta(
        request, "marca", "brand", "marca_id", "brand_id"
    )
    categoria_actual = _categoria_por_filtro(categoria)
    marca_actual = _marca_por_filtro(marca)
    pagina = _pagina_de_variantes(
        request, "" if error_codigo else palabra, categoria, marca
    )
    corregida = None
    if palabra and not error_codigo and not pagina.paginator.count:
        # «¿Quiso decir…?»: si no hay nada, se busca con las palabras del catálogo más parecidas.
        corregida = corregir_busqueda(palabra)
        if corregida:
            pagina = _pagina_de_variantes(request, corregida, categoria, marca)
    variantes_pagina = con_imagen_variante(con_precio_minimo(pagina))
    return render(
        request,
        "products/buscar.html",
        {
            "palabra": palabra,
            "error_codigo": error_codigo,
            "corregida": corregida,
            "categoria_seleccionada": (
                str(categoria_actual.pk)
                if categoria_actual is not None
                else ""
            ),
            "marca_seleccionada": (
                str(marca_actual.pk) if marca_actual is not None else ""
            ),
            "categorias": Categories.objects.order_by("name"),
            "marcas": Brands.objects.order_by("name"),
            "pagina": pagina,
            "variantes": variantes_pagina,
        },
    )


def _pagina_de_variantes(request, palabra, categoria, marca):
    """La página pedida (de PRODUCTOS_POR_PAGINA en PRODUCTOS_POR_PAGINA) de la búsqueda."""
    variantes = buscar_variantes_por_nombre(palabra, categoria, marca)
    return Paginator(variantes, PRODUCTOS_POR_PAGINA).get_page(
        request.GET.get("pagina")
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

    return (
        Categories.objects.filter(name__iexact=texto).order_by("name").first()
    )


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
    """Busca familias para vistas de catálogo; la búsqueda pública usa variantes."""
    productos = buscar_productos(palabra)
    productos = filtrar_por_categoria(productos, categoria)
    return filtrar_por_marca(productos, marca)


def buscar_variantes_por_nombre(
    nombre: str, categoria=None, marca=None
) -> QuerySet[ProductVariants]:
    """Busca variantes por presentación, producto o marca.

    La búsqueda no distingue mayúsculas de minúsculas y puede acotarse con
    una categoría y una marca, ambas opcionales. Cada GTIN es un resultado
    independiente aunque comparta la familia de producto con otra variante.
    """
    variantes = buscar_variantes(nombre)
    variantes = filtrar_por_categoria(variantes, categoria)
    return filtrar_por_marca(variantes, marca)


def obtener_precios_por_gtin(
    gtin: str, solo_disponibles: bool = True
) -> QuerySet:
    """Obtiene y rankea todos los precios de un GTIN, de menor a mayor.

    Se excluyen los precios nulos y, por defecto, las ofertas no disponibles.
    Los precios empatados reciben el mismo puesto de ranking.
    """
    return precios_por_gtin(gtin, solo_disponibles)


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
    """Busca variantes y devuelve las opciones de cada GTIN por ranking.

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
            {
                "error": translate_text(
                    "Debe indicar el nombre del producto a comparar."
                )
            },
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
                "precios": [_serializar_precio(precio) for precio in precios],
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
