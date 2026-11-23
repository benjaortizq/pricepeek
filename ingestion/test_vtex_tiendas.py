"""Pruebas del lector del catálogo de Walmart y Maxipali (VTEX), con respuestas reales de su API."""

import copy
import json
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from .categorias import ABARROTES, ELECTRODOMESTICOS, categoria_para
from .models import StoreProduct
from .scrapers import ProductoNoEncontrado, vtex as api
from .test_productos_tienda import GTIN_IPHONE, ProductosDeTiendaTestCase
from .test_scrapers import HttpFalso, muestra
from .tiendas import TIENDAS
from .tiendas.vtex import TiendaVtex, maxipali, walmart

URL_LECHE = "https://www.walmart.co.cr/leche-dos-pinos-semidescremada-1-l-4/p"
URL_GRANOLA = "https://www.walmart.co.cr/granola-lustig-original-300-g-6/p"
URL_IPHONE = "https://www.walmart.co.cr/apple-iphone-17-8gb-256g-neg-768-6-8/p"
PRODUCTOS_0 = "https://www.walmart.co.cr/sitemap/product-0.xml"
PRODUCTOS_1 = "https://www.walmart.co.cr/sitemap/product-1.xml"


def respuesta_api(nombre):
    return json.loads(muestra(nombre))


LECHE = respuesta_api("vtex_walmart_leche_api.json")
IPHONE = respuesta_api("vtex_walmart_iphone17_api.json")  # agotado: la tienda no muestra precio
# El mismo iPhone, disponible y con la oferta (precio) de la leche.
IPHONE_CON_PRECIO = copy.deepcopy(IPHONE)
IPHONE_CON_PRECIO[0]["items"][0]["sellers"][0]["commertialOffer"] = copy.deepcopy(
    LECHE[0]["items"][0]["sellers"][0]["commertialOffer"]
)


class VtexListarUrlsTests(SimpleTestCase):
    def test_estan_registradas(self):
        self.assertIs(TIENDAS["walmart"], walmart)
        self.assertIs(TIENDAS["maxipali"], maxipali)
        self.assertEqual((walmart.NOMBRE, maxipali.NOMBRE), ("Walmart", "Maxipali"))

    def test_lista_las_paginas_de_producto_de_los_sitemaps_de_productos(self):
        http = HttpFalso({
            walmart.SITEMAP: muestra("vtex_walmart_sitemap.xml"),
            PRODUCTOS_0: muestra("vtex_walmart_sitemap_productos_0.xml"),
            PRODUCTOS_1: muestra("vtex_walmart_sitemap_productos_1.xml"),
        })
        # Fuera: la categoría (/lacteos), la URL con "?", la de otro dominio y la repetida.
        self.assertEqual(walmart.listar_urls(http), [URL_LECHE, URL_GRANOLA, URL_IPHONE])
        self.assertNotIn("https://www.walmart.co.cr/sitemap/brand-0.xml", http.pedidas)

    def test_es_url_de_producto(self):
        self.assertTrue(walmart.es_url_de_producto(URL_LECHE))
        self.assertFalse(walmart.es_url_de_producto("https://www.walmart.co.cr/p"))
        self.assertFalse(maxipali.es_url_de_producto(URL_LECHE))


