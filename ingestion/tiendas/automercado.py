"""Catálogo de Automercado: sale de Algolia, el buscador que usa su sitio.

- Su sitemap solo trae categorías, y sus páginas cargan los productos en el navegador
  consultando Algolia con una llave pública de solo búsqueda. Aquí se hace esa misma consulta:
  la llave se lee de la página de inicio (client_keys.algoliaApiKey); la aplicación y el índice
  son los de la configuración de su sitio (algolia.appId y algoliaIndex.products).
- Cada consulta devuelve como máximo 1000 productos, así que se piden por categoría (la faceta
  categoryPageId: "ABARROTES", "ABARROTES > CEREALES"...). Si una tiene más de 1000, se piden
  sus subcategorías. Todo el catálogo (unos 20 000 productos) son unas 60 consultas.
- De cada sucursal solo se piden el precio y si está disponible: el detalle completo de las 24
  sucursales pesa diez veces más. El precio es el de la mayoría (como en scrapers/automercado.py).
- No publica el código de barras (upcLink viene vacío): sus productos no se pueden crear en el
  catálogo, solo vincularse por el nombre a los que ya están, como los de Monge. Por eso al
  nombre que no dice el tamaño se le agrega la presentación ("frasco 200 g").
- Las páginas de producto son https://automercado.cr/p/{nombre en minúsculas y con guiones}/id/{productID}.
"""

import json
from urllib.parse import urlencode

from django.utils.text import slugify

from ..emparejamiento import rasgos
from ..scrapers import PrecioNoEncontrado
from ..scrapers.automercado import estado_de_la_pagina, oferta_del_producto
from .base import Ficha, ruta_de_busqueda

APLICACION = "FU5XFX7KNL"
INDICE = "Product_CatalogueV2"
FACETA = "categoryPageId"
POR_CONSULTA = 1000  # lo más que devuelve Algolia para una consulta
CAMPOS = [
    "productID",
    "ecomDescription",
    "productPresentation",
    "marca",
    "productNumber",
    "imageUrl",
    "hierarchicalCategories",
    "productAvailable",
]
DE_CADA_SUCURSAL = ["amount", "basePrice", "productAvailable"]


def url_del_producto(producto):
    """La página del producto, como la arma su sitio, o "" si no trae su id."""
    id_producto = str(producto.get("productID") or "").strip()
    if not id_producto:
        return ""
    return f"https://automercado.cr/p/{slugify(producto.get('ecomDescription') or '') or 'producto'}/id/{id_producto}"


def ruta_de_la_categoria(nombre):
    """ "SNACK Y GOLOSINA > CONFITURAS Y CHOCOLATES" -> "snack-y-golosina/confituras-y-chocolates" (como en su URL)."""
    return ruta_de_busqueda(nombre.replace(">", "/"))


def nombre_con_presentacion(producto):
    """El nombre con la presentación ("frasco 200 g") si no dice el tamaño: casi la mitad no lo dice
    ("CAFE INSTANTANEO CLASICO NESCAFE"), y sin tamaño se confunde con el de otro tamaño."""
    nombre = " ".join(str(producto.get("ecomDescription") or "").split())
    presentacion = " ".join(
        str(producto.get("productPresentation") or "").split()
    )
    if presentacion and not rasgos(nombre).capacidades:
        return f"{nombre} {presentacion}"
    return nombre


def ficha_del_producto(url, producto):
    categorias = producto.get("hierarchicalCategories") or {}
    return Ficha(
        url=url,
        nombre=nombre_con_presentacion(producto),
        oferta=oferta_del_producto(producto),  # sin código de barras
        sku=str(producto.get("productNumber") or ""),
        marca=str(producto.get("marca") or "").strip(),
        categoria=str(categorias[max(categorias)])
        if categorias
        else "",  # la más específica: lvl2 > lvl1 > lvl0
        imagen_url=str(producto.get("imageUrl") or ""),
    )


