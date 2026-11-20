"""Catálogo de Gollo (gollo.com, Magento 2).

- Lista de productos: el sitemap de productos que anuncia su robots.txt. Las páginas de
  producto terminan en el código de Gollo y "/p":
  https://www.gollo.com/iphone-17-apple-256-gb-ram-8gb-6-3-48mp-48mp-negro-esim-5003050226/p
- Datos: ver ingestion/scrapers/gollo.py. A diferencia de Monge, Gollo sí publica el GTIN,
  así que la coincidencia con el catálogo se puede hacer por código de barras.
- Ojo: el mismo producto comercial puede tener otro GTIN que en otra tienda. El iPhone 17
  negro de Gollo es el modelo MG6J4BE/A (195950643480) y el de Walmart es otro (0195950643411).
"""

from urllib.parse import urlsplit

from ..scrapers import gollo as paginas
from .base import Ficha, urls_del_sitemap

NOMBRE = "Gollo"
DOMINIO = "www.gollo.com"
# Gollo tiene protección contra bots en su CDN: las páginas que no están en caché le responden
# 403 a este scraper (a la librería requests). Se va más despacio por cortesía y, si los 403
# siguen, obtener_productos se detiene solo. Para usar esta tienda en serio hace falta que
# Gollo lo autorice (por ejemplo, un feed de productos o permitir este cliente).
PAUSA = 4
SITEMAP = f"https://{DOMINIO}/media/sitemap/sitemap_gollo_cr_sitemap_products_gollo_cr.xml"


def es_url_de_producto(url):
    partes = urlsplit(url)
    ruta = partes.path
    # /catalog/... está prohibido en su robots.txt
    return partes.netloc == DOMINIO and not partes.query and ruta.endswith("/p") and ruta.count("/") == 2


def listar_urls(http):
    """Las URLs de producto del sitemap, en su orden y sin repetir."""
    return list(dict.fromkeys(u for u in urls_del_sitemap(http.texto(SITEMAP)) if es_url_de_producto(u)))


def obtener_ficha(url, http):
    """La ficha del producto, o None si la página no es de un producto."""
    html = http.texto(url)
    leido = paginas.leer_pagina(html)
    if leido is None:
        return None
    producto, specs, oferta = leido
    gtin_publicado = specs.get("GTIN", "")
    _, motivo = paginas.codigo_de_barras(gtin_publicado)
    marca = producto.get("brand")
    marca = marca.get("name") if isinstance(marca, dict) else marca
    modelo = " ".join(dict.fromkeys(m for m in (specs.get("Modelo comercial"), specs.get("MPN")) if m))
    return Ficha(
        url=url,
        nombre=str(producto.get("name") or "").strip(),
        oferta=oferta,
        sku=specs.get("Código") or str(producto.get("sku") or ""),
        marca=str(marca or specs.get("Marca") or "").strip(),
        modelo=modelo,
        color=specs.get("Color", ""),
        categoria=specs.get("Tipo de producto", ""),
        imagen_url=paginas.imagen_principal(html, producto),
        codigos_invalidos=((gtin_publicado, motivo),) if motivo else (),
    )
