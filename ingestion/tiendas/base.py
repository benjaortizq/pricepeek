"""Lo que devuelve el lector del catálogo de una tienda."""

import html
import re
from dataclasses import dataclass

from django.utils.text import slugify

from ..scrapers import Oferta


@dataclass(frozen=True)
class Ficha:
    """Un producto tal como lo publica la tienda."""

    url: str
    nombre: str
    oferta: Oferta
    sku: str = ""  # el código interno de la tienda (no es un código de barras)
    marca: str = ""
    modelo: str = ""
    color: str = ""
    categoria: str = ""  # "Celulares y Tablets > Celulares > Apple"
    imagen_url: str = ""
    # Códigos de barras que publicó la tienda pero no son válidos: (código, motivo). Quedan como incidencia (RF-38).
    codigos_invalidos: tuple = ()


def urls_del_sitemap(xml):
    """Las URLs de las etiquetas <loc> de un sitemap (o de un índice de sitemaps)."""
    return [
        html.unescape(url.strip())
        for url in re.findall(r"<loc>(.*?)</loc>", xml, re.S)
    ]


def ruta_de_busqueda(texto):
    """La categoría como sale en la URL de la tienda: "Electrónica/Línea Blanca" -> "electronica/linea-blanca"."""
    return "/".join(
        slugify(parte) for parte in str(texto).split("/") if slugify(parte)
    )
