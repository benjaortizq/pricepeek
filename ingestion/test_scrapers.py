"""Pruebas de los extractores con páginas reales guardadas en ingestion/muestras (sin internet)."""

import copy
import json
from decimal import Decimal
from pathlib import Path
from unittest import mock

import requests
from curl_cffi.requests.exceptions import Timeout as CurlTimeout
from django.test import SimpleTestCase

from .scrapers import (
    ClienteHttp,
    ErrorDescarga,
    Oferta,
    PrecioNoEncontrado,
    ProductoNoEncontrado,
    automercado,
    extractor_para,
    ld_json,
    vtex,
)

MUESTRAS = Path(__file__).parent / "muestras"


def muestra(nombre):
    return (MUESTRAS / nombre).read_text(encoding="utf-8")


class HttpFalso:
    """Reemplaza a ClienteHttp: responde con lo que se le da por URL (o lanza la excepción dada)."""

    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.pedidas = []

    def _responder(self, url):
        self.pedidas.append(url)
        respuesta = self.respuestas[url]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    texto = json = _responder


URL_WALMART = (
    "https://www.walmart.co.cr/apple-iphone-17-8gb-256g-neg-768-6-8/p"
)
API_WALMART = "https://www.walmart.co.cr/api/catalog_system/pub/products/search/apple-iphone-17-8gb-256g-neg-768-6-8/p"
URL_PERI = "https://www.peridomicilio.com/p/nescafe-clasico-nestle120g-38962"
URL_MEGASUPER = "https://www.megasuper.com/p/refresco-gaseoso-envase-desechable-coca-cola-25ml-7401006400901"
URL_AUTOMERCADO = "https://automercado.cr/p/cereal-endulzado-zucaritas-kelloggs-caja-490-g/id/a4a118ed-f90a-4468-8929-9a3425246bc3"


class OfertaTests(SimpleTestCase):
    def test_descuento_con_dos_decimales(self):
        self.assertEqual(
            Oferta(619900, 472131, True).descuento, Decimal("0.24")
        )
        self.assertEqual(Oferta(3230, 2745, True).descuento, Decimal("0.15"))

    def test_sin_descuento(self):
        self.assertEqual(Oferta(6350, 6350, True).descuento, Decimal("0.00"))
        self.assertEqual(Oferta(None, None, False).descuento, Decimal("0.00"))
        self.assertEqual(
            Oferta(1000, 1200, True).descuento, Decimal("0.00")
        )  # precio final mayor: no es descuento


class ExtractorParaTests(SimpleTestCase):
    def test_elige_el_extractor_por_dominio(self):
        self.assertIs(extractor_para(URL_WALMART), vtex.extraer)
        self.assertIs(
            extractor_para("https://maxipali.co.cr/algo/p"), vtex.extraer
        )
        self.assertIs(extractor_para(URL_AUTOMERCADO), automercado.extraer)
        self.assertIs(extractor_para(URL_PERI), ld_json.extraer)
        self.assertIs(extractor_para(URL_MEGASUPER), ld_json.extraer)

    def test_tienda_no_soportada(self):
        self.assertIsNone(
            extractor_para("https://www.pequeno-mundo.com/producto/1")
        )
        self.assertIsNone(extractor_para(""))
        self.assertIsNone(extractor_para(None))


