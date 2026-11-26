"""Gollo (gollo.com, Magento 2).

- Precio final y disponibilidad: el ld+json del producto (offers).
- Precio de lista: el "price" del mismo objeto Product (Gollo lo pone ahí, fuera de offers).
- Código de barras, modelo, MPN, color y tipo de producto: la tabla de especificaciones,
      <td class="col data" data-th="GTIN">195950643480</td>
  A veces el GTIN viene sin el cero inicial de un UPC-A (11 dígitos) o como "0" (sin código).
- No se usa su API: robots.txt prohíbe /rest/ y /graphql.
"""

import re
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser

from products.barcodes import validar_codigo_barras

from . import ld_json
from .base import PrecioNoEncontrado, a_colones


class _Especificaciones(HTMLParser):
    """Junta las celdas <td data-th="Nombre">valor</td> de la tabla de especificaciones."""

    def __init__(self):
        super().__init__()
        self.datos = {}
        self._clave = None
        self._texto = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            clave = (dict(attrs).get("data-th") or "").strip()
            if clave:
                self._clave, self._texto = clave, []

    def handle_endtag(self, tag):
        if tag == "td" and self._clave is not None:
            self.datos.setdefault(
                self._clave, " ".join("".join(self._texto).split())
            )
            self._clave = None

    def handle_data(self, data):
        if self._clave is not None:
            self._texto.append(data)


def especificaciones(html):
    lector = _Especificaciones()
    lector.feed(html)
    lector.close()
    return lector.datos


def codigo_de_barras(valor):
    """(código válido, "") o ("", motivo por el que no sirve). Vacío o "0" es ("", ""): no tiene código."""
    codigo = re.sub(r"\s", "", valor or "")
    if not codigo.strip("0"):
        return "", ""
    if (
        len(codigo) == 11
        and codigo.isdigit()
        and validar_codigo_barras(codigo.zfill(12))
    ):
        return codigo.zfill(
            12
        ), ""  # un UPC-A al que se le perdió el cero inicial
    resultado = validar_codigo_barras(codigo)
    return (codigo, "") if resultado else ("", resultado.motivo)


def imagen_principal(html, producto):
    encontrada = re.search(
        r'<meta property="og:image" content="([^"]+)"', html
    )
    if encontrada:
        return unescape(encontrada.group(1))
    imagen = producto.get("image") or ""
    return (
        f"https://www.gollo.com/media/catalog/product{imagen}"
        if imagen.startswith("/")
        else imagen
    )


def leer_pagina(html):
    """(objeto Product del ld+json, especificaciones, Oferta) o None si la página no es de un producto."""
    producto = ld_json.producto_de_la_pagina(html)
    if producto is None:
        return None
    specs = especificaciones(html)
    gtin, _ = codigo_de_barras(specs.get("GTIN"))
    oferta = ld_json.oferta_del_producto(producto, (gtin,) if gtin else ())
    lista = a_colones(producto.get("price"))
    if lista and oferta.precio_final and lista > oferta.precio_final:
        oferta = replace(oferta, precio_lista=lista)
    return producto, specs, oferta


def extraer(url, http):
    leido = leer_pagina(http.texto(url))
    if leido is None:
        raise PrecioNoEncontrado(
            "La página no trae los datos del producto (ld+json)."
        )
    return [leido[2]]
