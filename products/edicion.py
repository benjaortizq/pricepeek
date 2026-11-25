"""Edición de los datos generales de un producto desde el panel de administración.

Issue «Edición de datos generales de productos»: el administrador cambia el nombre, la marca,
la categoría, la descripción y la imagen de un producto del catálogo.

Son datos del producto, no de una tienda: el nombre, la marca, la categoría y la descripción
viven en ``products`` y la imagen en ``product_images`` (la principal de cada presentación).
Los precios de las tiendas (``prices``, lo que maneja cada empresa) apuntan a la presentación
por su código de barras, así que todas las tiendas que ofrecen el producto muestran lo mismo:
no hay una copia por tienda que actualizar. La obtención de datos de cada hora solo crea
productos nuevos, no vuelve a escribir los que ya existen, así que no deshace estos cambios.

Las imágenes que sube el administrador se guardan en el almacenamiento de archivos (Supabase
Storage en producción). Su enlace firmado vence en una hora, así que en ``product_images``
queda el de la vista ``imagen_de_producto`` (de este sitio), que cada vez redirige a uno vigente.
"""

import re
import uuid
from dataclasses import dataclass, field

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from ingestion.catalogo import _clave, arreglar_secuencias, secuencias_atrasadas

from .correccion import olvidar_vocabulario
from .models import Brands, ProductImages, ProductVariants

CARPETA_DE_IMAGENES = "productos/"
# El nombre de una imagen subida, sin la carpeta: «<id del producto>/<32 letras hexadecimales>.<extensión>».
NOMBRE_DE_IMAGEN = re.compile(r"\d+/[0-9a-f]{32}\.(?:jpg|png|webp|gif)")
EXTENSION_POR_FORMATO = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def url_de_imagen_subida(nombre):
    """El enlace que queda en product_images para una imagen subida (sin la carpeta)."""
    return reverse("imagen_de_producto", kwargs={"nombre": nombre})


def nombre_de_imagen_subida(url):
    """Lo contrario de url_de_imagen_subida: el nombre en el almacenamiento, o None si es de una tienda."""
    base = url_de_imagen_subida("x")[:-1]
    nombre = (url or "").removeprefix(base) if (url or "").startswith(base) else ""
    return CARPETA_DE_IMAGENES + nombre if NOMBRE_DE_IMAGEN.fullmatch(nombre) else None


def marca_con_nombre(nombre):
    """(marca, es_nueva). Se compara como en la obtención de datos (ingestion.catalogo):
    «Black + Decker», «black-decker» y «BLACK+DECKER» son la misma marca. La nueva no se guarda aquí."""
    clave = _clave(nombre)
    slugs = set()
    for marca in Brands.objects.order_by("id"):
        if clave in (_clave(marca.name), _clave(marca.slug)):
            return marca, False
        slugs.add(marca.slug)
    base = slugify(nombre) or clave or "marca"
    slug, numero = base, 2
    while slug in slugs:
        slug, numero = f"{base}-{numero}", numero + 1
    ahora = timezone.now()
    return Brands(name=nombre.strip(), slug=slug, created_at=ahora, updated_at=ahora), True


def imagen_actual(producto):
    """La imagen que muestra el detalle del producto: la principal de su primera presentación."""
    return (
        ProductImages.objects.filter(variant__product_id=producto.pk, is_main=True)
        .order_by("id")
        .values_list("image_url", flat=True)
        .first()
    )


@dataclass
class Edicion:
    cambios: list = field(default_factory=list)  # en español, para el mensaje: ["el nombre", "la marca"]
    marca_nueva: bool = False


