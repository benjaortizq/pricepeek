"""Búsqueda de productos y variantes por nombre o marca."""

from django.db.models import Q

from .models import ProductImages, ProductVariants, Products


def buscar_productos(palabra):
    """Familias de producto cuyo nombre o marca contiene la palabra."""
    productos = Products.objects.select_related("brand", "category").order_by("name")
    palabra = (palabra or "").strip()
    if palabra:
        productos = productos.filter(Q(name__icontains=palabra) | Q(brand__name__icontains=palabra))
    return productos


def buscar_variantes(palabra):
    """Variantes cuya presentación, producto o marca coincide con la palabra.

    Cada variante tiene su propio GTIN, por lo que dos presentaciones de una
    misma familia de producto quedan como resultados independientes.
    """
    variantes = ProductVariants.objects.select_related(
        "product", "product__brand", "product__category"
    )
    palabra = (palabra or "").strip()
    if palabra:
        variantes = variantes.filter(
            Q(name__icontains=palabra)
            | Q(product__name__icontains=palabra)
            | Q(product__brand__name__icontains=palabra)
        )
    return variantes.order_by("product__name", "name", "gtin")


def con_imagen(productos):
    """Devuelve los productos con .imagen_url (la principal, o None).

    Hace una consulta por producto, así que pase solo los que se van a mostrar (ya paginados).
    """
    productos = list(productos)
    for producto in productos:
        imagen = ProductImages.objects.filter(variant__product_id=producto.pk).order_by("-is_main", "id").first()
        producto.imagen_url = imagen.image_url if imagen else None
    return productos


def con_imagen_variante(variantes):
    """Devuelve las variantes con .imagen_url (la principal, o None).

    La imagen pertenece a la variante, no a las demás presentaciones de la
    misma familia de producto.
    """
    variantes = list(variantes)
    for variante in variantes:
        imagen = (
            ProductImages.objects.filter(variant_id=variante.pk)
            .order_by("-is_main", "id")
            .first()
        )
        variante.imagen_url = imagen.image_url if imagen else None
    return variantes
