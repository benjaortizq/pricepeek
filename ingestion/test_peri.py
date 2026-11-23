"""Pruebas del lector del catálogo de Peri, con páginas reales recortadas en ingestion/muestras.

Las muestras salieron de páginas reales de peridomicilio.com: el árbol de categorías y los productos
son los de la tienda, solo que pocos (peri_inicio.html, peri_galletas.html y peri_panaderia.html).
"""

import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from .models import StoreProduct
from .scrapers import ErrorDescarga, Oferta, PrecioNoEncontrado, extractor_para, ld_json
from .test_productos_tienda import ProductosDeTiendaTestCase
from .test_scrapers import muestra, HttpFalso
from .tiendas import TIENDAS
from .tiendas.peri import (
    INICIO,
    arbol_de_categorias,
    ficha_del_producto,
    peri,
    productos_de_la_pagina,
    recorrer,
    ruta_de_la_categoria,
    url_de_la_categoria,
)

URL_PANADERIA = "https://www.peridomicilio.com/ca/panaderia/F2"
URL_GALLETAS = "https://www.peridomicilio.com/ca/panaderia/galletas/F2/C15"
URL_HARINAS = "https://www.peridomicilio.com/ca/panaderia/harinas-e-insumos/F2/C10"
URL_LACTEOS = "https://www.peridomicilio.com/ca/lacteos-y-huevos/F12"
URL_CONDENSADAS = "https://www.peridomicilio.com/ca/lacteos-y-huevos/condensadas-y-evaporadas/F12/C63"

URL_NABISCO = "https://www.peridomicilio.com/p/galleta-nabisco-mini-chips-anoy-50g-208689"
URL_RICHESTER = "https://www.peridomicilio.com/p/galleta-richester-animados-chocolate-140g-220377"
URL_TOSH = "https://www.peridomicilio.com/p/galleta-tosh-integral-miel-9uds-109882"
URL_MIMASA = "https://www.peridomicilio.com/p/harina-de-maiz-mimasa-750-gr-156520"

AVISO_GALLETAS = "panaderia/galletas: 3 productos nuevos (tiene 212; su página solo muestra 3)"


def pagina_de_next(texto):
    """Una página con estos datos de Next.js, para los casos que las muestras no tienen."""
    return f"<script>self.__next_f.push([1,{json.dumps(texto)}])</script>"


VACIA = pagina_de_next('1:["$","$Lcd",null,{"pagination":{"page":1,"pages":0,"total":{"value":0}}}]\n')


def paginas(cambios=None):
    """La tienda con las muestras: Panadería y Galletas con productos, las otras categorías vacías."""
    respuestas = {
        INICIO: muestra("peri_inicio.html"),
        URL_PANADERIA: muestra("peri_panaderia.html"),
        URL_GALLETAS: muestra("peri_galletas.html"),
        URL_HARINAS: VACIA,
        URL_LACTEOS: VACIA,
        URL_CONDENSADAS: VACIA,
    }
    return HttpFalso({**respuestas, **(cambios or {})})


class CategoriasDePeriTests(SimpleTestCase):
    def test_esta_registrada_y_se_lee_por_categorias(self):
        self.assertIs(TIENDAS["peri"], peri)
        self.assertEqual(peri.NOMBRE, "Peri")  # en la tabla stores está como "Peri\n"
        self.assertFalse(hasattr(peri, "listar_urls"))  # sin sitemap: obtener_productos la lee por categorías

    def test_el_arbol_viene_en_la_pagina_de_inicio(self):
        categorias = list(recorrer(arbol_de_categorias(muestra("peri_inicio.html"))))
        self.assertEqual(
            [ruta_de_la_categoria(categoria) for categoria in categorias],
            [
                "panaderia",
                "panaderia/galletas",
                "panaderia/harinas-e-insumos",
                "lacteos-y-huevos",
                "lacteos-y-huevos/condensadas-y-evaporadas",
            ],
        )
        self.assertEqual(url_de_la_categoria(categorias[1]), URL_GALLETAS)

    def test_inicio_sin_el_arbol(self):
        with self.assertRaises(PrecioNoEncontrado):
            arbol_de_categorias(pagina_de_next('1:{"categoryTree":"$8b"}\n'))  # solo la referencia


