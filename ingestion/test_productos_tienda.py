"""Pruebas de los productos de tiendas: guardarlos, sugerir su variante y vincularlos (con el comando y el admin)."""

from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.urls import reverse

from accounts.models import User
from products.models import Brands, Categories, Prices, Stores
from products.tests import CatalogoTestCase, fechas

from .actualizacion import SIN_CAMBIOS, revisar
from .models import StoreProduct
from .productos_tienda import (
    NoSePuedeVincular,
    candidatas_del_catalogo,
    confirmar,
    guardar_ficha,
    tienda_del_catalogo,
)
from .scrapers import ErrorDescarga, Oferta
from .test_scrapers import HttpFalso, muestra
from .test_tiendas import SUBMAPA_URLS, URL_IPHONE, URL_SAMSUNG, URL_TRIMMER
from .tiendas import Ficha, monge

Status = StoreProduct.Status
GTIN_IPHONE = "0195950643411"
NO_ES_PRODUCTO = (
    '<script type="application/ld+json">{"@type": "WebPage"}</script>'
)


class ProductosDeTiendaTestCase(CatalogoTestCase):
    """El catálogo de CatalogoTestCase más un iPhone 17 negro y un iPhone 17 Pro azul."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        apple = Brands.objects.create(name="Apple", slug="apple", **fechas())
        celulares = Categories.objects.create(
            name="Electrodomésticos", **fechas()
        )
        cls.iphone = cls.producto("iPhone 17", apple, celulares)
        cls.variante_iphone = cls.variante(cls.iphone, GTIN_IPHONE)
        cls.variante_iphone.name = "iPhone 17- 256GB Negro"
        cls.variante_iphone.save()
        cls.variante_pro = cls.variante(cls.iphone, "0195950643428")
        cls.variante_pro.name = "iPhone 17 Pro - 256GB Azul"
        cls.variante_pro.save()
        cls.precio(
            cls.variante_leche,
            Stores.objects.create(name="Walmart\n", **fechas()),
            1760,
        )  # crea los colones

    def ficha_iphone(self, **cambios):
        datos = {
            "url": URL_IPHONE,
            "nombre": "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB",
            "oferta": Oferta(599900, 479900, True),
            "sku": "199387",
            "marca": "Apple",
            "modelo": "iPhone 17",
            "color": "Negro",
            "categoria": "Celulares y Tablets > Celulares > Apple",
            "imagen_url": "https://www.tiendamonge.com/media/catalog/product/iphone.png",
        }
        return Ficha(**{**datos, **cambios})

    def guardar(self, ficha=None, guardar=True):
        return guardar_ficha(
            ficha or self.ficha_iphone(),
            "Monge",
            candidatas_del_catalogo(),
            guardar=guardar,
        )


class GuardarFichaTests(ProductosDeTiendaTestCase):
    def test_guarda_el_producto_y_sugiere_su_variante(self):
        producto = self.guardar()
        producto.refresh_from_db()
        self.assertEqual(
            (
                producto.store_name,
                producto.sku,
                producto.final_price,
                producto.list_price,
            ),
            ("Monge", "199387", 479900, 599900),
        )
        self.assertEqual(
            (producto.status, producto.suggested_gtin, producto.score),
            (Status.SUGGESTED, GTIN_IPHONE, 100),
        )
        self.assertEqual(
            producto.suggested_variant.name, "iPhone 17- 256GB Negro"
        )

    def test_sin_coincidencia(self):
        producto = self.guardar(
            self.ficha_iphone(
                nombre="Celular 5G Apple iPhone 17 Blanco 8GB RAM 256GB",
                color="Blanco",
            )
        )
        self.assertEqual(
            (producto.status, producto.suggested_gtin), (Status.NO_MATCH, "")
        )

    def test_dry_run_no_guarda(self):
        producto = self.guardar(guardar=False)
        self.assertEqual(producto.status, Status.SUGGESTED)
        self.assertFalse(StoreProduct.objects.exists())

    def test_volver_a_obtenerlo_actualiza_sus_datos_sin_tocar_lo_revisado(
        self,
    ):
        producto = self.guardar()
        producto.status = Status.REJECTED
        producto.save()
        self.guardar(self.ficha_iphone(oferta=Oferta(599900, 450000, True)))
        producto.refresh_from_db()
        self.assertEqual(
            (producto.final_price, producto.status), (450000, Status.REJECTED)
        )
        self.assertEqual(StoreProduct.objects.count(), 1)

    def test_si_la_tienda_trae_codigo_de_barras_se_usa_ese(self):
        ficha = self.ficha_iphone(
            nombre="Teléfono negro",
            modelo="",
            color="",
            oferta=Oferta(1, 1, True, ("195950643411",)),
        )
        producto = self.guardar(ficha)
        self.assertEqual(
            (producto.suggested_gtin, producto.score, producto.match_reason),
            (GTIN_IPHONE, 100, "mismo código de barras"),
        )


class ConfirmarTests(ProductosDeTiendaTestCase):
    def test_crea_la_tienda_y_el_precio(self):
        producto = self.guardar()
        precio = confirmar(producto)
        precio = Prices.objects.select_related("id_store", "currency").get(
            pk=precio.pk
        )
        self.assertEqual(precio.id_store.name, "Monge")
        self.assertEqual(
            (precio.gtin_id, precio.price, precio.discount),
            (GTIN_IPHONE, 599900, Decimal("0.20")),
        )
        self.assertEqual(
            (
                precio.is_available,
                precio.product_web_url,
                precio.currency.name,
            ),
            (True, URL_IPHONE, "colones"),
        )
        producto.refresh_from_db()
        self.assertEqual(producto.status, Status.CONFIRMED)

    def test_confirmar_otra_vez_actualiza_el_mismo_precio(self):
        producto = self.guardar()
        confirmar(producto)
        producto.final_price = 450000
        confirmar(producto)
        self.assertEqual(Prices.objects.filter(gtin_id=GTIN_IPHONE).count(), 1)
        self.assertEqual(
            Prices.objects.get(gtin_id=GTIN_IPHONE).discount, Decimal("0.25")
        )

    def test_la_variante_ya_tiene_precio_en_esa_tienda_con_otro_enlace(self):
        confirmar(self.guardar())
        otro = self.guardar(self.ficha_iphone(url=URL_IPHONE + "-2"))
        with self.assertRaisesMessage(
            NoSePuedeVincular, "ya tiene precio en Monge"
        ):
            confirmar(otro)

    def test_sin_variante_elegida(self):
        producto = self.guardar(
            self.ficha_iphone(color="Blanco", nombre="iPhone 17 Blanco")
        )
        with self.assertRaisesMessage(NoSePuedeVincular, "Elija primero"):
            confirmar(producto)

    def test_usa_la_tienda_que_ya_existe_aunque_su_nombre_traiga_salto_de_linea(
        self,
    ):
        self.assertEqual(tienda_del_catalogo("walmart").name, "Walmart\n")
        self.assertEqual(Stores.objects.count(), 1)

    def test_despues_actualizar_precios_lo_mantiene(self):
        precio = confirmar(self.guardar())
        precio = Prices.objects.select_related("id_store", "gtin").get(
            pk=precio.pk
        )
        revision = revisar(
            precio,
            HttpFalso({URL_IPHONE: muestra("monge_iphone17_negro.html")}),
        )
        self.assertEqual(revision.resultado, SIN_CAMBIOS)


class ComandoObtenerProductosTests(ProductosDeTiendaTestCase):
    def respuestas(self, **cambios):
        respuestas = {
            monge.SITEMAP: muestra("monge_sitemap.xml"),
            SUBMAPA_URLS: muestra("monge_sitemap_urls.xml"),
            URL_TRIMMER: NO_ES_PRODUCTO,
            URL_SAMSUNG: muestra("monge_refrigeradora_samsung.html"),
            URL_IPHONE: muestra("monge_iphone17_negro.html"),
        }
        return {**respuestas, **cambios}

    def correr(self, respuestas, *argumentos):
        salida = StringIO()
        with mock.patch(
            "ingestion.management.commands.obtener_productos.ClienteHttp",
            return_value=HttpFalso(respuestas),
        ):
            call_command(
                "obtener_productos",
                "--tienda",
                "monge",
                *argumentos,
                stdout=salida,
            )
        return salida.getvalue()

    def test_obtiene_los_productos_y_sugiere_coincidencias(self):
        salida = self.correr(self.respuestas())
        self.assertIn(
            "Monge: 3 páginas en su lista; se van a revisar 3.", salida
        )
        self.assertIn(
            "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB · ₡479.900 → iPhone 17- 256GB Negro (puntaje 100",
            salida,
        )
        self.assertIn(
            "3 páginas · 2 productos · 1 con coincidencia sugerida · 1 no eran productos · 0 fallos",
            salida,
        )
        self.assertEqual(
            StoreProduct.objects.get(url=URL_SAMSUNG).status, Status.NO_MATCH
        )
        self.assertEqual(
            StoreProduct.objects.get(url=URL_IPHONE).suggested_gtin,
            GTIN_IPHONE,
        )

    def test_la_segunda_vez_solo_revisa_lo_nuevo(self):
        self.correr(self.respuestas())
        salida = self.correr(self.respuestas())
        self.assertIn(
            "se van a revisar 1.", salida
        )  # la que no es de producto no se guarda
        self.assertIn(
            "se van a revisar 3.", self.correr(self.respuestas(), "--todos")
        )

    def test_filtro_limite_y_dry_run(self):
        salida = self.correr(
            self.respuestas(), "--filtro", "IPHONE", "--dry-run"
        )
        self.assertIn("se van a revisar 1.", salida)
        self.assertIn("no se guardará nada", salida)
        self.assertFalse(StoreProduct.objects.exists())
        self.assertIn(
            "se van a revisar 2.",
            self.correr(self.respuestas(), "--limite", "2"),
        )

    def test_una_pagina_que_falla_no_detiene_las_demas(self):
        salida = self.correr(
            self.respuestas(
                **{
                    URL_SAMSUNG: ErrorDescarga(
                        "La tienda respondió con el código 503."
                    )
                }
            )
        )
        self.assertIn(
            f"{URL_SAMSUNG}: La tienda respondió con el código 503.", salida
        )
        self.assertIn(
            "1 productos · 1 con coincidencia sugerida · 1 no eran productos · 1 fallos",
            salida,
        )


class AdminProductosDeTiendaTests(ProductosDeTiendaTestCase):
    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser(
                email="admin@pricepeek.test", password="Clave2026segura"
            )
        )
        self.producto = self.guardar()
        self.lista = reverse("admin:ingestion_storeproduct_changelist")

    def test_la_lista_muestra_la_sugerencia(self):
        respuesta = self.client.get(self.lista)
        self.assertContains(
            respuesta, "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB"
        )
        self.assertContains(respuesta, "iPhone 17- 256GB Negro")
        self.assertContains(respuesta, "₡479.900")

    def test_accion_confirmar(self):
        self.client.post(
            self.lista,
            {
                "action": "confirmar_seleccionados",
                "_selected_action": [self.producto.pk],
            },
        )
        self.assertTrue(
            Prices.objects.filter(
                gtin_id=GTIN_IPHONE, product_web_url=URL_IPHONE
            ).exists()
        )

    def test_elegir_otra_variante_a_mano(self):
        url = reverse(
            "admin:ingestion_storeproduct_change", args=[self.producto.pk]
        )
        self.assertContains(self.client.get(url), "iPhone 17 Pro - 256GB Azul")
        self.client.post(url, {"variante": "0195950643428"})
        self.producto.refresh_from_db()
        self.assertEqual(
            (self.producto.suggested_gtin, self.producto.match_reason),
            ("0195950643428", "elegida a mano"),
        )

    def test_accion_rechazar(self):
        self.client.post(
            self.lista,
            {
                "action": "rechazar_seleccionados",
                "_selected_action": [self.producto.pk],
            },
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.status, Status.REJECTED)
