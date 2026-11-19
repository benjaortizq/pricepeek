"""Walmart y Maxipali usan VTEX, que tiene una API pública del catálogo.

En vez de leer el HTML se consulta la API con el mismo "slug" de la URL del producto:
    https://www.walmart.co.cr/apple-iphone-17-8gb-256g-neg-768-6-8/p
    https://www.walmart.co.cr/api/catalog_system/pub/products/search/apple-iphone-17-8gb-256g-neg-768-6-8/p
La respuesta trae, por cada presentación (item), el código de barras, el precio de lista,
el precio con descuento y si está disponible.
"""

from urllib.parse import urlsplit

from .base import Oferta, PrecioNoEncontrado, ProductoNoEncontrado, a_colones


def url_api(url_producto):
    partes = urlsplit(url_producto)
    ruta = partes.path.rstrip("/")
    if not ruta.endswith("/p") or ruta == "/p":
        raise PrecioNoEncontrado("La URL no tiene el formato de VTEX (…/nombre-del-producto/p).")
    slug = ruta.removesuffix("/p").strip("/")
    return f"{partes.scheme}://{partes.netloc}/api/catalog_system/pub/products/search/{slug}/p"


def extraer(url, http):
    productos = http.json(url_api(url))
    if not isinstance(productos, list):
        raise PrecioNoEncontrado("La API de VTEX devolvió algo que no es una lista de productos.")
    if not productos:
        raise ProductoNoEncontrado("La tienda ya no tiene este producto en su catálogo.")

    ofertas = []
    for item in productos[0].get("items") or []:
        vendedores = item.get("sellers") or []
        vendedor = next((v for v in vendedores if v.get("sellerDefault")), vendedores[0] if vendedores else None)
        if vendedor is None:
            continue
        detalle = vendedor.get("commertialOffer") or {}
        disponible = bool(detalle.get("IsAvailable"))
        # Cuando el producto está agotado, VTEX pone los precios en 0: se dejan como "sin precio".
        final = a_colones(detalle.get("Price")) if disponible else None
        lista = a_colones(detalle.get("ListPrice")) if disponible else None
        ean = str(item.get("ean") or "").strip()
        ofertas.append(Oferta(lista or final, final, disponible, (ean,) if ean else ()))
    if not ofertas:
        raise PrecioNoEncontrado("La API de VTEX no trae precios para este producto.")
    return ofertas
