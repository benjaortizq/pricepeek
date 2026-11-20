"""Pruebas de Gollo: lector del catálogo, precios y coincidencia por código de barras (páginas reales en ingestion/muestras)."""

from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from products.models import Prices, Stores
from products.tests import fechas

from .actualizacion import FALLO, SIN_CAMBIOS, revisar
from .emparejamiento import rasgos
from .models import Incident, StoreProduct
from .productos_tienda import candidatas_del_catalogo, confirmar, guardar_ficha
from .scrapers import ErrorDescarga, Oferta, PrecioNoEncontrado, extractor_para
from .scrapers import gollo as paginas
from .test_productos_tienda import GTIN_IPHONE, ProductosDeTiendaTestCase
from .test_scrapers import HttpFalso, muestra
from .tiendas import TIENDAS, gollo

URL_IPHONE = "https://www.gollo.com/iphone-17-apple-256-gb-ram-8gb-6-3-48mp-48mp-negro-esim-5003050226/p"
URL_LLANTA = "https://www.gollo.com/llanta-goodride-rp28-175-70-0501040140/p"
URL_CAFETERA = "https://www.gollo.com/cafetera-black-decker-12-tazas-digital-cm2046s-2010010093/p"
GTIN_GOLLO = "195950643480"  # el iPhone 17 negro de Gollo (MG6J4BE/A); el del catálogo es otro modelo regional
Status = StoreProduct.Status


def ficha(url, archivo, html=None):
    return gollo.obtener_ficha(url, HttpFalso({url: html if html is not None else muestra(archivo)}))


class GolloListarUrlsTests(SimpleTestCase):
    def test_esta_registrada(self):
        self.assertIs(TIENDAS["gollo"], gollo)
        self.assertIs(extractor_para(URL_IPHONE), paginas.extraer)

    def test_lista_las_paginas_de_producto_del_sitemap(self):
        http = HttpFalso({gollo.SITEMAP: muestra("gollo_sitemap_productos.xml")})
        # /catalog/product/view/... queda fuera (robots.txt) y las <image:loc> no se cuentan.
        self.assertEqual(gollo.listar_urls(http), [URL_LLANTA, URL_IPHONE])

    def test_es_url_de_producto(self):
        self.assertTrue(gollo.es_url_de_producto(URL_IPHONE))
        self.assertFalse(gollo.es_url_de_producto("https://www.gollo.com/catalog/product/view/id/25318/"))
        self.assertFalse(gollo.es_url_de_producto(URL_IPHONE + "?color=negro"))
        self.assertFalse(gollo.es_url_de_producto("https://www.tiendamonge.com/algo/p"))


class GolloFichaTests(SimpleTestCase):
    def test_ficha_del_iphone(self):
        f = ficha(URL_IPHONE, "gollo_iphone17_negro.html")
        self.assertEqual(f.nombre, "iPhone 17 8GB + 256GB Negro")
        self.assertEqual(f.oferta, Oferta(599900, 499895, True, (GTIN_GOLLO,)))
        self.assertEqual(f.oferta.descuento, Decimal("0.17"))
        self.assertEqual((f.marca, f.modelo, f.color, f.categoria, f.sku), ("Apple", "iPhone 17 MG6J4BE/A", "Negro", "Celular", "5003050226"))
        self.assertTrue(f.imagen_url.startswith("https://www.gollo.com/media/catalog/product/5/0/5003050226_1.jpg"))
        self.assertEqual(f.codigos_invalidos, ())

    def test_upc_sin_el_cero_inicial(self):
        f = ficha(URL_CAFETERA, "gollo_cafetera_black_decker.html")
        self.assertEqual(f.oferta.gtins, ("050875828247",))  # Gollo publica 50875828247 (11 dígitos)
        self.assertEqual((f.marca, f.oferta.precio_lista, f.oferta.precio_final), ("Black + Decker", 59900, 44900))

    def test_gtin_cero_es_que_no_tiene_codigo(self):
        f = ficha(URL_LLANTA, "gollo_llanta_sin_gtin.html")
        self.assertEqual((f.oferta.gtins, f.codigos_invalidos), ((), ()))
        self.assertEqual(f.oferta, Oferta(79000, 79000, True))

    def test_gtin_invalido_queda_anotado(self):
        html = muestra("gollo_iphone17_negro.html").replace(f">{GTIN_GOLLO}<", ">195950643481<")
        f = ficha(URL_IPHONE, None, html)
        self.assertEqual(f.oferta.gtins, ())
        [(codigo, motivo)] = f.codigos_invalidos
        self.assertEqual(codigo, "195950643481")
        self.assertIn("dígito verificador", motivo)

    def test_pagina_que_no_es_de_producto(self):
        self.assertIsNone(ficha(URL_IPHONE, None, "<html><body>Categoría</body></html>"))
        with self.assertRaises(PrecioNoEncontrado):
            paginas.extraer(URL_IPHONE, HttpFalso({URL_IPHONE: "<html></html>"}))

    def test_actualizar_precios_lee_la_misma_oferta(self):
        ofertas = paginas.extraer(URL_IPHONE, HttpFalso({URL_IPHONE: muestra("gollo_iphone17_negro.html")}))
        self.assertEqual(ofertas, [Oferta(599900, 499895, True, (GTIN_GOLLO,))])


