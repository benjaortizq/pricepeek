"""Pruebas unitarias y de integración para el módulo de productos."""

from django.test import TestCase

import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reviews.models import Reviews


from .auditoria import limite_historial_publico
from .correccion import olvidar_vocabulario
from .models import (
    AuditPriceChanges,
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    Products,
    ProductVariants,
    Stores,
)

from .busqueda import buscar_productos, con_imagen, con_imagen_variante
from .views import (
    _serializar_precio,
    buscar_variantes_por_nombre,
    obtener_precios_por_gtin,
)

# Los modelos son managed = False (las tablas viven en Supabase),
# así que en la base de pruebas hay que crear las tablas a mano.
# accounts_user ya existe porque User sí es managed.
MODELOS = [
    Brands,
    Categories,
    Currencies,
    Stores,
    Products,
    ProductVariants,
    ProductImages,
    Prices,
    AuditPriceChanges,
    Reviews,
]


def fechas():
    ahora = timezone.now()
    return {"created_at": ahora, "updated_at": ahora}


class CatalogoTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for modelo in MODELOS:
                editor.create_model(modelo)
        super().setUpClass()

    def setUp(self):
        super().setUp()
        olvidar_vocabulario()  # el «¿quiso decir…?» se arma con los productos de cada prueba

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for modelo in reversed(MODELOS):
                editor.delete_model(modelo)

    @classmethod
    def setUpTestData(cls):
        cls.dos_pinos = Brands.objects.create(
            name="Dos Pinos", slug="dos-pinos", **fechas()
        )
        cls.heinz = Brands.objects.create(
            name="Kraft Heinz", slug="kraft-heinz", **fechas()
        )
        cls.lacteos = Categories.objects.create(name="Lácteos", **fechas())
        cls.salsas = Categories.objects.create(name="Salsas", **fechas())

        cls.leche = cls.producto(
            "Leche entera 1L",
            cls.dos_pinos,
            cls.lacteos,
            "Leche entera pasteurizada.",
        )
        cls.variante_leche = cls.variante(cls.leche, "7441001234567")
        cls.ketchup = cls.producto("Salsa de tomate", cls.heinz, cls.salsas)
        cls.variante_ketchup = cls.variante(cls.ketchup, "0013000000765")

    @classmethod
    def producto(cls, nombre, marca, categoria, descripcion=None):
        return Products.objects.create(
            name=nombre,
            brand=marca,
            category=categoria,
            description=descripcion,
            **fechas(),
        )

    @classmethod
    def variante(cls, producto, gtin):
        return ProductVariants.objects.create(
            product=producto, gtin=gtin, name=producto.name, **fechas()
        )

    @classmethod
    def precio(cls, variante, tienda, precio, descuento="0", disponible=True):
        colones, _ = Currencies.objects.get_or_create(
            name="colones", symbol="₡", defaults=fechas()
        )
        return Prices.objects.create(
            gtin=variante,
            id_store=tienda,
            price=precio,
            discount=Decimal(descuento),
            is_available=disponible,
            currency=colones,
            product_web_url=f"https://tienda.test/{variante.gtin}",
            **fechas(),
        )

    @classmethod
    def imagen(cls, variante, url, principal=False):
        return ProductImages.objects.create(
            variant=variante,
            image_url=url,
            is_main=principal,
            number_image=1,
            **fechas(),
        )


