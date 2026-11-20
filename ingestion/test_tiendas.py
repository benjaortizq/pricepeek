"""Pruebas del lector del catálogo de Monge, con páginas reales guardadas en ingestion/muestras."""

from decimal import Decimal

from django.test import SimpleTestCase

from .scrapers import Oferta, extractor_para, ld_json
from .test_scrapers import HttpFalso, muestra
from .tiendas import TIENDAS, monge

URL_IPHONE = "https://www.tiendamonge.com/celular-5g-apple-iphone-17-negro-8gb-ram-256gb-199387"
URL_SAMSUNG = "https://www.tiendamonge.com/refrigeradora-side-by-side-samsung-27cp-rs27t5200s9-silver-165750"
URL_TRIMMER = "https://www.tiendamonge.com/trimmer-remington-ne3250"
SUBMAPA_URLS = "https://www.tiendamonge.com/media/sitemap_tienda_monge_cr-urls.xml"
SUBMAPA_IMAGENES = "https://www.tiendamonge.com/media/sitemap_tienda_monge_cr-images.xml"


class MongeListarUrlsTests(SimpleTestCase):
    def test_esta_registrada(self):
        self.assertIs(TIENDAS["monge"], monge)

    def test_lista_las_paginas_que_pueden_ser_de_producto(self):
        http = HttpFalso({monge.SITEMAP: muestra("monge_sitemap.xml"), SUBMAPA_URLS: muestra("monge_sitemap_urls.xml")})
        # Se quedan fuera /catalog/... (prohibido en robots.txt) y las categorías (/productos/...).
        self.assertEqual(monge.listar_urls(http), [URL_TRIMMER, URL_SAMSUNG, URL_IPHONE])
        self.assertNotIn(SUBMAPA_IMAGENES, http.pedidas)

    def test_es_url_de_producto(self):
        self.assertTrue(monge.es_url_de_producto(URL_IPHONE))
        self.assertFalse(monge.es_url_de_producto(URL_IPHONE + "?options=cart"))
        self.assertFalse(monge.es_url_de_producto("https://www.tiendamonge.com/"))
        self.assertFalse(monge.es_url_de_producto("https://www.verdugotienda.com/algo-123456"))


class MongeFichaTests(SimpleTestCase):
    def ficha(self, url, archivo):
        return monge.obtener_ficha(url, HttpFalso({url: muestra(archivo)}))

    def test_ficha_del_iphone(self):
        ficha = self.ficha(URL_IPHONE, "monge_iphone17_negro.html")
        self.assertEqual(ficha.nombre, "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB")
        # Sin códigos de barras: el "gtin" del ld+json de Monge es su código interno.
        self.assertEqual(ficha.oferta, Oferta(599900, 479900, True))
        self.assertEqual(ficha.oferta.descuento, Decimal("0.20"))
        self.assertEqual((ficha.sku, ficha.marca, ficha.modelo, ficha.color), ("199387", "Apple", "iPhone 17", "Negro"))
        self.assertEqual(ficha.categoria, "Celulares y Tablets > Celulares > Apple")
        self.assertTrue(ficha.imagen_url.startswith("https://www.tiendamonge.com/media/catalog/product/"))
        self.assertEqual(ficha.url, URL_IPHONE)

    def test_ficha_de_la_refrigeradora(self):
        ficha = self.ficha(URL_SAMSUNG, "monge_refrigeradora_samsung.html")
        self.assertEqual(ficha.oferta, Oferta(899900, 797900, True))  # ₡797.899,99 se redondea
        self.assertEqual((ficha.marca, ficha.modelo), ("Samsung", "RS27T5200S9/ED"))
        self.assertEqual(ficha.categoria, "Hogar y Línea Blanca > Refrigeradoras > Side by Side")

    def test_pagina_que_no_es_de_producto(self):
        html = '<script type="application/ld+json">{"@type": "WebPage", "name": "Plan A"}</script>'
        self.assertIsNone(monge.obtener_ficha(URL_TRIMMER, HttpFalso({URL_TRIMMER: html})))


class MongeActualizarPreciosTests(SimpleTestCase):
    def test_actualizar_precios_lee_el_precio_de_lista_y_el_de_oferta(self):
        self.assertIs(extractor_para(URL_IPHONE), ld_json.extraer)
        ofertas = ld_json.extraer(URL_IPHONE, HttpFalso({URL_IPHONE: muestra("monge_iphone17_negro.html")}))
        self.assertEqual(ofertas, [Oferta(599900, 479900, True)])

    def test_ruta_de_categorias_sin_migas(self):
        self.assertEqual(ld_json.ruta_de_categorias("<html></html>"), [])
