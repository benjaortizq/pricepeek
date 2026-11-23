"""Extractores de precios: uno por plataforma de tienda en línea.

Cada extractor es una función extraer(url, http) que devuelve una lista de Oferta
(una por presentación que muestre la página) o lanza un ErrorExtraccion.
Para agregar una tienda que usa una plataforma conocida basta con agregar su dominio aquí.
"""

from urllib.parse import urlsplit

from . import automercado, gollo, ld_json, vtex
from .base import (
    ClienteHttp,
    CodigoDistinto,
    ErrorDescarga,
    ErrorExtraccion,
    Oferta,
    PrecioNoEncontrado,
    ProductoNoEncontrado,
)

EXTRACTORES = {
    "walmart.co.cr": vtex.extraer,
    "maxipali.co.cr": vtex.extraer,
    "automercado.cr": automercado.extraer,
    "peridomicilio.com": ld_json.extraer,
    "megasuper.com": ld_json.extraer,
    "tiendamonge.com": ld_json.extraer,
    "gollo.com": gollo.extraer,
}


def extractor_para(url):
    """El extractor que sirve para la URL, según su dominio, o None si la tienda no está soportada."""
    dominio = (urlsplit(url or "").hostname or "").removeprefix("www.")
    return EXTRACTORES.get(dominio)


__all__ = [
    "ClienteHttp",
    "CodigoDistinto",
    "ErrorDescarga",
    "ErrorExtraccion",
    "EXTRACTORES",
    "Oferta",
    "PrecioNoEncontrado",
    "ProductoNoEncontrado",
    "extractor_para",
]