class DetalleProductoTests(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.imagen(cls.variante_leche, "https://img.test/secundaria.png")
        cls.imagen(
            cls.variante_leche,
            "https://img.test/principal.png",
            principal=True,
        )

    def url(self, pk=None):
        return reverse("detalle_producto", kwargs={"pk": pk or self.leche.pk})

    def test_muestra_todos_los_detalles_del_producto(self):
        respuesta = self.client.get(self.url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "Dos Pinos")
        self.assertContains(respuesta, "Lácteos")
        self.assertContains(respuesta, "Leche entera pasteurizada.")
        self.assertContains(respuesta, "7441001234567")

    def test_muestra_la_imagen_principal(self):
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, 'src="https://img.test/principal.png"')
        self.assertNotContains(respuesta, "secundaria.png")

    def test_muestra_el_codigo_de_barras_de_cada_variante(self):
        self.variante(self.leche, "7441001234574")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "7441001234567")
        self.assertContains(respuesta, "7441001234574")

    def test_busca_variantes_por_nombre_sin_distinguir_mayusculas(self):
        variantes = buscar_variantes_por_nombre("LECHE")

        self.assertEqual(list(variantes), [self.variante])

    def test_filtra_variantes_por_categoria_y_marca(self):
        por_categoria = buscar_variantes_por_nombre(
            "leche", categoria=self.producto.category
        )
        por_marca = buscar_variantes_por_nombre(
            "leche", marca=self.producto.brand
        )

        self.assertEqual(list(por_categoria), [self.variante])
        self.assertEqual(list(por_marca), [self.variante])
        self.assertFalse(
            buscar_variantes_por_nombre("leche", categoria="Bebidas").exists()
        )
        self.assertFalse(
            buscar_variantes_por_nombre(
                "leche", marca="Marca inexistente"
            ).exists()
        )

    def test_obtiene_los_precios_del_mismo_gtin_rankeados(self):
        precios = list(obtener_precios_por_gtin(self.variante.gtin))

        self.assertEqual(
            [precio.price for precio in precios], [2000, 2000, 2500]
        )
        self.assertEqual([precio.ranking for precio in precios], [1, 1, 3])
        self.assertEqual(
            {precio.id_store.name for precio in precios},
            {"Tienda B", "Tienda C", "Tienda A"},
        )

    def test_api_compara_precios_con_filtros_opcionales(self):
        respuesta = self.client.get(
            reverse("comparar_precios"),
            {"nombre": "leche", "categoria": "Lácteos", "marca": "dos-pinos"},
        )

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.json()
        self.assertEqual(contenido["total"], 1)
        self.assertEqual(
            contenido["resultados"][0]["gtin"], self.variante.gtin
        )
        self.assertEqual(
            [
                precio["ranking"]
                for precio in contenido["resultados"][0]["precios"]
            ],
            [1, 1, 3],
        )

    def test_serializa_un_descuento_nulo_como_cero(self):
        precio = SimpleNamespace(
            ranking=1,
            id_store=SimpleNamespace(name="Tienda"),
            final_price=Decimal("1000"),
            currency=SimpleNamespace(symbol="₡"),
            discount=None,
            is_available=True,
            product_web_url="https://tienda.test/producto",
        )

        self.assertEqual(_serializar_precio(precio)["descuento"], 0.0)

    def test_api_exige_el_nombre_para_comparar(self):
        respuesta = self.client.get(reverse("comparar_precios"))

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("error", respuesta.json())

    def test_api_devuelve_las_categorias_y_marcas_para_filtrar(self):
        respuesta = self.client.get(reverse("filtros_productos"))

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.json()
        self.assertIn(
            {"id": self.producto.category_id, "name": "Lácteos"},
            contenido["categorias"],
        )
        self.assertIn(
            {
                "id": self.producto.brand_id,
                "name": "Dos Pinos",
                "slug": "dos-pinos",
            },
            contenido["marcas"],
        )

    def test_producto_sin_imagen_descripcion_ni_variantes(self):
        sencillo = self.producto("Arroz", self.dos_pinos, self.lacteos)
        respuesta = self.client.get(self.url(sencillo.pk))
        self.assertContains(respuesta, "Este producto no tiene imagen.")
        self.assertContains(respuesta, "Sin descripción.")
        self.assertContains(respuesta, "Sin código de barras.")

    def test_producto_inexistente_responde_404(self):
        respuesta = self.client.get(self.url(999))
        self.assertEqual(respuesta.status_code, 404)

    def test_lista_el_precio_de_cada_tienda(self):
        walmart = Stores.objects.create(name="Walmart\n", **fechas())
        automercado = Stores.objects.create(name="Automercado\n", **fechas())
        self.precio(self.variante_leche, walmart, 1760)
        self.precio(self.variante_leche, automercado, 1940, descuento="0.25")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "₡1.760")
        self.assertContains(respuesta, "₡1.455")  # 1940 con 25 % de descuento
        self.assertContains(respuesta, "Descuento de 25 %")
        self.assertContains(
            respuesta,
            '<span class="font-bold text-on-surface text-body-lg">Walmart</span>',
            html=False,
        )
        self.assertContains(
            respuesta, 'href="https://tienda.test/7441001234567"'
        )

    def test_no_marca_ningun_precio_como_el_mejor(self):
        tienda = Stores.objects.create(name="Walmart", **fechas())
        self.precio(self.variante_leche, tienda, 1760)
        self.assertNotContains(self.client.get(self.url()), "Mejor precio")

    def test_indica_precios_no_disponibles(self):
        tienda = Stores.objects.create(name="Peri", **fechas())
        self.precio(self.variante_leche, tienda, None, disponible=False)
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "No disponible")
        self.assertContains(respuesta, "Sin precio")

    def test_producto_sin_precios_lo_indica(self):
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "Todavía no hay precios registrados")

    def test_orden_precios_descripcion_y_resenas(self):
        html = self.client.get(self.url()).content.decode()
        precios = html.index('id="precios-heading"')
        descripcion = html.index('id="descripcion-heading"')
        resenas = html.index('id="resenas-heading"')
        self.assertLess(precios, descripcion)
        self.assertLess(descripcion, resenas)


