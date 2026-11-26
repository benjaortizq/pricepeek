r"""Tiendas que publican el precio con datos estructurados de schema.org (ld+json).

    <script type="application/ld+json">
      {"@type": "Product", "sku": "38962", "offers": {"@type": "Offer",
       "priceSpecification": {"price": 6350, "priceCurrency": "CRC"},
       "availability": "https://schema.org/InStock"}}
    </script>

Peri y Megasuper (Next.js): el bloque no trae el código de barras, pero los datos de la
página sí, al lado del mismo sku: \"sku\":\"38962\",\"ean\":[\"088169002950,7501058631442\"].
No publican un precio de lista aparte, así que se guarda el que se cobra, sin descuento.

Monge (Magento): trae el precio de lista y el de oferta en priceSpecification
(priceType ListPrice y SalePrice). Sus campos "gtin" y "gtin8" son su código interno,
no un código de barras, así que no se usan.
"""

import json
import re
from html.parser import HTMLParser

from .base import Oferta, PrecioNoEncontrado, ProductoNoEncontrado, a_colones

AGOTADO = ("OutOfStock", "SoldOut", "Discontinued")


class _BloquesLdJson(HTMLParser):
    """Junta el contenido de cada <script type="application/ld+json">."""

    def __init__(self):
        super().__init__()
        self.bloques = []
        self._dentro = False

    def handle_starttag(self, tag, attrs):
        tipo = (dict(attrs).get("type") or "").strip().lower()
        if tag == "script" and tipo == "application/ld+json":
            self._dentro = True
            self.bloques.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._dentro = False

    def handle_data(self, data):
        if self._dentro:
            self.bloques[-1] += data


def objetos_ld_json(html):
    """Todos los objetos JSON de los bloques ld+json de la página (incluidos los de @graph)."""
    lector = _BloquesLdJson()
    lector.feed(html)
    lector.close()
    for bloque in lector.bloques:
        try:
            datos = json.loads(bloque)
        except ValueError:
            continue
        for objeto in datos if isinstance(datos, list) else [datos]:
            if isinstance(objeto, dict):
                yield objeto
                yield from (
                    o
                    for o in objeto.get("@graph") or []
                    if isinstance(o, dict)
                )


def _es_de_tipo(objeto, tipo):
    tipos = objeto.get("@type")
    return tipo in (tipos if isinstance(tipos, list) else [tipos])


def producto_de_la_pagina(html):
    """El primer objeto Product de la página, o None."""
    return next(
        (o for o in objetos_ld_json(html) if _es_de_tipo(o, "Product")), None
    )


def ruta_de_categorias(html):
    """Las categorías del BreadcrumbList, sin "Inicio", "Productos" ni el producto mismo."""
    migas = next(
        (o for o in objetos_ld_json(html) if _es_de_tipo(o, "BreadcrumbList")),
        None,
    )
    if migas is None:
        return []
    elementos = sorted(
        (e for e in migas.get("itemListElement") or [] if isinstance(e, dict)),
        key=lambda e: e.get("position") or 0,
    )
    nombres = [
        (e.get("item") or {}).get("name") or e.get("name") or ""
        for e in elementos
    ]
    nombres = [
        n.strip() for n in nombres[:-1] if n and n.strip()
    ]  # el último es el producto
    return [
        n for n in nombres if n.lower() not in ("inicio", "home", "productos")
    ]


def _ofertas(offers):
    """Aplana "offers": puede ser una oferta, una lista o un AggregateOffer con su propia lista."""
    ofertas = []
    for oferta in offers if isinstance(offers, list) else [offers]:
        if not isinstance(oferta, dict):
            continue
        if isinstance(oferta.get("offers"), (list, dict)):
            ofertas += _ofertas(oferta["offers"])
        else:
            ofertas.append(oferta)
    return ofertas


def _precios(oferta):
    """(precio de lista, precio final) de una oferta. El de lista es None si la tienda no lo publica."""
    especificaciones = oferta.get("priceSpecification")
    especificaciones = (
        especificaciones
        if isinstance(especificaciones, list)
        else [especificaciones]
    )
    especificaciones = [e for e in especificaciones if isinstance(e, dict)]
    moneda = oferta.get("priceCurrency") or next(
        (e.get("priceCurrency") for e in especificaciones), None
    )
    if moneda and moneda != "CRC":
        raise PrecioNoEncontrado(
            f"El precio viene en {moneda}, no en colones."
        )

    def es_de_lista(especificacion):
        return str(especificacion.get("priceType") or "").endswith("ListPrice")

    lista = next(
        (
            a_colones(e.get("price"))
            for e in especificaciones
            if es_de_lista(e)
        ),
        None,
    )
    final = a_colones(oferta.get("price"))
    if final is None:
        final = next(
            (
                a_colones(e.get("price"))
                for e in especificaciones
                if not es_de_lista(e) and e.get("price") is not None
            ),
            None,
        )
    if final is None:
        final = a_colones(oferta.get("lowPrice")) or lista
    return lista, final


def oferta_del_producto(producto, gtins=()):
    """La Oferta del objeto Product (precio de lista, precio final y disponibilidad)."""
    ofertas = _ofertas(producto.get("offers"))
    if not ofertas:
        raise PrecioNoEncontrado(
            "Los datos del producto no traen ninguna oferta."
        )
    oferta = ofertas[0]
    lista, final = _precios(oferta)
    disponible = not any(
        estado in str(oferta.get("availability") or "") for estado in AGOTADO
    )
    if final is None and disponible:
        raise PrecioNoEncontrado("Los datos del producto no traen el precio.")
    return Oferta(lista or final, final, disponible, tuple(gtins))


def codigos_de_barras(html, sku):
    """Los EAN que la página asocia al sku (las comillas pueden venir escapadas: \\")."""
    if not sku:
        return ()
    patron = (
        r'\\?"sku\\?":\\?"'
        + re.escape(str(sku))
        + r'\\?",\\?"ean\\?":\[([^\]]*)\]'
    )
    encontrado = re.search(patron, html)
    return (
        tuple(re.findall(r"\d{8,14}", encontrado.group(1)))
        if encontrado
        else ()
    )


def es_producto_inexistente(html):
    """Next.js responde 200 (no 404) cuando el producto no existe: en vez del componente de la
    página del producto (/p/[slug]/page-….js) carga el de "no encontrado" (/p/[slug]/not-found-….js)."""
    return (
        "/p/%5Bslug%5D/not-found-" in html
        and "/p/%5Bslug%5D/page-" not in html
    )


def extraer(url, http):
    html = http.texto(url)
    producto = producto_de_la_pagina(html)
    if producto is None:
        if es_producto_inexistente(html):
            raise ProductoNoEncontrado(
                "La tienda muestra la página de «no encontrado»: el producto ya no existe."
            )
        raise PrecioNoEncontrado(
            "La página no trae los datos del producto (ld+json)."
        )
    return [
        oferta_del_producto(
            producto, codigos_de_barras(html, producto.get("sku"))
        )
    ]
