"""Pruebas del lector del catálogo de Automercado (por Algolia)."""

import json
from io import StringIO
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.core.management import call_command
from django.test import SimpleTestCase

from .models import StoreProduct
from .scrapers import Oferta
from .test_productos_tienda import GTIN_IPHONE, ProductosDeTiendaTestCase
from .test_scrapers import URL_AUTOMERCADO
from .tiendas import TIENDAS
from .tiendas.automercado import (
    automercado,
    ficha_del_producto,
    url_del_producto,
)

LLAVE = "llave-publica-de-busqueda"
INICIO = f'<script id="automercado-state" type="application/json">{json.dumps({"client_keys": {"algoliaApiKey": LLAVE}})}</script>'


def de_algolia(
    id_producto,
    nombre,
    categoria="ABARROTES > CEREALES",
    marca="KELLOGGS",
    precios=((3230, 2745),) * 3,
):
    niveles = categoria.split(" > ")
    return {
        "productID": id_producto,
        "ecomDescription": nombre,
        "marca": marca,
        "productNumber": "139295",
        "imageUrl": "https://ik.imagekit.io/autoenlinea/imgjpg/139295.jpg",
        "hierarchicalCategories": {
            f"lvl{i}": " > ".join(niveles[: i + 1])
            for i in range(len(niveles))
        },
        "productAvailable": True,
        "storeDetail": {
            f"{numero:02d}": {
                "basePrice": lista,
                "amount": final,
                "productAvailable": True,
            }
            for numero, (lista, final) in enumerate(precios, 1)
        },
    }


class AlgoliaFalso:
    """Responde como la página de inicio y Algolia, según los parámetros de cada consulta."""

    def __init__(self, conteos, por_categoria, sucursales=("01", "02", "03")):
        self.conteos, self.por_categoria, self.sucursales = (
            conteos,
            por_categoria,
            sucursales,
        )
        self.categorias_pedidas = []
        self.campos = None

    def texto(self, url):
        assert url == automercado.INICIO, url
        return INICIO

    def json(self, url):
        parametros = {
            clave: valor[0]
            for clave, valor in parse_qs(urlsplit(url).query).items()
        }
        assert parametros["x-algolia-api-key"] == LLAVE
        if parametros.get("facets") == '["*"]':
            return {
                "hits": [],
                "facets": {
                    f"storeDetail.{s}.amount": {"1": 1}
                    for s in self.sucursales
                },
            }
        if "facets" in parametros:
            return {"hits": [], "facets": {"categoryPageId": self.conteos}}
        [filtro] = json.loads(parametros["facetFilters"])
        nombre = filtro.removeprefix("categoryPageId:")
        self.categorias_pedidas.append(nombre)
        self.campos = json.loads(parametros["attributesToRetrieve"])
        return {"hits": self.por_categoria.get(nombre, [])}


ZUCARITAS = de_algolia(
    "a4a118ed-f90a-4468-8929-9a3425246bc3",
    "CEREAL ENDULZADO ZUCARITAS KELLOGGS caja 490 g",
    "ABARROTES > CEREALES > CEREALES ENDULZADOS",
)
CHOCO = de_algolia("b1", "CEREAL CHOCO KRISPIS KELLOGGS caja 300 g")
GALLETA = de_algolia(
    "c1",
    "GALLETA MARIA POZUELO paquete 200 g",
    "ABARROTES > GALLETAS",
    marca="POZUELO",
)
LECHE = de_algolia(
    "d1",
    "LECHE SEMIDESCREMADA DOS PINOS caja 1 l",
    "LÁCTEOS y EMBUTIDOS",
    marca="DOS PINOS",
)
CONTEOS = {
    "ABARROTES": 3,
    "ABARROTES > CEREALES": 2,
    "ABARROTES > GALLETAS": 1,
    "LÁCTEOS y EMBUTIDOS": 1,
}
POR_CATEGORIA = {
    "ABARROTES > CEREALES": [ZUCARITAS, CHOCO],
    "ABARROTES > GALLETAS": [GALLETA],
    "LÁCTEOS y EMBUTIDOS": [LECHE],
}


