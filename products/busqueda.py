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
    """Devuelve los productos con .imagen_url (la principal, o None).

    Hace una consulta por producto, así que pase solo los que se van a mostrar (ya paginados).
    """
    productos = list(productos)
    for producto in productos:
        imagen = ProductImages.objects.filter(variant__product_id=producto.pk).order_by("-is_main", "id").first()
        producto.imagen_url = imagen.image_url if imagen else None
    return productos