class GolloPiezasTests(SimpleTestCase):
    def test_especificaciones(self):
        specs = paginas.especificaciones(muestra("gollo_iphone17_negro.html"))
        self.assertEqual((specs["GTIN"], specs["MPN"], specs["Memoria Interna"]), (GTIN_GOLLO, "MG6J4BE/A", "256 GB"))

    def test_codigo_de_barras(self):
        self.assertEqual(paginas.codigo_de_barras(" 195950643480 "), (GTIN_GOLLO, ""))
        self.assertEqual(paginas.codigo_de_barras("0"), ("", ""))
        self.assertEqual(paginas.codigo_de_barras(""), ("", ""))
        self.assertEqual(paginas.codigo_de_barras(None), ("", ""))
        codigo, motivo = paginas.codigo_de_barras("ABC123")
        self.assertEqual(codigo, "")
        self.assertIn("solo puede tener dígitos", motivo)

    def test_el_mas_que_separa_no_es_plus(self):
        self.assertEqual(rasgos("iPhone 17 8GB + 256GB Negro").modificadores, set())
        self.assertEqual(rasgos("Cafetera Black + Decker").modificadores, set())
        self.assertEqual(rasgos("Redmi Note 15 Pro+").modificadores, {"pro", "plus"})


class GolloCatalogoTests(ProductosDeTiendaTestCase):
    def guardar_gollo(self, html=None):
        f = ficha(URL_IPHONE, "gollo_iphone17_negro.html", html)
        return guardar_ficha(f, "Gollo", candidatas_del_catalogo())

    def test_el_nombre_coincide_pero_el_codigo_no(self):
        producto = self.guardar_gollo()
        self.assertEqual((producto.status, producto.suggested_gtin, producto.score), (Status.SUGGESTED, GTIN_IPHONE, 80))
        self.assertTrue(
            producto.match_reason.startswith(f"código distinto: la tienda dice {GTIN_GOLLO} y el catálogo {GTIN_IPHONE}")
        )

    def test_mismo_codigo_de_barras(self):
        html = muestra("gollo_iphone17_negro.html").replace(f">{GTIN_GOLLO}<", ">195950643411<")
        producto = self.guardar_gollo(html)
        self.assertEqual((producto.suggested_gtin, producto.score, producto.match_reason), (GTIN_IPHONE, 100, "mismo código de barras"))

    def test_confirmado_actualizar_precios_acepta_el_codigo_de_la_tienda(self):
        precio = confirmar(self.guardar_gollo())
        precio = Prices.objects.select_related("id_store", "gtin").get(pk=precio.pk)
        self.assertEqual((precio.id_store.name, precio.price, precio.discount), ("Gollo", 599900, Decimal("0.17")))
        revision = revisar(precio, HttpFalso({URL_IPHONE: muestra("gollo_iphone17_negro.html")}))
        self.assertEqual((revision.resultado, revision.incidencia), (SIN_CAMBIOS, None))

    def test_sin_confirmar_el_codigo_distinto_es_incidencia(self):
        gollo_tienda = Stores.objects.create(name="Gollo", **fechas())
        fila = self.precio(self.variante_iphone, gollo_tienda, 599900, "0.17")
        Prices.objects.filter(pk=fila.pk).update(product_web_url=URL_IPHONE)
        fila = Prices.objects.select_related("id_store", "gtin").get(pk=fila.pk)
        revision = revisar(fila, HttpFalso({URL_IPHONE: muestra("gollo_iphone17_negro.html")}))
        self.assertEqual((revision.resultado, revision.incidencia.kind), (FALLO, Incident.Kind.BARCODE_MISMATCH))


