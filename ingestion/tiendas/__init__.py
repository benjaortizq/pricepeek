"""Lectores del catálogo de cada tienda: qué productos publica y sus datos.

Cada tienda es un módulo (o un objeto, como las de VTEX) con:
    NOMBRE                  el nombre de la tienda, como queda en la tabla stores
    listar_urls(http, avisar=None)  las URLs de sus páginas de producto; si se tarda, puede ir
                            llamando a avisar(texto) para que se vea que avanza
    obtener_ficha(url, http) la Ficha del producto, o None si la página no es de un producto
    PAUSA                   (opcional) segundos entre peticiones, si la tienda necesita que se vaya más despacio

Las de VTEX tienen además productos_de_categorias(http, categorias, avisar=None) y
ficha_de_la_busqueda(url, producto), para --categoria de obtener_productos.
"""

from . import gollo, monge
from .base import Ficha
from .vtex import maxipali, walmart

TIENDAS = {
    "gollo": gollo,
    "maxipali": maxipali,
    "monge": monge,
    "walmart": walmart,
}

__all__ = ["Ficha", "TIENDAS"]