@mock.patch("ingestion.tiendas.automercado.POR_CONSULTA", 2)
class ProductosDeAutomercadoTests(SimpleTestCase):
    def leer(self, categorias=(), avisos=None):
        self.http = AlgoliaFalso(CONTEOS, POR_CATEGORIA)
        return automercado.productos_de_categorias(
            self.http,
            list(categorias),
            avisar=None if avisos is None else avisos.append,
        )

    def test_esta_registrada(self):
        self.assertIs(TIENDAS["automercado"], automercado)
        self.assertEqual(automercado.NOMBRE, "Automercado")
        self.assertFalse(
            hasattr(automercado, "listar_urls")
        )  # su sitemap no trae productos

    def test_lee_todas_las_categorias_y_parte_las_que_tienen_demasiados(self):
        avisos = []
        productos = self.leer(avisos=avisos)
        self.assertEqual(
            list(productos),
            [url_del_producto(p) for p in (ZUCARITAS, CHOCO, GALLETA, LECHE)],
        )
        self.assertEqual(
            self.http.categorias_pedidas,
            [
                "ABARROTES > CEREALES",
                "ABARROTES > GALLETAS",
                "LÁCTEOS y EMBUTIDOS",
            ],
        )
        self.assertEqual(
            avisos,
            [
                "abarrotes: 3 productos, más de los 2 por consulta; se piden sus 2 subcategorías",
                "abarrotes/cereales: 2 productos",
                "abarrotes/galletas: 1 productos",
                "lacteos-y-embutidos: 1 productos",
            ],
        )

    def test_por_categoria_con_la_ruta_de_su_url(self):
        avisos = []
        productos = self.leer(
            ["abarrotes/cereales", "Lácteos y Embutidos", "electronica"],
            avisos,
        )
        self.assertEqual(
            list(productos),
            [url_del_producto(p) for p in (ZUCARITAS, CHOCO, LECHE)],
        )
        self.assertIn("electronica: no existe en Automercado", avisos[0])

    def test_de_cada_sucursal_solo_pide_el_precio_y_si_esta_disponible(self):
        self.leer(["abarrotes/galletas"])
        self.assertIn("storeDetail.03.amount", self.http.campos)
        self.assertIn("storeDetail.01.productAvailable", self.http.campos)
        self.assertNotIn("storeDetail", self.http.campos)


class FichaDeAutomercadoTests(SimpleTestCase):
    def test_url_como_la_arma_su_sitio(self):
        self.assertEqual(url_del_producto(ZUCARITAS), URL_AUTOMERCADO)
        self.assertEqual(url_del_producto({"ecomDescription": "SIN ID"}), "")

    def test_al_nombre_sin_tamano_se_le_agrega_la_presentacion(self):
        sin_tamano = {
            **de_algolia("g1", "CAFE INSTANTANEO CLASICO NESCAFE"),
            "productPresentation": "frasco 200 g",
        }
        con_tamano = {
            **de_algolia(
                "g2", "CHOCOLATE VARIADO GHIRARDELLI paquete 447.6 g"
            ),
            "productPresentation": "paquete 447,6 g",
        }
        self.assertEqual(
            ficha_del_producto("u1", sin_tamano).nombre,
            "CAFE INSTANTANEO CLASICO NESCAFE frasco 200 g",
        )
        self.assertEqual(
            ficha_del_producto("u2", con_tamano).nombre,
            "CHOCOLATE VARIADO GHIRARDELLI paquete 447.6 g",
        )

    def test_ficha(self):
        producto = de_algolia(
            "e1",
            "CEREAL ZUCARITAS KELLOGGS caja 490 g",
            "ABARROTES > CEREALES > CEREALES ENDULZADOS",
            precios=((3230, 2745), (3230, 2745), (3310, 2810)),
        )
        ficha = ficha_del_producto(
            "https://automercado.cr/p/x/id/e1", producto
        )
        self.assertEqual(
            (ficha.nombre, ficha.marca, ficha.sku),
            ("CEREAL ZUCARITAS KELLOGGS caja 490 g", "KELLOGGS", "139295"),
        )
        self.assertEqual(
            ficha.categoria, "ABARROTES > CEREALES > CEREALES ENDULZADOS"
        )
        self.assertEqual(
            ficha.imagen_url,
            "https://ik.imagekit.io/autoenlinea/imgjpg/139295.jpg",
        )
        self.assertEqual(
            ficha.oferta, Oferta(3230, 2745, True)
        )  # el de la mayoría de las sucursales
        self.assertEqual(
            ficha.oferta.gtins, ()
        )  # Automercado no publica el código de barras


class ObtenerProductosDeAutomercadoTests(ProductosDeTiendaTestCase):
    def test_lee_todo_su_catalogo_y_sugiere_por_el_nombre(self):
        iphone = de_algolia(
            "f1",
            "CELULAR APPLE IPHONE 17 256GB NEGRO",
            "TIENDA Y HOGAR > CELULARES",
            marca="APPLE",
        )
        http = AlgoliaFalso(
            {"TIENDA Y HOGAR": 2, "TIENDA Y HOGAR > CELULARES": 2},
            {"TIENDA Y HOGAR": [iphone, LECHE]},
        )
        salida = StringIO()
        with mock.patch(
            "ingestion.management.commands.obtener_productos.ClienteHttp",
            return_value=http,
        ):
            call_command(
                "obtener_productos", "--tienda", "automercado", stdout=salida
            )

        self.assertIn(
            "Buscando los productos de Automercado en: todas sus categorías...",
            salida.getvalue(),
        )
        self.assertIn(
            "Automercado: 2 productos; se van a revisar 2.", salida.getvalue()
        )
        self.assertIn(
            "2 páginas · 2 productos · 1 con coincidencia sugerida",
            salida.getvalue(),
        )
        producto = StoreProduct.objects.get(url=url_del_producto(iphone))
        self.assertEqual(
            (producto.store_name, producto.barcodes), ("Automercado", [])
        )
        self.assertEqual(
            (producto.status, producto.suggested_gtin),
            (StoreProduct.Status.SUGGESTED, GTIN_IPHONE),
        )