class HistorialPreciosPublicoTests(CatalogoTestCase):
    def url(self):
        return reverse("detalle_producto", kwargs={"pk": self.leche.pk})

    def crear_oferta(self, nombre="Tienda Historial"):
        tienda = Stores.objects.create(name=nombre, **fechas())
        oferta = self.precio(self.variante_leche, tienda, 1760, "0.10")
        return tienda, oferta

    def crear_auditoria(
        self,
        tienda,
        *,
        old_price=1760,
        new_price=1900,
        old_discount="0.10",
        new_discount="0.05",
        is_active=True,
        created_at=None,
        autor=None,
    ):
        return AuditPriceChanges.objects.create(
            old_price=old_price,
            new_price=new_price,
            old_discount=Decimal(old_discount),
            new_discount=Decimal(new_discount),
            id_requested_by=autor.pk if autor is not None else None,
            created_at=created_at or timezone.now(),
            is_active=is_active,
            gtin_id=self.variante_leche.gtin,
            id_store_id=tienda.pk,
        )

    def test_el_historial_publico_no_expone_actor_ni_identificadores_internos(
        self,
    ):
        tienda, oferta = self.crear_oferta()
        autor = User.objects.create_user(
            email="actor-privado@example.com",
            password="ClaveSegura123",
            role=User.Role.CLIENT,
        )
        self.crear_auditoria(tienda, autor=autor)

        respuesta = self.client.get(self.url())

        self.assertEqual(respuesta.status_code, 200)
        precio_publicado = next(
            precio
            for precio in respuesta.context["precios"]
            if precio.pk == oferta.pk
        )
        historial = respuesta.context["historiales_precio"][
            precio_publicado.historial_clave
        ]
        self.assertEqual(len(historial), 1)
        self.assertEqual(
            set(historial[0]),
            {
                "fecha",
                "precio_anterior",
                "precio_nuevo",
                "descuento_anterior",
                "descuento_nuevo",
            },
        )
        self.assertNotContains(respuesta, autor.email)
        self.assertNotContains(respuesta, "id_requested_by")

    def test_el_historial_publico_muestra_reactivacion_y_desactivacion(self):
        tienda, oferta = self.crear_oferta()
        self.crear_auditoria(
            tienda,
            old_price=1760,
            new_price=1760,
            old_discount="0.10",
            new_discount="0.10",
            is_active=True,
        )
        self.crear_auditoria(
            tienda,
            old_price=1760,
            new_price=1760,
            old_discount="0.10",
            new_discount="0.10",
            is_active=False,
        )

        respuesta = self.client.get(self.url())

        precio_publicado = next(
            precio
            for precio in respuesta.context["precios"]
            if precio.pk == oferta.pk
        )
        historial = respuesta.context["historiales_precio"][
            precio_publicado.historial_clave
        ]
        self.assertEqual(
            {cambio["cambio_disponibilidad"] for cambio in historial},
            {"Reactivación", "Desactivación"},
        )

    def test_el_historial_publico_cubre_exactamente_seis_meses_calendarios(
        self,
    ):
        tienda, oferta = self.crear_oferta()
        ahora = timezone.localtime(timezone.now())
        limite = limite_historial_publico(ahora)
        self.crear_auditoria(tienda, created_at=limite)
        self.crear_auditoria(
            tienda,
            created_at=limite - timedelta(seconds=1),
        )

        with patch("products.auditoria.timezone.now", return_value=ahora):
            respuesta = self.client.get(self.url())

        precio_publicado = next(
            precio
            for precio in respuesta.context["precios"]
            if precio.pk == oferta.pk
        )
        historial = respuesta.context["historiales_precio"][
            precio_publicado.historial_clave
        ]
        self.assertEqual(len(historial), 1)
        fecha = historial[0]["fecha"]
        self.assertIn("T", fecha)
        self.assertTrue(fecha.endswith("-06:00") or fecha.endswith("+00:00"))

    def test_el_precio_es_el_elemento_interactivo_del_modal(self):
        self.crear_oferta()

        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, 'id="price-history-dialog"')
        self.assertContains(respuesta, "data-price-history-trigger")
        self.assertContains(respuesta, "data-price-history-close")
        self.assertContains(respuesta, "No se han registrado cambios")
        self.assertContains(respuesta, 'evento.key === "Escape"')

    def test_el_modal_publico_se_traduce_al_ingles(self):
        self.crear_oferta()
        self.client.cookies["django_language"] = "en"

        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, "Price change history")
        self.assertContains(respuesta, "No changes have been recorded")
        self.assertContains(respuesta, "Previous price")