class VtexFichaTests(SimpleTestCase):
    def ficha(self, url, respuesta):
        return walmart.obtener_ficha(url, HttpFalso({api.url_api(url): respuesta}))

    def test_ficha_de_la_leche(self):
        ficha = self.ficha(URL_LECHE, LECHE)
        self.assertEqual(ficha.nombre, "Leche Semidescremada Dos Pinos -1 L")
        self.assertEqual(ficha.marca, "Dos Pinos")  # no "DOS PINOS"
        self.assertEqual(ficha.sku, "8969")
        self.assertEqual(ficha.categoria, "Lácteos > Leche > Leche Semi y Descremada")
        self.assertEqual(categoria_para(ficha.categoria), ABARROTES)
        self.assertEqual((ficha.oferta.precio_final, ficha.oferta.disponible, ficha.oferta.gtins), (1050, True, ("7441001601064",)))
        self.assertTrue(ficha.imagen_url.startswith("https://walmartcr.vteximg.com.br/arquivos/ids/752338/"))
        self.assertEqual(ficha.codigos_invalidos, ())

    def test_ficha_del_iphone_agotado(self):
        ficha = self.ficha(URL_IPHONE, IPHONE)
        self.assertEqual((ficha.marca, ficha.modelo, ficha.color), ("Apple", "iPhone 17", "Negro"))
        self.assertEqual(ficha.categoria, "Electrónica > Celulares > APPLE")
        self.assertEqual(categoria_para(ficha.categoria), ELECTRODOMESTICOS)
        self.assertEqual((ficha.oferta.precio_final, ficha.oferta.disponible, ficha.oferta.gtins), (None, False, (GTIN_IPHONE,)))

    def test_producto_que_ya_no_esta_no_es_ficha(self):
        self.assertIsNone(self.ficha(URL_LECHE, []))

    def test_codigo_de_barras_invalido(self):
        respuesta = copy.deepcopy(LECHE)
        respuesta[0]["items"][0]["ean"] = "7441001601065"  # el dígito verificador no calza
        ficha = self.ficha(URL_LECHE, respuesta)
        self.assertEqual(ficha.oferta.gtins, ())
        self.assertEqual([codigo for codigo, _ in ficha.codigos_invalidos], ["7441001601065"])

    def test_toma_la_primera_presentacion_disponible(self):
        respuesta = copy.deepcopy(IPHONE)
        disponible = copy.deepcopy(LECHE[0]["items"][0])
        respuesta[0]["items"].append(disponible)
        ficha = self.ficha(URL_IPHONE, respuesta)
        self.assertEqual((ficha.oferta.disponible, ficha.oferta.gtins), (True, ("7441001601064",)))

    def test_el_extractor_de_precios_sigue_igual(self):
        http = HttpFalso({api.url_api(URL_LECHE): LECHE})
        [oferta] = api.extraer(URL_LECHE, http)
        self.assertEqual((oferta.precio_final, oferta.gtins), (1050, ("7441001601064",)))
        with self.assertRaises(ProductoNoEncontrado):
            api.extraer(URL_LECHE, HttpFalso({api.url_api(URL_LECHE): []}))


class ObtenerProductosDeWalmartTests(ProductosDeTiendaTestCase):
    def test_obtiene_los_productos_y_el_iphone_coincide_por_codigo_de_barras(self):
        respuestas = {
            walmart.SITEMAP: muestra("vtex_walmart_sitemap.xml"),
            PRODUCTOS_0: muestra("vtex_walmart_sitemap_productos_0.xml"),
            PRODUCTOS_1: muestra("vtex_walmart_sitemap_productos_1.xml"),
            api.url_api(URL_LECHE): LECHE,
            api.url_api(URL_GRANOLA): [],  # desactivado
            api.url_api(URL_IPHONE): IPHONE_CON_PRECIO,
        }
        salida = StringIO()
        with mock.patch("ingestion.management.commands.obtener_productos.ClienteHttp", return_value=HttpFalso(respuestas)):
            call_command("obtener_productos", "--tienda", "walmart", stdout=salida)

        self.assertIn("3 páginas · 2 productos · 1 con coincidencia sugerida · 1 no eran productos · 0 fallos", salida.getvalue())
        iphone = StoreProduct.objects.get(url=URL_IPHONE)
        self.assertEqual((iphone.store_name, iphone.suggested_gtin, iphone.match_reason), ("Walmart", GTIN_IPHONE, "mismo código de barras"))
        leche = StoreProduct.objects.get(url=URL_LECHE)
        self.assertEqual((leche.brand, leche.barcodes, leche.final_price), ("Dos Pinos", ["7441001601064"], 1050))


