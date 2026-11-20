"""Búsqueda de productos por nombre o marca."""

from django.db.models import Q

from .models import ProductImages, Products


def buscar_productos(palabra):
    """Productos cuyo nombre o marca contiene la palabra (sin importar mayúsculas)."""
    productos = Products.objects.select_related("brand", "category").order_by("name")
    palabra = (palabra or "").strip()
    if palabra:
        productos = productos.filter(Q(name__icontains=palabra) | Q(brand__name__icontains=palabra))
    return productos


def con_imagen(productos):
    """Devuelve los productos con .imagen_url (la principal; si no hay, la primera; o None).

    Trae las imágenes de todos en una sola consulta (con la base en Supabase, cada consulta
    tarda ~80 ms). Pase solo los que se van a mostrar (ya paginados).
    """
    productos = list(productos)
    imagenes = (
        ProductImages.objects.filter(variant__product_id__in=[producto.pk for producto in productos])
        .order_by("variant__product_id", "-is_main", "id")
        .values_list("variant__product_id", "image_url")
    )
    primera = {}
    for producto_id, url in imagenes:
        primera.setdefault(producto_id, url)
    for producto in productos:
        producto.imagen_url = primera.get(producto.pk)
    return productos