class ProductosDePeriTests(SimpleTestCase):
    def leer(self, categorias, http=None):
        avisos = []
        productos = peri.productos_de_categorias(http or paginas(), categorias, avisar=avisos.append)
        return productos, avisos

    def test_una_categoria_con_la_ruta_de_su_url(self):
        for pedida in ("panaderia/galletas", "Panadería/Galletas", "panaderia/galletas/F2/C15"):
            with self.subTest(pedida=pedida):
                productos, avisos = self.leer([pedida])
                self.assertEqual(list(productos), [URL_NABISCO, URL_RICHESTER, URL_TOSH])
                self.assertEqual(avisos[0], AVISO_GALLETAS)
                self.assertTrue(avisos[1].startswith("1 categoría(s) con más productos de los que muestra su página"))

    def test_una_categoria_trae_tambien_sus_subcategorias(self):
        http = paginas()
        productos, avisos = self.leer(["panaderia"], http)
        self.assertEqual(http.pedidas, [INICIO, URL_PANADERIA, URL_GALLETAS, URL_HARINAS])
        # La galleta Nabisco sale en Panadería y en Galletas: queda una sola vez.
        self.assertEqual(list(productos), [URL_MIMASA, URL_NABISCO, URL_RICHESTER, URL_TOSH])
        self.assertIn("panaderia/galletas: 2 productos nuevos (tiene 212; su página solo muestra 3)", avisos)
        self.assertIn("panaderia/harinas-e-insumos: 0 productos nuevos", avisos)

    def test_sin_categorias_lee_todas(self):
        http = paginas()
        productos, _ = self.leer([], http)
        self.assertEqual(http.pedidas, [INICIO, URL_PANADERIA, URL_GALLETAS, URL_HARINAS, URL_LACTEOS, URL_CONDENSADAS])
        self.assertEqual(len(productos), 4)

    def test_categoria_que_no_existe(self):
        productos, avisos = self.leer(["electronica"])
        self.assertEqual(productos, {})
        self.assertEqual(
            avisos, ["electronica: no existe en Peri. Es la ruta de su URL sin los códigos, por ejemplo panaderia/galletas"]
        )

    def test_una_categoria_que_falla_no_detiene_las_demas(self):
        http = paginas({URL_GALLETAS: ErrorDescarga("La tienda respondió con el código 500.", 500)})
        productos, avisos = self.leer(["panaderia"], http)
        self.assertIn("panaderia/galletas: no se pudo leer (La tienda respondió con el código 500.)", avisos)
        self.assertEqual(list(productos), [URL_MIMASA, URL_NABISCO])
        self.assertIn(URL_HARINAS, http.pedidas)

    def test_si_la_tienda_rechaza_las_peticiones_se_detiene(self):
        http = paginas({URL_GALLETAS: ErrorDescarga("La tienda respondió con el código 403.", 403)})
        with self.assertRaises(ErrorDescarga):
            self.leer(["panaderia"], http)
        self.assertNotIn(URL_HARINAS, http.pedidas)


