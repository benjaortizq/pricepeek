"""Lectores del catálogo de cada tienda: qué productos publica y sus datos.

Cada tienda es un módulo con:
    NOMBRE                  el nombre de la tienda, como queda en la tabla stores
    listar_urls(http)       las URLs de sus páginas de producto
    obtener_ficha(url, http) la Ficha del producto, o None si la página no es de un producto
    PAUSA                   (opcional) segundos entre peticiones, si la tienda necesita que se vaya más despacio
"""

from . import gollo, monge
from .base import Ficha

TIENDAS = {
    "gollo": gollo,
    "monge": monge,
}

__all__ = ["Ficha", "TIENDAS"]
