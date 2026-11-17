from django.core.paginator import Paginator
from django.db.models import F, Q, DecimalField, ExpressionWrapper, QuerySet, Window
from django.db.models.functions import Coalesce, Rank
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from .busqueda import buscar_productos, con_imagen
from .models import Prices, ProductImages, ProductVariants, Products
from django.views.decorators.http import require_GET

from reviews.models import Reviews

from .models import (
    Brands,
    Categories,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
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
    if texto.isdecimal():
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
    if texto.isdecimal():
        return queryset.filter(**{f"{prefijo}brand_id": int(texto)})

    return queryset.filter(
        Q(**{f"{prefijo}brand__name__iexact": texto})
        | Q(**{f"{prefijo}brand__slug__iexact": texto})
    )


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
    
    precios = Prices.objects.select_related("id_store", "currency").annotate(
        # Usamos Coalesce por si el campo 'discount' es nulo (lo tratamos como 0).
        # Usamos ExpressionWrapper para cuidar la precisión decimal (DecimalField).
        final_price=ExpressionWrapper(
            F("price") * (1.0 - Coalesce(F("discount"), 0.0)),
            output_field=DecimalField(max_digits=10, decimal_places=0)
        )
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
        "precio": precio.price * (1.0 - float(precio.discount)),
        "moneda": precio.currency.symbol,
        "descuento": float(precio.discount),
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