class FichaDePeriTests(SimpleTestCase):
    def producto(self, url, archivo="peri_galletas.html"):
        productos, _ = productos_de_la_pagina(muestra(archivo))
        return next(producto for producto in productos if url.endswith(producto["slug"]))

    def ficha(self, url, archivo="peri_galletas.html", **cambios):
        return ficha_del_producto(url, {**self.producto(url, archivo), **cambios})

    def test_la_pagina_trae_sus_productos_y_cuantos_tiene_la_categoria(self):
        productos, total = productos_de_la_pagina(muestra("peri_galletas.html"))
        self.assertEqual([producto["sku"] for producto in productos], ["208689", "220377", "109882"])
        self.assertEqual(total, 212)

    def test_ficha(self):
        ficha = self.ficha(URL_NABISCO)
        self.assertEqual(ficha.url, URL_NABISCO)
        self.assertEqual(ficha.nombre, "Galleta Nabisco Mini Chips Anoy 50g")
        self.assertEqual(ficha.oferta, Oferta(410, 410, True, ("7750168000697",)))
        self.assertEqual((ficha.sku, ficha.marca, ficha.categoria), ("208689", "CHIPS", "Panadería > Galletas"))
        self.assertEqual(
            ficha.imagen_url, "https://res.cloudinary.com/carrito-lleno-gessa/image/upload/v1728593075/bar-code/7750168000697.jpg"
        )
        self.assertEqual(ficha.codigos_invalidos, ())

    def test_precio_especial_por_unidad(self):
        # Cuesta ₡450 y está a ₡340 c/u (máximo 3): se cobra ₡340, como dice la página del producto.
        self.assertEqual(self.ficha(URL_RICHESTER).oferta, Oferta(340, 340, True, ("7891152800937",)))

    def test_la_promocion_de_paquete_no_cambia_el_precio_de_una_unidad(self):
        # «2 por ₡1720»: una sola cuesta ₡1150, que es lo que publica su página.
        self.assertEqual(self.ficha(URL_MIMASA, "peri_panaderia.html").oferta, Oferta(1150, 1150, True, ("7441000713942",)))

    def test_promocion_que_ya_no_esta_activa(self):
        promociones = [{**promocion, "isActive": False} for promocion in self.producto(URL_RICHESTER)["promotions"]]
        self.assertEqual(self.ficha(URL_RICHESTER, promotions=promociones).oferta.precio_final, 450)

    def test_dos_codigos_en_el_mismo_ean(self):
        self.assertEqual(self.ficha(URL_TOSH).oferta.gtins, ("086581009403", "7441163406064"))

    def test_codigo_invalido_queda_como_incidencia(self):
        ficha = self.ficha(URL_NABISCO, ean=["7750168000698", "0"])  # dígito verificador malo; "0" es no tener código
        self.assertEqual(ficha.oferta.gtins, ())
        [(codigo, motivo)] = ficha.codigos_invalidos
        self.assertEqual(codigo, "7750168000698")
        self.assertTrue(motivo.startswith("El dígito verificador no coincide"))

    def test_sin_precio(self):
        with self.assertRaises(PrecioNoEncontrado):
            self.ficha(URL_NABISCO, price=None)
        agotado = self.ficha(URL_NABISCO, price=None, isAvailable=False)
        self.assertEqual(agotado.oferta, Oferta(None, None, False, ("7750168000697",)))

    def test_actualizar_precios_lee_la_pagina_del_producto(self):
        self.assertIs(extractor_para(URL_RICHESTER), ld_json.extraer)


class ObtenerProductosDePeriTests(ProductosDeTiendaTestCase):
    def test_lee_una_categoria_y_sugiere_por_el_codigo_de_barras(self):
        self.variante(self.producto("Galleta Chips Ahoy mini 50 g", self.dos_pinos, self.salsas), "7750168000697")
        salida = StringIO()
        with mock.patch("ingestion.management.commands.obtener_productos.ClienteHttp", return_value=paginas()):
            call_command("obtener_productos", "--tienda", "peri", "--categoria", "panaderia/galletas", stdout=salida)

        texto = salida.getvalue()
        self.assertIn("Buscando los productos de Peri en: panaderia/galletas...", texto)
        self.assertIn(AVISO_GALLETAS, texto)
        self.assertIn("Peri: 3 productos en esas categorías; se van a revisar 3.", texto)
        nabisco = StoreProduct.objects.get(url=URL_NABISCO)
        self.assertEqual((nabisco.store_name, nabisco.barcodes, nabisco.final_price), ("Peri", ["7750168000697"], 410))
        self.assertEqual((nabisco.status, nabisco.suggested_gtin), (StoreProduct.Status.SUGGESTED, "7750168000697"))
        self.assertEqual(StoreProduct.objects.get(url=URL_TOSH).barcodes, ["086581009403", "7441163406064"])
