"""Búsqueda de productos por nombre o marca.

La búsqueda acepta las cosas como la gente las escribe:
- sin importar mayúsculas ni tildes: "cafe" encuentra "Café" y "pina" encuentra "Piña";
- con letras repetidas de más o de menos: "tuto" encuentra "TUTTO" y "galeta", "Galleta";
- sin signos: "mms" encuentra "M&M's" y "cocacola", "Coca-Cola".
Cada palabra tiene que estar en el nombre o en la marca, en cualquier orden: "leche dos pinos".
"""

import re
import unicodedata

from django.db.models import Case, IntegerField, Q, Value, When

from .models import ProductImages, ProductVariants, Products

# Las letras que en el catálogo pueden venir con tilde (en mayúscula o minúscula).
_CON_TILDE = {
    "a": "aáàäâ",
    "e": "eéèëê",
    "i": "iíìïî",
    "o": "oóòöô",
    "u": "uúùüû",
    "n": "nñ",
}
# Entre dos letras puede haber un signo (Coca-Cola, M&M's), pero no un espacio: si no, "sal"
# encontraría "galleta[s a l]a crema". Sirve igual en Postgres y en SQLite (Python).
_SIGNO = r"[^\w\s]?"


def _sin_tildes(texto):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def palabra_normalizada(palabra):
    """ "Café" -> "cafe", "M&M's" -> "mms": en minúscula, sin tildes y solo con letras y números."""
    return re.sub(r"[^a-z0-9]", "", _sin_tildes(palabra.lower()))


def _patron_de_letra(letra):
    if letra.isdigit():
        return letra  # los números, tal cual: 100 no es 10
    variantes = _CON_TILDE.get(letra, letra)
    return (
        f"[{variantes}{variantes.upper()}]+"
        if len(variantes) > 1
        else f"{letra}+"
    )


def patron_de_busqueda(palabra):
    """La expresión regular que encuentra la palabra escrita parecido, o "" si no tiene letras ni números.

    "tuto" -> t+ u+ t+ o+ (con un signo opcional entre letras): en el producto, cada letra puede
    venir repetida ("Tutto"). Lo que se escribe repetido sí se exige: "mm" son dos emes, para que
    "m&m" no encuentre cualquier cosa con una m.
    """
    return _SIGNO.join(map(_patron_de_letra, palabra_normalizada(palabra)))


def buscar_productos(palabra):
    """Productos que tienen cada palabra (escrita parecido) en el nombre o en la marca.

    Primero los que tienen el texto tal cual (lo que se encontraba antes) y después los parecidos;
    dentro de cada grupo, por nombre.
    """
    palabra = (palabra or "").strip()
    productos = Products.objects.select_related("brand", "category")
    patrones = [
        patron for patron in map(patron_de_busqueda, palabra.split()) if patron
    ]
    if not patrones:
        return productos.order_by("name")
    for patron in patrones:
        productos = productos.filter(
            Q(name__iregex=patron) | Q(brand__name__iregex=patron)
        )
    tal_cual = Q(name__icontains=palabra) | Q(brand__name__icontains=palabra)
    orden = Case(
        When(tal_cual, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    return productos.annotate(parecido=orden).order_by("parecido", "name")


def buscar_variantes(palabra):
    """Variantes que tienen cada palabra (escrita parecido) en la presentación, el producto o la marca.

    Acepta lo mismo que ``buscar_productos``: sin importar mayúsculas, tildes, letras repetidas
    ni signos. Cada variante tiene su propio GTIN, por lo que dos presentaciones de una misma
    familia de producto quedan como resultados independientes. Primero las que tienen el texto
    tal cual y después las parecidas; dentro de cada grupo, por producto y presentación.
    """
    variantes = ProductVariants.objects.select_related(
        "product", "product__brand", "product__category"
    )
    palabra = (palabra or "").strip()
    patrones = [
        patron for patron in map(patron_de_busqueda, palabra.split()) if patron
    ]
    if not patrones:
        return variantes.order_by("product__name", "name", "gtin")
    for patron in patrones:
        variantes = variantes.filter(
            Q(name__iregex=patron)
            | Q(product__name__iregex=patron)
            | Q(product__brand__name__iregex=patron)
        )
    tal_cual = (
        Q(name__icontains=palabra)
        | Q(product__name__icontains=palabra)
        | Q(product__brand__name__icontains=palabra)
    )
    orden = Case(
        When(tal_cual, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    return variantes.annotate(parecido=orden).order_by(
        "parecido", "product__name", "name", "gtin"
    )


def _con_imagen(objetos, campo):
    """Les pone .imagen_url a los objetos (la principal; si no hay, la primera; o None).

    Trae las imágenes de todos en una sola consulta (con la base en Supabase, cada consulta
    tarda ~80 ms). ``campo`` es por dónde se juntan las imágenes con los objetos.
    """
    objetos = list(objetos)
    imagenes = (
        ProductImages.objects.filter(
            **{f"{campo}__in": [objeto.pk for objeto in objetos]}
        )
        .order_by(campo, "-is_main", "id")
        .values_list(campo, "image_url")
    )
    primera = {}
    for objeto_id, url in imagenes:
        primera.setdefault(objeto_id, url)
    for objeto in objetos:
        objeto.imagen_url = primera.get(objeto.pk)
    return objetos


def con_imagen(productos):
    """Devuelve los productos con .imagen_url, en una sola consulta.

    Pase solo los que se van a mostrar (ya paginados).
    """
    return _con_imagen(productos, "variant__product_id")


def con_imagen_variante(variantes):
    """Devuelve las variantes con .imagen_url, en una sola consulta.

    La imagen pertenece a la variante, no a las demás presentaciones de la
    misma familia de producto. Pase solo las que se van a mostrar (ya paginadas).
    """
    return _con_imagen(variantes, "variant_id")
