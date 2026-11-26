"""Automercado: el precio viene en el estado JSON que la página trae incrustado.

    <script id="automercado-state" type="application/json">
      {"product-detail.ssr-algolia": {"products": [{"hits": [{"productID": "...",
        "storeDetail": {"01": {"basePrice": 3230, "amount": 2745, "productAvailable": true}, ...}}]}]}}
    </script>

Cada sucursal tiene su precio (basePrice = sin descuento, amount = con descuento) y no
siempre es el mismo. Se toma el precio que tiene la mayoría de las sucursales donde el
producto está disponible. La página no trae el código de barras.
"""

import json
import re
from collections import Counter
from html.parser import HTMLParser

from .base import Oferta, PrecioNoEncontrado, ProductoNoEncontrado, a_colones

ID_ESTADO = "automercado-state"


class _Estado(HTMLParser):
    def __init__(self):
        super().__init__()
        self.contenido = None
        self._dentro = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == ID_ESTADO:
            self._dentro = True
            self.contenido = ""

    def handle_endtag(self, tag):
        if tag == "script":
            self._dentro = False

    def handle_data(self, data):
        if self._dentro:
            self.contenido += data


def estado_de_la_pagina(html):
    lector = _Estado()
    lector.feed(html)
    lector.close()
    if lector.contenido is None:
        raise PrecioNoEncontrado(f"La página no trae el bloque {ID_ESTADO}.")
    try:
        return json.loads(lector.contenido)
    except ValueError:
        raise PrecioNoEncontrado(
            f"El bloque {ID_ESTADO} no es JSON válido."
        ) from None


def _id_de_la_url(url):
    encontrado = re.search(r"/id/([0-9a-fA-F-]{36})", url)
    return encontrado.group(1).lower() if encontrado else None


def extraer(url, http):
    estado = estado_de_la_pagina(http.texto(url))
    try:
        resultados = estado["product-detail.ssr-algolia"]["products"][0][
            "hits"
        ]
    except (KeyError, IndexError, TypeError):
        raise PrecioNoEncontrado(
            "El estado de la página no tiene el detalle del producto."
        ) from None
    if not resultados:
        raise ProductoNoEncontrado(
            "La tienda ya no tiene este producto en su catálogo."
        )

    id_url = _id_de_la_url(url)
    producto = next(
        (
            r
            for r in resultados
            if str(r.get("productID", "")).lower() == id_url
        ),
        resultados[0],
    )
    return [oferta_del_producto(producto)]


def oferta_del_producto(producto):
    """La Oferta de un producto de Algolia (el de la página o el de la búsqueda): el precio de la mayoría."""
    sucursales = (producto.get("storeDetail") or {}).values()
    precios = Counter(
        (a_colones(s.get("basePrice")), a_colones(s.get("amount")))
        for s in sucursales
        if s.get("productAvailable") and a_colones(s.get("amount"))
    )
    if not precios:
        if producto.get("productAvailable") is False or sucursales:
            return Oferta(None, None, False)
        raise PrecioNoEncontrado("El producto no trae precios por sucursal.")
    (lista, final), _ = precios.most_common(1)[0]
    return Oferta(lista or final, final, True)