class AvisosYVariosFiltrosTests(ProductosDeTiendaTestCase):
    RESPUESTAS = {
        walmart.SITEMAP: muestra("vtex_walmart_sitemap.xml"),
        PRODUCTOS_0: muestra("vtex_walmart_sitemap_productos_0.xml"),
        PRODUCTOS_1: muestra("vtex_walmart_sitemap_productos_1.xml"),
        api.url_api(URL_LECHE): LECHE,
        api.url_api(URL_GRANOLA): [],
        api.url_api(URL_IPHONE): IPHONE,
    }

    def test_avisa_mientras_lee_los_sitemaps(self):
        avisos = []
        walmart.listar_urls(HttpFalso(self.RESPUESTAS), avisar=avisos.append)
        self.assertEqual(avisos, ["sitemap 2/2 · 7 páginas hasta ahora"])

    def test_varios_filtros_en_una_sola_corrida(self):
        salida = StringIO()
        with mock.patch("ingestion.management.commands.obtener_productos.ClienteHttp", return_value=HttpFalso(self.RESPUESTAS)):
            call_command("obtener_productos", "--tienda", "walmart", "--filtro", "iphone", "LECHE", "--dry-run", stdout=salida)
        self.assertIn("Leyendo la lista de productos de Walmart...\n  sitemap 2/2", salida.getvalue())
        self.assertIn("Walmart: 3 páginas en su lista; se van a revisar 2.", salida.getvalue())


def busqueda(ruta, desde, por_pagina=2):
    return (
        f"https://www.walmart.co.cr/api/catalog_system/pub/products/search/{ruta}"
        f"?_from={desde}&_to={desde + por_pagina - 1}&O=OrderByNameASC"
    )


def de_la_busqueda(slug):
    producto = copy.deepcopy(LECHE[0])
    producto["linkText"] = slug
    return producto


def pagina(slug):
    return f"https://www.walmart.co.cr/{slug}/p"


ARBOL = "https://www.walmart.co.cr/api/catalog_system/pub/category/tree/4"


@mock.patch.object(TiendaVtex, "POR_PAGINA", 2)
class ProductosPorCategoriaTests(SimpleTestCase):
    def test_pide_paginas_hasta_que_una_viene_incompleta(self):
        http = HttpFalso({
            busqueda("electronica/celulares", 2500): [],  # cabe en una sola búsqueda
            busqueda("electronica/celulares", 0): [de_la_busqueda("a"), de_la_busqueda("b")],
            busqueda("electronica/celulares", 2): [de_la_busqueda("c")],
        })
        avisos = []
        productos = walmart.productos_de_categorias(http, ["electronica/celulares"], avisar=avisos.append)
        self.assertEqual(list(productos), [pagina("a"), pagina("b"), pagina("c")])
        self.assertEqual(avisos, ["electronica/celulares: 3 productos"])

    def test_la_ruta_se_escribe_como_en_la_url_de_la_tienda(self):
        http = HttpFalso({
            busqueda("electronica/linea-blanca", 2500): [],
            busqueda("electronica/linea-blanca", 0): [de_la_busqueda("a")],
        })
        productos = walmart.productos_de_categorias(http, ["/Electrónica/Línea Blanca/"])
        self.assertEqual(list(productos), [pagina("a")])

    @mock.patch.object(TiendaVtex, "ULTIMO_DESDE", 2)
    def test_si_la_busqueda_no_deja_ver_todos_va_por_subcategoria(self):
        http = HttpFalso({
            busqueda("electronica", 2): [de_la_busqueda("c"), de_la_busqueda("d")],  # llena: puede haber más
            ARBOL: [
                {"url": "https://www.walmart.co.cr/lacteos", "children": []},
                {
                    "url": "https://www.walmart.co.cr/electronica",
                    "children": [
                        {"url": "https://www.walmart.co.cr/electronica/celulares", "children": []},
                        {"url": "https://www.walmart.co.cr/electronica/audio", "children": []},
                    ],
                },
            ],
            busqueda("electronica/celulares", 2): [],
            busqueda("electronica/celulares", 0): [de_la_busqueda("a"), de_la_busqueda("b")],
            busqueda("electronica/audio", 2): [],
            busqueda("electronica/audio", 0): [de_la_busqueda("b")],  # en las dos subcategorías
        })
        avisos = []
        productos = walmart.productos_de_categorias(http, ["electronica"], avisar=avisos.append)
        self.assertEqual(list(productos), [pagina("a"), pagina("b")])
        self.assertIn("se busca en sus 2 subcategorías", avisos[0])
        self.assertEqual(avisos[1:], ["electronica/celulares: 2 productos", "electronica/audio: 0 productos"])
        self.assertNotIn(busqueda("electronica", 0), http.pedidas)  # no lee la categoría entera de balde

    def test_avisa_si_la_categoria_no_tiene_productos(self):
        avisos = []
        http = HttpFalso({busqueda("electronik", 2500): [], busqueda("electronik", 0): []})
        walmart.productos_de_categorias(http, ["electronik"], avisar=avisos.append)
        self.assertIn("ningún producto", avisos[0])


