"""Catálogo de Monge (tiendamonge.com, Magento 2).

- Lista de productos: el sitemap que anuncia su robots.txt. Las páginas de producto
  tienen un solo segmento y casi siempre terminan en el código de Monge:
  https://www.tiendamonge.com/celular-5g-apple-iphone-17-negro-8gb-ram-256gb-199387
- Datos: el bloque ld+json de cada página (nombre, modelo, color, imagen, precios,
  disponibilidad) y las categorías del BreadcrumbList. La marca sale del widget de
  Flixmedia (data-flix-brand), porque el ld+json no la trae.
- No publica el código de barras: los "gtin" de su ld+json son su código interno.
- No se usa su API (GraphQL está bloqueado y REST pide credenciales) ni su búsqueda
  (robots.txt prohíbe /search, /catalogsearch/ y las URLs con "?").
"""

from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..scrapers import ld_json
from .base import Ficha, urls_del_sitemap

NOMBRE = "Monge"
DOMINIO = "www.tiendamonge.com"
SITEMAP = f"https://{DOMINIO}/media/sitemap_tienda_monge_cr.xml"


def es_url_de_producto(url):
    partes = urlsplit(url)
    ruta = partes.path.strip("/")
    return (
        partes.netloc == DOMINIO
        and not partes.query
        and ruta != ""
        and "/" not in ruta
    )


def listar_urls(http, avisar=None):
    """Las URLs que pueden ser de un producto, en el orden del sitemap y sin repetir."""
    urls = []
    for submapa in urls_del_sitemap(http.texto(SITEMAP)):
        if "-urls" in submapa:  # el otro es el de imágenes
            urls += urls_del_sitemap(http.texto(submapa))
    return list(dict.fromkeys(u for u in urls if es_url_de_producto(u)))


class _Flixmedia(HTMLParser):
    """Lee los atributos data-flix-* de la etiqueta del widget de Flixmedia."""

    def __init__(self):
        super().__init__()
        self.datos = {}

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if not self.datos and "data-flix-brand" in atributos:
            self.datos = {
                k.removeprefix("data-flix-"): (v or "").strip()
                for k, v in atributos.items()
                if k.startswith("data-flix-")
            }


def datos_de_flixmedia(html):
    lector = _Flixmedia()
    lector.feed(html)
    lector.close()
    return lector.datos


def _texto(valor):
    return str(valor).strip() if isinstance(valor, (str, int, float)) else ""


def obtener_ficha(url, http):
    """La ficha del producto, o None si la página no es de un producto."""
    html = http.texto(url)
    producto = ld_json.producto_de_la_pagina(html)
    if producto is None:
        return None
    imagen = producto.get("image")
    if isinstance(imagen, list):
        imagen = imagen[0] if imagen else ""
    if isinstance(imagen, dict):
        imagen = imagen.get("url")
    return Ficha(
        url=url,
        nombre=_texto(producto.get("name")),
        oferta=ld_json.oferta_del_producto(
            producto
        ),  # sin códigos de barras: Monge no los publica
        sku=_texto(producto.get("sku")),
        marca=datos_de_flixmedia(html).get("brand", ""),
        modelo=_texto(producto.get("model")),
        color=_texto(producto.get("color")),
        categoria=" > ".join(ld_json.ruta_de_categorias(html)),
        imagen_url=_texto(imagen),
    )