class VtexTests(SimpleTestCase):
    def setUp(self):
        self.api = json.loads(muestra("vtex_walmart_iphone17.json"))

    def extraer(self, respuesta):
        return vtex.extraer(URL_WALMART, HttpFalso({API_WALMART: respuesta}))

    def test_convierte_la_url_del_producto_en_la_de_la_api(self):
        self.assertEqual(vtex.url_api(URL_WALMART), API_WALMART)

    def test_una_url_que_no_es_de_vtex_no_se_puede_consultar(self):
        with self.assertRaises(PrecioNoEncontrado):
            vtex.url_api("https://www.walmart.co.cr/busca?q=leche")

    def test_extrae_precio_de_lista_precio_final_y_codigo(self):
        self.assertEqual(
            self.extraer(self.api),
            [Oferta(619900, 472131, True, ("0195950643411",))],
        )

    def test_producto_agotado_queda_sin_precio(self):
        agotado = copy.deepcopy(self.api)
        detalle = agotado[0]["items"][0]["sellers"][0]["commertialOffer"]
        detalle.update(
            Price=0, ListPrice=0, IsAvailable=False, AvailableQuantity=0
        )
        self.assertEqual(
            self.extraer(agotado),
            [Oferta(None, None, False, ("0195950643411",))],
        )

    def test_busqueda_vacia_es_producto_no_encontrado(self):
        with self.assertRaises(ProductoNoEncontrado):
            self.extraer([])

    def test_respuesta_sin_precios_es_precio_no_encontrado(self):
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer([{"productName": "Sin items", "items": []}])
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer({"error": "otra cosa"})


class LdJsonTests(SimpleTestCase):
    def extraer(self, url, html):
        return ld_json.extraer(url, HttpFalso({url: html}))

    def test_peri_precio_y_todos_sus_codigos_de_barras(self):
        self.assertEqual(
            self.extraer(URL_PERI, muestra("peri_nescafe.html")),
            [
                Oferta(
                    6350,
                    6350,
                    True,
                    (
                        "088169002950",
                        "7501058631442",
                        "7501059283282",
                        "7891000057667",
                    ),
                )
            ],
        )

    def test_megasuper(self):
        self.assertEqual(
            self.extraer(URL_MEGASUPER, muestra("megasuper_coca_cola.html")),
            [Oferta(2042, 2042, True, ("7401006400901",))],
        )

    def test_producto_agotado(self):
        html = muestra("peri_nescafe.html").replace(
            "schema.org/InStock", "schema.org/OutOfStock"
        )
        [oferta] = self.extraer(URL_PERI, html)
        self.assertFalse(oferta.disponible)

    def test_precio_directo_en_la_oferta_y_aggregate_offer(self):
        html = (
            '<script type="application/ld+json">{"@graph": [{"@type": "WebSite"}, {"@type": "Product", '
            '"offers": {"@type": "AggregateOffer", "offers": [{"price": "1500.00", "priceCurrency": "CRC"}]}}]}'
            "</script>"
        )
        self.assertEqual(
            self.extraer(URL_PERI, html), [Oferta(1500, 1500, True)]
        )

    def test_pagina_sin_datos_de_producto(self):
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer(
                URL_PERI, "<html><body>Página en mantenimiento</body></html>"
            )

    def test_pagina_de_no_encontrado_con_codigo_200(self):
        # Así responde Peri (Next.js) cuando el producto ya no existe.
        chunks = "/_next/static/chunks/app/(shop)/(ecommerce)/p/%5Bslug%5D"
        no_existe = f'<html><head><script src="{chunks}/not-found-27a1bef62e931292.js" async></script></head></html>'
        with self.assertRaises(ProductoNoEncontrado):
            self.extraer(URL_PERI, no_existe)
        # Una página de producto también carga ese componente, pero junto con el de la página.
        cambio_de_formato = no_existe.replace(
            "</head>",
            f'<script src="{chunks}/page-4c187fc354556241.js"></script></head>',
        )
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer(URL_PERI, cambio_de_formato)

    def test_disponible_pero_sin_precio(self):
        html = muestra("peri_nescafe.html").replace(
            '"price": 6350', '"price": null'
        )
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer(URL_PERI, html)

    def test_precio_en_otra_moneda(self):
        html = muestra("peri_nescafe.html").replace(
            '"priceCurrency": "CRC"', '"priceCurrency": "USD"'
        )
        with self.assertRaisesMessage(PrecioNoEncontrado, "USD"):
            self.extraer(URL_PERI, html)