class GolloComandoTests(ProductosDeTiendaTestCase):
    def correr(self, respuestas, *argumentos):
        salida = StringIO()
        comando = "ingestion.management.commands.obtener_productos"
        with (
            mock.patch(f"{comando}.ClienteHttp", return_value=HttpFalso(respuestas)) as cliente,
            mock.patch(f"{comando}.esperar") as esperar,
        ):
            call_command("obtener_productos", "--tienda", "gollo", *argumentos, stdout=salida)
        self.pausa = cliente.call_args.kwargs["pausa"]
        self.esperas = [llamada.args[0] for llamada in esperar.call_args_list]
        return salida.getvalue()

    def test_usa_la_pausa_recomendada_para_gollo(self):
        self.correr(self.respuestas())
        self.assertEqual(self.pausa, gollo.PAUSA)
        self.correr(self.respuestas(), "--pausa", "10", "--todos")
        self.assertEqual(self.pausa, 10)

    def respuestas(self, iphone=None):
        return {
            gollo.SITEMAP: muestra("gollo_sitemap_productos.xml"),
            URL_LLANTA: muestra("gollo_llanta_sin_gtin.html"),
            URL_IPHONE: iphone or muestra("gollo_iphone17_negro.html"),
        }

    def test_obtiene_los_productos_y_sugiere(self):
        salida = self.correr(self.respuestas())
        self.assertIn("Gollo: 2 páginas en su lista; se van a revisar 2.", salida)
        self.assertIn("iPhone 17 8GB + 256GB Negro · ₡499.895 → iPhone 17- 256GB Negro (puntaje 80: código distinto", salida)
        self.assertIn("2 páginas · 2 productos · 1 con coincidencia sugerida · 0 no eran productos · 0 fallos", salida)

    def test_codigo_invalido_queda_como_incidencia(self):
        iphone = muestra("gollo_iphone17_negro.html").replace(f">{GTIN_GOLLO}<", ">195950643481<")
        salida = self.correr(self.respuestas(iphone))
        self.assertIn("código de barras inválido (195950643481)", salida)
        self.assertIn("1 códigos de barras inválidos (quedan como incidencia)", salida)
        incidencia = Incident.objects.get()
        self.assertEqual((incidencia.kind, incidencia.store_name, incidencia.gtin), (Incident.Kind.INVALID_BARCODE, "Gollo", "195950643481"))

    def test_si_la_tienda_nos_bloquea_se_detiene(self):
        respuestas = {gollo.SITEMAP: "".join(f"<url><loc>https://www.gollo.com/producto-{i}/p</loc></url>" for i in range(20))}
        respuestas.update({f"https://www.gollo.com/producto-{i}/p": ErrorDescarga("La tienda respondió con el código 403.", 403) for i in range(20)})
        salida = self.correr(respuestas)
        self.assertIn("Gollo está rechazando peticiones: se esperan 30 s antes de seguir.", salida)
        self.assertEqual(self.esperas, [30, 60, 90, 120])
        self.assertIn("Gollo rechazó 5 peticiones seguidas: se detiene para no insistir.", salida)
        self.assertIn("5 páginas · 0 productos", salida)

    def test_despues_de_un_rechazo_sigue_normal(self):
        respuestas = self.respuestas()
        respuestas[URL_LLANTA] = ErrorDescarga("La tienda respondió con el código 429.", 429)
        salida = self.correr(respuestas)
        self.assertEqual(self.esperas, [30])
        self.assertIn("2 páginas · 1 productos · 1 con coincidencia sugerida · 0 no eran productos · 1 fallos", salida)

    def test_otros_fallos_no_lo_detienen(self):
        respuestas = {gollo.SITEMAP: "".join(f"<url><loc>https://www.gollo.com/producto-{i}/p</loc></url>" for i in range(8))}
        respuestas.update({f"https://www.gollo.com/producto-{i}/p": ErrorDescarga("La tienda respondió con el código 503.", 503) for i in range(8)})
        self.assertIn("8 páginas · 0 productos · 0 con coincidencia sugerida · 0 no eran productos · 8 fallos", self.correr(respuestas))

    def test_dry_run_no_registra_incidencias(self):
        iphone = muestra("gollo_iphone17_negro.html").replace(f">{GTIN_GOLLO}<", ">195950643481<")
        self.correr(self.respuestas(iphone), "--dry-run")
        self.assertFalse(Incident.objects.exists())
        self.assertFalse(StoreProduct.objects.exists())