def editar_producto(producto, *, nombre, marca, categoria, descripcion, imagen=None, imagen_url=""):
    """Guarda los datos generales del producto. imagen: un archivo de forms.ImageField; imagen_url: un enlace.

    Si el producto tiene varias presentaciones, la imagen nueva queda como la principal de todas.
    """
    edicion = Edicion()
    marca, edicion.marca_nueva = marca_con_nombre(marca)
    descripcion = descripcion.strip() or None
    anteriores = {
        "el nombre": (producto.name, nombre),
        "la marca": (producto.brand_id, marca.pk),
        "la categoría": (producto.category_id, categoria.pk),
        "la descripción": (producto.description or None, descripcion),
    }
    edicion.cambios = [campo for campo, (antes, despues) in anteriores.items() if antes != despues]

    subida = None
    if imagen:
        # Se sube antes de la transacción: es una petición a Supabase Storage y no debe dejar la base esperando.
        extension = EXTENSION_POR_FORMATO[imagen.image.format]
        subida = default_storage.save(f"{CARPETA_DE_IMAGENES}{producto.pk}/{uuid.uuid4().hex}.{extension}", imagen)
        imagen_url = url_de_imagen_subida(subida.removeprefix(CARPETA_DE_IMAGENES))

    try:
        with transaction.atomic():
            ahora = timezone.now()
            if edicion.marca_nueva:
                _arreglar_secuencia(Brands)
                marca.save()
            if edicion.cambios:
                producto.name, producto.brand, producto.category, producto.description = nombre, marca, categoria, descripcion
                producto.updated_at = ahora
                producto.save(update_fields=["name", "brand", "category", "description", "updated_at"])
            reemplazadas = _cambiar_imagen(producto, imagen_url, ahora) if imagen_url else None
    except Exception:
        if subida:
            default_storage.delete(subida)
        raise
    if reemplazadas is not None:
        edicion.cambios.append("la imagen")
        transaction.on_commit(lambda: _borrar_imagenes_sin_uso(reemplazadas))
    if {"el nombre", "la marca"} & set(edicion.cambios):
        olvidar_vocabulario()  # el «¿quiso decir…?» de la búsqueda conoce las palabras de los nombres y las marcas
    return edicion


def _cambiar_imagen(producto, url, ahora):
    """Pone url como la imagen principal de cada presentación. None si ya era esa en todas.

    Devuelve los enlaces que se reemplazaron, para borrar del almacenamiento las imágenes subidas
    que ya nadie usa.
    """
    variantes = list(ProductVariants.objects.filter(product_id=producto.pk).values_list("id", flat=True))
    principales = ProductImages.objects.filter(variant_id__in=variantes, is_main=True)
    actuales = list(principales.values_list("variant_id", "image_url"))
    con_imagen = {variante for variante, _ in actuales}
    sin_imagen = [variante for variante in variantes if variante not in con_imagen]
    if not sin_imagen and all(actual == url for _, actual in actuales):
        return None
    principales.exclude(image_url=url).update(image_url=url, updated_at=ahora)
    if sin_imagen:
        ultimas = dict(
            ProductImages.objects.filter(variant_id__in=sin_imagen)
            .values("variant_id")
            .annotate(ultima=Max("number_image"))
            .values_list("variant_id", "ultima")
        )
        _arreglar_secuencia(ProductImages)
        ProductImages.objects.bulk_create(
            ProductImages(
                variant_id=variante,
                image_url=url,
                is_main=True,
                number_image=(ultimas.get(variante) or 0) + 1,
                created_at=ahora,
                updated_at=ahora,
            )
            for variante in sin_imagen
        )
    return {actual for _, actual in actuales if actual != url}


def _arreglar_secuencia(modelo):
    """Si alguien insertó filas con el id escrito a mano, el contador de ids quedó atrás (ver
    ingestion.catalogo.secuencias_atrasadas) y la fila nueva chocaría con una que ya existe."""
    arreglar_secuencias(secuencias_atrasadas([modelo]))


def _borrar_imagenes_sin_uso(urls):
    for url in urls:
        nombre = nombre_de_imagen_subida(url)
        if nombre and not ProductImages.objects.filter(image_url=url).exists():
            default_storage.delete(nombre)