class AutomercadoTests(SimpleTestCase):
    def extraer(self, html):
        return automercado.extraer(
            URL_AUTOMERCADO, HttpFalso({URL_AUTOMERCADO: html})
        )

    def estado(self):
        html = muestra("automercado_zucaritas.html")
        return automercado.estado_de_la_pagina(html)

    def con_estado(self, estado):
        return f'<script id="automercado-state" type="application/json">{json.dumps(estado)}</script>'

    def test_toma_el_precio_de_la_mayoria_de_sucursales(self):
        # 21 sucursales: ₡3.230 con descuento a ₡2.745; 3 sucursales: ₡3.310 con descuento a ₡2.810.
        [oferta] = self.extraer(muestra("automercado_zucaritas.html"))
        self.assertEqual(oferta, Oferta(3230, 2745, True))
        self.assertEqual(oferta.descuento, Decimal("0.15"))

    def test_ignora_las_sucursales_donde_no_esta_disponible(self):
        estado = self.estado()
        for sucursal in estado["product-detail.ssr-algolia"]["products"][0][
            "hits"
        ][0]["storeDetail"].values():
            if sucursal["amount"] == 2745:
                sucursal["productAvailable"] = False
        self.assertEqual(
            self.extraer(self.con_estado(estado)), [Oferta(3310, 2810, True)]
        )

    def test_agotado_en_todas_las_sucursales(self):
        estado = self.estado()
        for sucursal in estado["product-detail.ssr-algolia"]["products"][0][
            "hits"
        ][0]["storeDetail"].values():
            sucursal["productAvailable"] = False
        self.assertEqual(
            self.extraer(self.con_estado(estado)), [Oferta(None, None, False)]
        )

    def test_producto_que_ya_no_existe(self):
        estado = {"product-detail.ssr-algolia": {"products": [{"hits": []}]}}
        with self.assertRaises(ProductoNoEncontrado):
            self.extraer(self.con_estado(estado))

    def test_pagina_sin_el_estado(self):
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer("<html><body>Nueva versión del sitio</body></html>")
        with self.assertRaises(PrecioNoEncontrado):
            self.extraer(self.con_estado({"otra-cosa": {}}))


def respuesta_http(codigo, texto=""):
    respuesta = requests.Response()
    respuesta.status_code = codigo
    respuesta._content = texto.encode()
    return respuesta


class ClienteHttpTests(SimpleTestCase):
    def setUp(self):
        self.http = ClienteHttp(pausa=0, reintentos=2, espera_reintento=0)
        parche = mock.patch.object(self.http.sesion, "get")
        self.get = parche.start()
        self.addCleanup(parche.stop)

    def test_devuelve_el_texto(self):
        self.get.return_value = respuesta_http(200, "<html>ok</html>")
        self.assertEqual(
            self.http.texto("https://tienda.test/p"), "<html>ok</html>"
        )

    def test_404_es_producto_no_encontrado_y_no_se_reintenta(self):
        self.get.return_value = respuesta_http(404)
        with self.assertRaises(ProductoNoEncontrado):
            self.http.texto("https://tienda.test/p")
        self.assertEqual(self.get.call_count, 1)

    def test_reintenta_los_errores_del_servidor(self):
        self.get.side_effect = [respuesta_http(503), respuesta_http(200, "ok")]
        self.assertEqual(self.http.texto("https://tienda.test/p"), "ok")
        self.assertEqual(self.get.call_count, 2)

    def test_se_rinde_despues_de_los_reintentos(self):
        self.get.side_effect = CurlTimeout("timeout")
        with self.assertRaisesMessage(ErrorDescarga, "Timeout"):
            self.http.texto("https://tienda.test/p")
        self.assertEqual(self.get.call_count, 3)

    def test_403_no_se_reintenta(self):
        self.get.return_value = respuesta_http(403)
        with self.assertRaisesMessage(ErrorDescarga, "403"):
            self.http.texto("https://tienda.test/p")
        self.assertEqual(self.get.call_count, 1)

    def test_json_invalido(self):
        self.get.return_value = respuesta_http(200, "<html>no es json</html>")
        with self.assertRaises(PrecioNoEncontrado):
            self.http.json("https://tienda.test/api")
