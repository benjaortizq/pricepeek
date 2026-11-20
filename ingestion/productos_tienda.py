"""Productos de las tiendas: guardarlos, sugerir su variante del catálogo y vincularlos (SCRUM-56)."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from products.models import Currencies, Prices, ProductVariants, Stores

from .actualizacion import formas_del_codigo
from .emparejamiento import PUNTAJE_PARA_SUGERIR, candidatas, mejor_coincidencia, rasgos
from .models import Incident, StoreProduct
from .scrapers import Oferta

Status = StoreProduct.Status
# Solo se vuelve a buscar coincidencia en lo que nadie ha revisado todavía.
REVISABLES = (Status.NO_MATCH, Status.SUGGESTED)
# Una coincidencia por código de barras es exacta: crear_productos la vincula sin revisión.
MOTIVO_MISMO_CODIGO = "mismo código de barras"
# Se resta cuando el nombre coincide pero la tienda publica otro código de barras.
CASTIGO_CODIGO_DISTINTO = 20


class NoSePuedeVincular(Exception):
    pass


def candidatas_del_catalogo():
    return candidatas(ProductVariants.objects.select_related("product__brand"))


def _por_codigo_de_barras(codigos, candidatas_):
    if not codigos:
        return None
    buscadas = set().union(*(formas_del_codigo(c) for c in codigos))
    return next((c for c in candidatas_ if formas_del_codigo(c.variante.gtin) & buscadas), None)


def sugerir(producto, candidatas_):
    """Deja como sugerencia la variante del catálogo que mejor coincide (o ninguna)."""
    por_codigo = _por_codigo_de_barras(producto.barcodes, candidatas_)
    if por_codigo is not None:
        mejor = (por_codigo, 100, MOTIVO_MISMO_CODIGO)
    else:
        rasgos_tienda = rasgos(producto.name, producto.product_model, producto.color)
        mejor = mejor_coincidencia(rasgos_tienda, producto.brand, candidatas_)
        if mejor is not None and producto.barcodes:
            # El nombre coincide pero el código no: puede ser otra versión (el iPhone de Gollo es
            # otro modelo regional que el de Walmart). Se sugiere igual, con aviso y menos puntaje.
            candidata, puntaje, motivo = mejor
            aviso = f"código distinto: la tienda dice {', '.join(producto.barcodes)} y el catálogo {candidata.variante.gtin}"
            puntaje -= CASTIGO_CODIGO_DISTINTO
            mejor = (candidata, puntaje, f"{aviso} · {motivo}") if puntaje >= PUNTAJE_PARA_SUGERIR else None
    if mejor is None:
        producto.status, producto.suggested_gtin, producto.score, producto.match_reason = Status.NO_MATCH, "", None, ""
    else:
        candidata, puntaje, motivo = mejor
        producto.status = Status.SUGGESTED
        producto.suggested_gtin = candidata.variante.gtin
        producto.score = puntaje
        producto.match_reason = motivo[:255]
    return producto


def _recortar(texto, largo):
    return (texto or "")[:largo]


def guardar_ficha(ficha, tienda, candidatas_, guardar=True):
    """Crea o actualiza el producto de la tienda (por su URL) y le busca coincidencia."""
    producto = StoreProduct.objects.filter(url=ficha.url).first() or StoreProduct(url=ficha.url)
    producto.store_name = tienda
    producto.sku = _recortar(ficha.sku, 64)
    producto.name = _recortar(ficha.nombre, 255)
    producto.brand = _recortar(ficha.marca, 100)
    producto.product_model = _recortar(ficha.modelo, 100)
    producto.color = _recortar(ficha.color, 60)
    producto.category = _recortar(ficha.categoria, 255)
    producto.image_url = ficha.imagen_url if len(ficha.imagen_url) <= 1000 else ""
    producto.list_price = ficha.oferta.precio_lista
    producto.final_price = ficha.oferta.precio_final
    producto.is_available = ficha.oferta.disponible
    producto.barcodes = list(ficha.oferta.gtins)
    if producto.status in REVISABLES:
        sugerir(producto, candidatas_)
    if guardar:
        producto.save()
    return producto


def registrar_codigos_invalidos(ficha, tienda, guardar=True):
    """Una incidencia por cada código de barras inválido que publicó la tienda (RF-38)."""
    incidencias = [
        Incident(
            kind=Incident.Kind.INVALID_BARCODE,
            store_name=tienda[: Incident.NAME_MAX_LENGTH],
            product_name=ficha.nombre[: Incident.NAME_MAX_LENGTH],
            gtin=str(codigo)[: Incident.GTIN_MAX_LENGTH],
            reason=f"{motivo}\n{ficha.url}",
        )
        for codigo, motivo in ficha.codigos_invalidos
    ]
    if guardar and incidencias:
        Incident.objects.bulk_create(incidencias)
    return incidencias


def tienda_del_catalogo(nombre):
    """La fila de stores con ese nombre (algunos nombres traen un salto de línea); si no existe, se crea."""
    for tienda in Stores.objects.all():
        if tienda.name.strip().lower() == nombre.strip().lower():
            return tienda
    ahora = timezone.now()
    return Stores.objects.create(name=nombre, created_at=ahora, updated_at=ahora)


@transaction.atomic
def confirmar(producto):
    """Vincula el producto de la tienda con la variante sugerida: crea (o actualiza) su fila en prices."""
    variante = producto.suggested_variant
    if variante is None:
        raise NoSePuedeVincular("Elija primero la variante del catálogo.")
    tienda = tienda_del_catalogo(producto.store_name)
    precio = Prices.objects.filter(id_store=tienda, gtin_id=variante.gtin).first()
    if precio is not None and precio.product_web_url != producto.url:
        raise NoSePuedeVincular(
            f"«{variante.name}» ya tiene precio en {tienda.name.strip()} con otro enlace: {precio.product_web_url}"
        )

    ahora = timezone.now()
    if precio is None:
        colones = Currencies.objects.filter(name__iexact="colones").first()
        if colones is None:
            raise NoSePuedeVincular("No existe la moneda «colones» en la tabla currencies.")
        precio = Prices(id_store=tienda, gtin=variante, currency=colones, price=None, discount=Decimal("0.00"), created_at=ahora)
    if producto.final_price is not None:
        precio.price = producto.list_price or producto.final_price
        precio.discount = Oferta(producto.list_price, producto.final_price, True).descuento
    precio.is_available = producto.is_available
    precio.product_web_url = producto.url
    precio.updated_at = ahora
    precio.save()

    producto.status = Status.CONFIRMED
    producto.save(update_fields=["status", "updated_at"])
    return precio


def rechazar(producto):
    producto.status = Status.REJECTED
    producto.save(update_fields=["status", "updated_at"])