class TiendaAutomercado:
    """No tiene listar_urls (su sitemap no trae productos): siempre se lee por productos_de_categorias."""

    NOMBRE = "Automercado"
    PAUSA = 1.5
    INICIO = "https://automercado.cr/"

    def __repr__(self):
        return "TiendaAutomercado()"

    def llave(self, http):
        estado = estado_de_la_pagina(http.texto(self.INICIO))
        try:
            return estado["client_keys"]["algoliaApiKey"]
        except (KeyError, TypeError):
            raise PrecioNoEncontrado(
                "La página de inicio no trae la llave de búsqueda (client_keys.algoliaApiKey)."
            ) from None

    @staticmethod
    def url_de_consulta(llave, **parametros):
        parametros = {
            k: json.dumps(v, ensure_ascii=False)
            if isinstance(v, (list, dict))
            else v
            for k, v in parametros.items()
        }
        credenciales = {
            "x-algolia-application-id": APLICACION,
            "x-algolia-api-key": llave,
        }
        return (
            f"https://{APLICACION}-dsn.algolia.net/1/indexes/{INDICE}?"
            + urlencode({**parametros, **credenciales})
        )

    def _consultar(self, http, llave, **parametros):
        respuesta = http.json(self.url_de_consulta(llave, **parametros))
        if not isinstance(respuesta, dict) or "hits" not in respuesta:
            raise PrecioNoEncontrado(
                "Algolia devolvió algo que no es una búsqueda."
            )
        return respuesta

    def categorias(self, http, llave):
        """{"ABARROTES > CEREALES": cuántos productos tiene} de todas las categorías."""
        respuesta = self._consultar(
            http,
            llave,
            query="",
            hitsPerPage=0,
            facets=[FACETA],
            maxValuesPerFacet=POR_CONSULTA,
        )
        return (respuesta.get("facets") or {}).get(FACETA) or {}

    def sucursales(self, http, llave):
        """Los números de las sucursales ("01", "02"...), según los campos storeDetail.NN.* del índice."""
        respuesta = self._consultar(
            http,
            llave,
            query="",
            hitsPerPage=0,
            facets=["*"],
            maxValuesPerFacet=1,
        )
        return sorted(
            {
                faceta.split(".")[1]
                for faceta in respuesta.get("facets") or {}
                if faceta.startswith("storeDetail.")
            }
        )

    def productos_de_categorias(self, http, categorias, avisar=None):
        """{URL de la página: producto de Algolia} de esas categorías ("abarrotes", "abarrotes/cereales"), o de todas."""
        avisar = avisar or (lambda texto: None)
        llave = self.llave(http)
        conteos = self.categorias(http, llave)
        campos = CAMPOS + [
            f"storeDetail.{s}.{c}"
            for s in self.sucursales(http, llave)
            for c in DE_CADA_SUCURSAL
        ]
        por_ruta = {ruta_de_la_categoria(nombre): nombre for nombre in conteos}
        if categorias:
            pendientes = []
            for ruta in map(ruta_de_busqueda, categorias):
                if ruta in por_ruta:
                    pendientes.append(por_ruta[ruta])
                else:
                    avisar(
                        f"{ruta}: no existe en Automercado. Es la ruta de su URL, por ejemplo abarrotes/cereales"
                    )
        else:
            pendientes = [nombre for nombre in conteos if ">" not in nombre]

        productos = {}
        while pendientes:
            nombre = pendientes.pop(0)
            ruta = ruta_de_la_categoria(nombre)
            if conteos[nombre] > POR_CONSULTA:
                nivel = nombre.count(">") + 1
                hijas = [
                    n
                    for n in conteos
                    if n.startswith(f"{nombre} >") and n.count(">") == nivel
                ]
                if hijas:
                    avisar(
                        f"{ruta}: {conteos[nombre]} productos, más de los {POR_CONSULTA} por consulta; se piden sus {len(hijas)} subcategorías"
                    )
                    pendientes[:0] = hijas
                    continue
                avisar(
                    f"{ruta}: tiene más de {POR_CONSULTA} productos y no tiene subcategorías: solo se leen {POR_CONSULTA}"
                )
            respuesta = self._consultar(
                http,
                llave,
                query="",
                hitsPerPage=POR_CONSULTA,
                page=0,
                facetFilters=[f"{FACETA}:{nombre}"],
                attributesToRetrieve=campos,
                attributesToHighlight=[],
                attributesToSnippet=[],
            )
            antes = len(productos)
            for producto in respuesta["hits"]:
                if url := url_del_producto(producto):
                    productos.setdefault(url, producto)
            avisar(f"{ruta}: {len(productos) - antes} productos")
        return productos

    def ficha_de_la_busqueda(self, url, producto):
        return ficha_del_producto(url, producto)


automercado = TiendaAutomercado()