class GraficaHistorialPreciosTests(CatalogoTestCase):
    def url(self):
        return reverse("detalle_producto", kwargs={"pk": self.leche.pk})

    def crear_oferta(
        self,
        nombre="Tienda Gráfica",
        *,
        precio=1000,
        descuento="0",
        disponible=True,
        creada=None,
    ):
        tienda = Stores.objects.create(name=nombre, **fechas())
        oferta = self.precio(
            self.variante_leche,
            tienda,
            precio,
            descuento,
            disponible=disponible,
        )
        if creada is None:
            creada = timezone.now() - timedelta(days=30)
        Prices.objects.filter(pk=oferta.pk).update(created_at=creada)
        return tienda, oferta

    def crear_auditoria(
        self,
        tienda,
        *,
        old_price=1000,
        new_price=900,
        old_discount="0",
        new_discount="0",
        is_active=True,
        creada=None,
        autor=None,
    ):
        return AuditPriceChanges.objects.create(
            old_price=old_price,
            new_price=new_price,
            old_discount=Decimal(old_discount),
            new_discount=Decimal(new_discount),
            id_requested_by=autor.pk if autor is not None else None,
            created_at=creada or timezone.now(),
            is_active=is_active,
            gtin_id=self.variante_leche.gtin,
            id_store_id=tienda.pk,
        )

    def obtener_grafica(self, respuesta):
        graficas = respuesta.context["grafica_precios"]["graficas"]
        self.assertEqual(len(graficas), 1)
        return graficas[0]

    def test_muestra_lineas_por_tienda_y_marcadores_para_varias_tiendas(self):
        ahora = timezone.localtime(timezone.now())
        tienda_a, _ = self.crear_oferta("Tienda A")
        tienda_b, _ = self.crear_oferta("Tienda B", precio=1200)
        self.crear_auditoria(
            tienda_a,
            new_price=950,
            creada=ahora - timedelta(days=2),
        )
        self.crear_auditoria(
            tienda_b,
            old_price=1200,
            new_price=1100,
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        grafica = self.obtener_grafica(respuesta)
        self.assertEqual(
            {serie["tienda"] for serie in grafica["series"]},
            {"Tienda A", "Tienda B"},
        )
        self.assertEqual(
            [len(serie["cambios"]) for serie in grafica["series"]],
            [1, 1],
        )
        self.assertContains(respuesta, "Historial de precios por tienda")
        self.assertContains(respuesta, "data-chart-marker")
        self.assertContains(respuesta, "data-chart-legend-toggle")
        self.assertContains(respuesta, "Resumen accesible de los cambios")

    def test_la_grafica_aparece_al_final_del_detalle_publico(self):
        self.crear_oferta()

        html = self.client.get(self.url()).content.decode()

        self.assertLess(
            html.index("resenas-heading"), html.index("price-chart-heading")
        )

    def test_cada_marcador_es_interactivo_y_describe_el_cambio(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        self.crear_auditoria(
            tienda,
            new_price=950,
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        cambio = self.obtener_grafica(respuesta)["series"][0]["cambios"][0]
        self.assertIn("Tienda Gráfica", cambio["aria_label"])
        self.assertIn("₡1.000", cambio["aria_label"])
        self.assertIn("₡950", cambio["aria_label"])
        self.assertIn("Disponible", cambio["aria_label"])
        self.assertContains(respuesta, 'role="button"')
        self.assertContains(respuesta, 'tabindex="0"')
        self.assertContains(
            respuesta, 'aria-controls="price-chart-detail-grafica-1"'
        )

    def test_la_serie_de_un_producto_menor_de_seis_meses_comienza_en_su_creacion(
        self,
    ):
        ahora = timezone.localtime(timezone.now())
        creacion = ahora - timedelta(days=20)
        self.crear_oferta(creada=creacion)

        respuesta = self.client.get(self.url())

        grafica = self.obtener_grafica(respuesta)
        serie = grafica["series"][0]
        self.assertEqual(serie["introduccion"], creacion.isoformat())
        self.assertEqual(serie["inicio_visible"], creacion.isoformat())
        self.assertEqual(
            serie["tramos"][0]["desde_texto"], creacion.isoformat()
        )
        self.assertEqual(
            respuesta.context["grafica_precios"]["ventana"]["meses"],
            6,
        )

    def test_una_tienda_sin_cambios_produce_una_linea_horizontal(self):
        self.crear_oferta()

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(serie["cambios"], [])
        self.assertEqual(len(serie["tramos"]), 1)
        tramo = serie["tramos"][0]
        self.assertLess(tramo["x1"], tramo["x2"])
        self.assertTrue(tramo["disponible"])

    def test_desactivacion_y_reactivacion_interrumpen_la_serie(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        desactivacion = ahora - timedelta(days=3)
        reactivacion = ahora - timedelta(days=1)
        self.crear_auditoria(
            tienda,
            old_price=1000,
            new_price=1000,
            is_active=False,
            creada=desactivacion,
        )
        self.crear_auditoria(
            tienda,
            old_price=1000,
            new_price=1000,
            is_active=True,
            creada=reactivacion,
        )

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(
            [cambio["tipo"] for cambio in serie["cambios"]],
            ["desactivacion", "reactivacion"],
        )
        self.assertEqual(
            [tramo["disponible"] for tramo in serie["tramos"]],
            [True, False, True],
        )

    def test_una_desactivacion_sin_reactivacion_no_reanuda_la_linea(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        self.crear_auditoria(
            tienda,
            old_price=1000,
            new_price=1000,
            is_active=False,
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(
            [cambio["tipo"] for cambio in serie["cambios"]], ["desactivacion"]
        )
        self.assertEqual(
            [tramo["disponible"] for tramo in serie["tramos"]],
            [True, False],
        )

    def test_conserva_dos_cambios_registrados_el_mismo_dia(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        dia_anterior = ahora - timedelta(days=1)
        self.crear_auditoria(
            tienda,
            new_price=950,
            creada=dia_anterior.replace(
                hour=9, minute=0, second=0, microsecond=0
            ),
        )
        self.crear_auditoria(
            tienda,
            old_price=950,
            new_price=900,
            creada=dia_anterior.replace(
                hour=15, minute=0, second=0, microsecond=0
            ),
        )

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(len(serie["cambios"]), 2)
        self.assertNotEqual(serie["cambios"][0]["x"], serie["cambios"][1]["x"])
        self.assertEqual(
            [cambio["precio_nuevo"] for cambio in serie["cambios"]],
            [950, 900],
        )

    def test_una_sola_tienda_produce_una_sola_serie(self):
        self.crear_oferta()

        respuesta = self.client.get(self.url())

        grafica = self.obtener_grafica(respuesta)
        self.assertEqual(len(grafica["series"]), 1)
        self.assertEqual(grafica["series"][0]["tienda"], "Tienda Gráfica")

    def test_el_html_y_el_json_de_la_grafica_no_exponen_actores_ni_ids_internos(
        self,
    ):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        autor = User.objects.create_user(
            email="actor-grafica@example.com",
            password="ClaveSegura123",
            role=User.Role.CLIENT,
        )
        self.crear_auditoria(
            tienda,
            new_price=950,
            creada=ahora - timedelta(days=1),
            autor=autor,
        )

        respuesta = self.client.get(self.url())

        datos = respuesta.context["grafica_precios"]
        self.assertNotContains(respuesta, autor.email)
        self.assertNotContains(respuesta, "id_requested_by")
        self.assertNotIn("id_requested_by", str(datos))
        self.assertNotIn("id_store", str(datos))
        self.assertNotIn("gtin", str(datos))
        self.assertNotIn("id_user", str(datos))

    def test_b3_y_la_grafica_comparten_una_sola_consulta_de_auditoria(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta()
        self.crear_auditoria(
            tienda,
            new_price=950,
            creada=ahora - timedelta(days=1),
        )

        with CaptureQueriesContext(connection) as consultas:
            self.client.get(self.url())

        consultas_auditoria = [
            consulta
            for consulta in consultas.captured_queries
            if "audit_price_changes" in consulta["sql"].lower()
        ]
        self.assertEqual(len(consultas_auditoria), 1)

    def test_el_precio_final_de_la_grafica_usa_el_redondeo_del_detalle(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta(precio=1001, descuento="0.34")
        self.crear_auditoria(
            tienda,
            old_price=1001,
            new_price=1002,
            old_discount="0.34",
            new_discount="0.33",
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        cambio = self.obtener_grafica(respuesta)["series"][0]["cambios"][0]
        self.assertEqual(cambio["precio_anterior"], 661)
        self.assertEqual(cambio["precio_nuevo"], 671)

    def test_primer_cambio_combinado_de_precio_y_disponibilidad_interrumpe_la_serie(
        self,
    ):
        ahora = timezone.localtime(timezone.now())
        tienda, oferta = self.crear_oferta()
        Prices.objects.filter(pk=oferta.pk).update(
            price=900,
            is_available=False,
        )
        self.crear_auditoria(
            tienda,
            old_price=1000,
            new_price=900,
            is_active=False,
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(serie["cambios"][0]["tipo"], "desactivacion")
        self.assertEqual(
            [tramo["disponible"] for tramo in serie["tramos"]],
            [True, False],
        )

    def test_un_precio_eliminado_no_extiende_la_serie_hasta_el_fin_de_la_ventana(
        self,
    ):
        ahora = timezone.localtime(timezone.now())
        tienda, oferta = self.crear_oferta()
        self.crear_auditoria(
            tienda,
            new_price=900,
            creada=ahora - timedelta(days=10),
        )
        eliminacion = ahora - timedelta(days=1)
        Prices.objects.filter(pk=oferta.pk).update(
            price=None,
            is_available=False,
            updated_at=eliminacion,
        )

        respuesta = self.client.get(self.url())

        serie = self.obtener_grafica(respuesta)["series"][0]
        self.assertEqual(
            serie["tramos"][-1]["hasta_texto"],
            eliminacion.isoformat(),
        )
        self.assertTrue(
            all(tramo["hasta"] <= eliminacion for tramo in serie["tramos"])
        )

    def test_un_cambio_que_conserva_el_precio_final_se_marca_sin_cambio(self):
        ahora = timezone.localtime(timezone.now())
        tienda, _ = self.crear_oferta(precio=1002, descuento="0.34")
        self.crear_auditoria(
            tienda,
            old_price=1001,
            new_price=1002,
            old_discount="0.34",
            new_discount="0.34",
            creada=ahora - timedelta(days=1),
        )

        respuesta = self.client.get(self.url())

        cambio = self.obtener_grafica(respuesta)["series"][0]["cambios"][0]
        self.assertEqual(cambio["tipo"], "sin_cambio")
        self.assertEqual(cambio["precio_anterior"], 661)
        self.assertEqual(cambio["precio_nuevo"], 661)

        self.client.cookies["django_language"] = "en"
        respuesta_en = self.client.get(self.url())
        self.assertContains(respuesta_en, "No change in final price")

    def test_las_coordenadas_svg_no_se_localizan_en_espanol(self):
        self.crear_oferta()

        for idioma in ("es", "en"):
            with self.subTest(idioma=idioma):
                self.client.cookies["django_language"] = idioma
                respuesta = self.client.get(self.url())
                html = respuesta.content.decode()

                linea = re.search(
                    r'<line class="price-chart-line"([^>]*)>',
                    html,
                )
                self.assertIsNotNone(linea)
                coordenadas = re.findall(
                    r'\b(?:x1|x2|y1|y2)="([^"]+)"',
                    linea.group(1),
                )
                self.assertTrue(coordenadas)
                for coordenada in coordenadas:
                    self.assertNotIn(",", coordenada)
                    float(coordenada)

    def test_la_grafica_se_traduce_al_ingles(self):
        self.crear_oferta()
        self.client.cookies["django_language"] = "en"

        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, "Price history by store")
        self.assertContains(respuesta, "Accessible summary of changes")
        self.assertContains(respuesta, "Previous final price")


class DetalleMarcaTests(CatalogoTestCase):
    def url(self, slug="dos-pinos"):
        return reverse("detalle_marca", kwargs={"slug": slug})

    def test_muestra_el_nombre_y_la_descripcion_de_la_marca(self):
        Brands.objects.filter(pk=self.dos_pinos.pk).update(
            description="Productos lácteos de la familia Dos Pinos."
        )

        respuesta = self.client.get(self.url())

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Dos Pinos")
        self.assertContains(
            respuesta, "Productos lácteos de la familia Dos Pinos."
        )
        self.assertContains(respuesta, "Sobre la marca")

    def test_muestra_solo_los_productos_de_la_marca(self):
        yogurt = self.producto("Yogur natural", self.dos_pinos, self.lacteos)

        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "Yogur natural")
        self.assertNotContains(respuesta, "Salsa de tomate")
        self.assertEqual(
            [producto.pk for producto in respuesta.context["productos"]],
            [self.leche.pk, yogurt.pk],
        )

    def test_el_nombre_de_la_marca_en_el_detalle_es_un_enlace(self):
        respuesta = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )

        self.assertContains(respuesta, f'href="{self.url()}"')

    def test_omite_la_descripcion_cuando_la_marca_no_tiene_una(self):
        respuesta = self.client.get(self.url())

        self.assertNotContains(respuesta, "Sobre la marca")

    def test_una_marca_inexistente_responde_404(self):
        respuesta = self.client.get(self.url("marca-inexistente"))

        self.assertEqual(respuesta.status_code, 404)


class BuscarProductosTests(CatalogoTestCase):
    def buscar(self, palabra):
        return list(buscar_productos(palabra))

    def test_encuentra_por_nombre_del_producto(self):
        self.assertEqual(self.buscar("leche"), [self.leche])

    def test_encuentra_por_nombre_de_la_marca(self):
        self.assertEqual(self.buscar("heinz"), [self.ketchup])

    def test_no_importan_mayusculas_ni_espacios_alrededor(self):
        self.assertEqual(self.buscar("  DOS pinos "), [self.leche])

    def test_palabra_vacia_devuelve_todos_los_productos(self):
        self.assertEqual(self.buscar(""), [self.leche, self.ketchup])

    def test_sin_coincidencias_devuelve_lista_vacia(self):
        self.assertEqual(self.buscar("televisor"), [])

    def test_letras_repetidas_de_mas_o_de_menos(self):
        tutto = Brands.objects.create(name="Tutto", slug="tutto", **fechas())
        bombon = self.producto("Bombón TUTTO de chocolate", tutto, self.salsas)
        galleta = self.producto("Galleta de vainilla", tutto, self.salsas)
        for palabra in ("tuto", "Tutto", "TUTTO", "tUtTo"):
            with self.subTest(palabra=palabra):
                self.assertEqual(
                    self.buscar(palabra), [bombon, galleta]
                )  # por el nombre o por la marca
        self.assertEqual(self.buscar("galeta"), [galleta])

    def test_sin_importar_tildes(self):
        cafe = self.producto("Café molido", self.dos_pinos, self.lacteos)
        pina = self.producto("Jugo de piña", self.dos_pinos, self.lacteos)
        self.assertEqual(self.buscar("cafe"), [cafe])
        self.assertEqual(self.buscar("CAFÉ"), [cafe])
        self.assertEqual(self.buscar("pina"), [pina])
        self.assertEqual(self.buscar("bombón"), [])

    def test_sin_signos(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        refresco = self.producto(
            "Refresco Coca-Cola 600 ml", self.heinz, self.salsas
        )
        self.assertEqual(self.buscar("mms"), [chocolate])
        self.assertEqual(self.buscar("m&m"), [chocolate])
        self.assertEqual(self.buscar("cocacola"), [refresco])
        self.assertEqual(self.buscar("coca-cola"), [refresco])

    def test_cada_palabra_en_el_nombre_o_la_marca_en_cualquier_orden(self):
        self.assertEqual(self.buscar("leche dos pinos"), [self.leche])
        self.assertEqual(self.buscar("pinos leche"), [self.leche])
        self.assertEqual(self.buscar("leche heinz"), [])

    def test_m_y_m_no_es_cualquier_cosa_con_m(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        self.assertEqual(
            self.buscar("m&m"), [chocolate]
        )  # no "Salsa de tomate"
        self.assertEqual(self.buscar("mms"), [chocolate])

    def test_primero_lo_que_tiene_el_texto_tal_cual(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        boquita = self.producto(
            "Boquita Yummies", self.dos_pinos, self.salsas
        )  # "mm" se parece a "m&m"
        self.assertEqual(self.buscar("m&m"), [chocolate, boquita])

    def test_un_espacio_no_cuenta_como_signo(self):
        crema = self.producto(
            "Galletas a la crema", self.dos_pinos, self.lacteos
        )
        sal = self.producto("Sal de mesa", self.dos_pinos, self.lacteos)
        self.assertEqual(
            self.buscar("sal"), [sal, self.ketchup]
        )  # "Salsa", pero no "galleta[s a l]a"
        self.assertEqual(self.buscar("galletas"), [crema])

    def test_los_numeros_no_se_estiran(self):
        agua = self.producto("Agua 100 ml", self.dos_pinos, self.lacteos)
        self.assertEqual(self.buscar("100"), [agua])
        self.assertEqual(self.buscar("1000"), [])

    def test_solo_signos_es_como_no_buscar_nada(self):
        self.assertEqual(self.buscar(" - & "), [self.leche, self.ketchup])

    def test_imagen_de_cada_producto_en_una_sola_consulta(self):
        self.imagen(self.variante_leche, "https://img.test/secundaria.png")
        self.imagen(
            self.variante_leche,
            "https://img.test/principal.png",
            principal=True,
        )
        self.imagen(self.variante_ketchup, "https://img.test/ketchup.png")
        self.producto(
            "Yogur natural", self.dos_pinos, self.lacteos
        )  # sin imagen
        with self.assertNumQueries(2):  # los productos y las imágenes de todos
            productos = con_imagen(buscar_productos(""))
        self.assertEqual(
            [p.imagen_url for p in productos],
            [
                "https://img.test/principal.png",
                "https://img.test/ketchup.png",
                None,
            ],
        )

    def test_imagen_de_cada_variante_en_una_sola_consulta(self):
        otra_leche = self.variante(
            self.leche, "7441001234598"
        )  # misma familia, sin imagen propia
        self.imagen(self.variante_leche, "https://img.test/secundaria.png")
        self.imagen(
            self.variante_leche,
            "https://img.test/principal.png",
            principal=True,
        )
        self.imagen(self.variante_ketchup, "https://img.test/ketchup.png")
        variantes = [self.variante_leche, otra_leche, self.variante_ketchup]
        with self.assertNumQueries(1):  # las imágenes de todas
            variantes = con_imagen_variante(variantes)
        self.assertEqual(
            [v.imagen_url for v in variantes],
            [
                "https://img.test/principal.png",
                None,
                "https://img.test/ketchup.png",
            ],
        )


class PaginaBusquedaTests(CatalogoTestCase):
    def test_muestra_los_resultados(self):
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "heinz"}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_todavia_no_muestra_precio(self):
        tienda = Stores.objects.create(name="Walmart", **fechas())
        self.precio(self.variante_ketchup, tienda, 1760)
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "heinz"}
        )
        self.assertNotContains(respuesta, "₡")

    def test_avisa_cuando_no_hay_resultados(self):
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "televisor"}
        )
        self.assertContains(respuesta, "No encontramos productos")

    def test_los_resultados_se_paginan_de_24_en_24(self):
        for i in range(25):
            yogur = self.producto(
                f"Yogur {i:02d}", self.dos_pinos, self.lacteos
            )
            self.variante(
                yogur, f"7441000{i:06d}"
            )  # la búsqueda muestra variantes
        primera = self.client.get(reverse("buscar_productos"), {"q": "yogur"})
        self.assertEqual(len(primera.context["variantes"]), 24)
        self.assertContains(primera, "Página 1 de 2")
        segunda = self.client.get(
            reverse("buscar_productos"), {"q": "yogur", "pagina": 2}
        )
        self.assertEqual(len(segunda.context["variantes"]), 1)

    def test_la_pagina_busca_sin_tildes_ni_signos_ni_letras_repetidas(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        cafe = self.variante(
            self.producto("Café molido", self.dos_pinos, self.lacteos),
            "7441000999901",
        )
        tutto = self.variante(
            self.producto("Bombón TUTTO", self.dos_pinos, self.salsas),
            "7441000999902",
        )
        mms = self.variante(
            self.producto("Chocolate con maní", mars, self.salsas),
            "7441000999903",
        )
        for palabra, esperada in (
            ("cafe", cafe),
            ("tuto", tutto),
            ("mms", mms),
            ("pinos leche", self.variante_leche),
        ):
            with self.subTest(palabra=palabra):
                respuesta = self.client.get(
                    reverse("buscar_productos"), {"q": palabra}
                )
                self.assertEqual(
                    list(respuesta.context["variantes"]), [esperada]
                )

    def test_la_correccion_respeta_los_filtros(self):
        sin_filtro = self.client.get(
            reverse("buscar_productos"), {"q": "lece"}
        )
        self.assertContains(sin_filtro, "Mostrando resultados para «leche»")
        respuesta = self.client.get(
            reverse("buscar_productos"),
            {"q": "lece", "categoria": self.salsas.pk},
        )  # «leche» existe, pero no en Salsas
        self.assertEqual(list(respuesta.context["variantes"]), [])
        self.assertNotContains(respuesta, "Mostrando resultados")
        self.assertContains(
            respuesta,
            "No encontramos productos con «lece» en la categoría o marca seleccionada",
        )

    def test_la_pantalla_principal_muestra_los_productos(self):
        cliente = User.objects.create_user(
            email="ana@correo.com", password="Clave2026segura"
        )
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse("inicio_cliente"))
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertContains(respuesta, "Leche entera 1L")