class ObtenerPorCategoriaTests(ProductosDeTiendaTestCase):
    def test_no_vuelve_a_pedir_cada_producto(self):
        http = HttpFalso({
            busqueda("electronica/celulares", 2500, por_pagina=50): [],
            busqueda("electronica/celulares", 0, por_pagina=50): [LECHE[0], IPHONE_CON_PRECIO[0]],
        })
        salida = StringIO()
        with mock.patch("ingestion.management.commands.obtener_productos.ClienteHttp", return_value=http):
            call_command("obtener_productos", "--tienda", "walmart", "--categoria", "electronica/celulares", stdout=salida)

        self.assertIn("Walmart: 2 productos en esas categorías; se van a revisar 2.", salida.getvalue())
        self.assertIn("2 páginas · 2 productos · 1 con coincidencia sugerida", salida.getvalue())
        self.assertEqual(len(http.pedidas), 2)  # las dos de la búsqueda; ninguna por producto
        iphone = StoreProduct.objects.get(url=URL_IPHONE)
        self.assertEqual((iphone.suggested_gtin, iphone.category), (GTIN_IPHONE, "Electrónica > Celulares > APPLE"))

    def test_solo_para_las_tiendas_que_tienen_categorias(self):
        with self.assertRaisesMessage(CommandError, "--categoria solo sirve para automercado, maxipali, peri, walmart."):
            call_command("obtener_productos", "--tienda", "gollo", "--categoria", "celulares", stdout=StringIO())


class SinPrecioTests(ProductosDeTiendaTestCase):
    def correr(self, *argumentos):
        http = HttpFalso({
            busqueda("electronica/celulares", 2500, por_pagina=50): [],
            busqueda("electronica/celulares", 0, por_pagina=50): [LECHE[0], IPHONE[0]],
        })
        salida = StringIO()
        with mock.patch("ingestion.management.commands.obtener_productos.ClienteHttp", return_value=http):
            call_command("obtener_productos", "--tienda", "walmart", "--categoria", "electronica/celulares", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_no_guarda_los_que_vienen_sin_precio(self):
        salida = self.correr()
        self.assertIn("2 páginas · 1 productos", salida)
        self.assertIn("1 sin precio (no se guardaron)", salida)
        self.assertTrue(StoreProduct.objects.filter(url=URL_LECHE).exists())
        self.assertFalse(StoreProduct.objects.filter(url=URL_IPHONE).exists())

    def test_los_ya_guardados_se_actualizan_aunque_se_queden_sin_precio(self):
        StoreProduct.objects.create(store_name="Walmart", url=URL_IPHONE, name="iPhone 17", final_price=900000)
        self.correr("--todos")
        iphone = StoreProduct.objects.get(url=URL_IPHONE)
        self.assertEqual((iphone.final_price, iphone.is_available), (None, False))
