"""Pruebas del issue «Historial de precios».

El historial se guarda cada vez que cambia un precio (la obtención de datos,
el portal de empresas o la vinculación de productos), el detalle del producto
muestra su gráfico de los últimos 6 meses y el panel de administración
muestra la comparativa de cada actualización.
"""

import importlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import User
from enterprise.services import (
    desactivar_precio_empresa,
    editar_precio_empresa,
    quitar_precio_empresa,
)
from ingestion.actualizacion import guardar_cambios

from .historial import (
    AGOTADO,
    BAJO,
    DISPONIBLE,
    NUEVO,
    OTRO,
    SUBIO,
    colores_de_tiendas,
    comparativa,
    graficos_del_producto,
    inicio_del_grafico,
    marcas_de_meses,
    precio_final,
    registrar,
    tipo_de_cambio,
)
from .models import PriceHistory, Prices, Stores
from .tests import CatalogoTestCase, fechas

Origen = PriceHistory.Source
CLAVE = "Clave2026segura"
ZONA = timezone.get_default_timezone()


def hace(dias):
    return timezone.now() - timedelta(days=dias)


class HistorialTestCase(CatalogoTestCase):
    """La leche en Walmart (₡1.000) y en Gollo (₡1.200)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.walmart = Stores.objects.create(name="Walmart\n", **fechas())
        cls.gollo = Stores.objects.create(name="Gollo", **fechas())
        cls.en_walmart = cls.precio(cls.variante_leche, cls.walmart, 1000)
        cls.en_gollo = cls.precio(cls.variante_leche, cls.gollo, 1200)

    def cambiar(self, precio, origen=Origen.SCRAPING, cuando=None, **campos):
        Prices.objects.filter(pk=precio.pk).update(**campos)
        return registrar([precio.pk], origen, cuando=cuando)

    def registros(self, precio):
        return list(
            PriceHistory.objects.filter(
                store_id=precio.id_store_id, gtin_id=precio.gtin_id
            ).order_by("recorded_at", "id")
        )


class RegistrarTests(HistorialTestCase):
    def test_el_primer_registro_no_tiene_precio_anterior(self):
        [registro] = registrar([self.en_walmart], Origen.EMPRESA)
        self.assertEqual(
            (registro.store_id, registro.gtin_id, registro.final_price),
            (self.walmart.pk, "7441001234567", 1000),
        )
        self.assertIsNone(registro.previous_final_price)
        self.assertIsNone(registro.was_available)
        self.assertEqual(registro.source, Origen.EMPRESA)
        self.assertEqual(tipo_de_cambio(registro), NUEVO)

    def test_si_nada_cambio_no_se_repite(self):
        registrar([self.en_walmart], Origen.SCRAPING)
        self.assertEqual(registrar([self.en_walmart], Origen.SCRAPING), [])
        self.assertEqual(len(self.registros(self.en_walmart)), 1)

    def test_guarda_como_estaba_antes_del_cambio(self):
        registrar([self.en_walmart], Origen.SCRAPING)
        [registro] = self.cambiar(self.en_walmart, price=900)
        self.assertEqual(
            (registro.previous_final_price, registro.final_price), (1000, 900)
        )
        self.assertTrue(registro.was_available)
        self.assertEqual(tipo_de_cambio(registro), BAJO)
        self.assertEqual(
            tipo_de_cambio(self.cambiar(self.en_walmart, price=950)[0]), SUBIO
        )

    def test_el_precio_final_lleva_el_descuento(self):
        [registro] = self.cambiar(self.en_walmart, discount=Decimal("0.25"))
        self.assertEqual((registro.price, registro.final_price), (1000, 750))
        # Se redondea como en el detalle del producto: ,5 hacia arriba.
        self.assertEqual(precio_final(1005, Decimal("0.50")), 503)
        self.assertIsNone(precio_final(None, Decimal("0.10")))

    def test_la_disponibilidad_tambien_es_un_cambio(self):
        registrar([self.en_walmart], Origen.SCRAPING)
        [agotado] = self.cambiar(self.en_walmart, is_available=False)
        self.assertEqual(tipo_de_cambio(agotado), AGOTADO)
        [disponible] = self.cambiar(self.en_walmart, is_available=True)
        self.assertEqual(tipo_de_cambio(disponible), DISPONIBLE)

    def test_cambiar_el_descuento_sin_cambiar_el_precio_final(self):
        registrar([self.en_walmart], Origen.SCRAPING)
        [registro] = self.cambiar(
            self.en_walmart, price=1250, discount=Decimal("0.20")
        )
        self.assertEqual(registro.final_price, 1000)
        self.assertEqual(tipo_de_cambio(registro), OTRO)


class EscriturasDePreciosTests(HistorialTestCase):
    """Todo lo que escribe en prices deja su registro en el historial."""

    def test_la_obtencion_de_datos(self):
        guardar_cambios(self.en_walmart, {"price": (1000, 1100)})
        [registro] = self.registros(self.en_walmart)
        self.assertEqual(
            (registro.final_price, registro.source), (1100, Origen.SCRAPING)
        )

    def test_la_obtencion_de_datos_sin_cambios_no_agrega_nada(self):
        guardar_cambios(self.en_walmart, {})  # solo confirma que sigue igual
        self.assertEqual(self.registros(self.en_walmart), [])

    def test_el_portal_de_empresas(self):
        editar_precio_empresa(
            self.walmart,
            self.en_walmart.pk,
            {"price": 980, "discount": Decimal("0"), "is_available": True},
        )
        desactivar_precio_empresa(self.walmart, self.en_walmart.pk)
        quitar_precio_empresa(self.walmart, self.en_walmart.pk)
        registros = self.registros(self.en_walmart)
        self.assertEqual(
            [(r.final_price, r.is_available) for r in registros],
            [(980, True), (980, False), (None, False)],
        )
        self.assertEqual({r.source for r in registros}, {Origen.EMPRESA})


class GraficoTests(HistorialTestCase):
    def setUp(self):
        super().setUp()
        self.ahora = timezone.now()
        self.desde = inicio_del_grafico(self.ahora)

    def grafico(self):
        precios = Prices.objects.select_related("id_store", "currency").filter(
            gtin_id=self.variante_leche.gtin
        )
        return graficos_del_producto(precios, ahora=self.ahora)[
            self.variante_leche.gtin
        ]

    def serie(self, grafico, tienda):
        return next(s for s in grafico["series"] if s["tienda"] == tienda)

    def test_una_linea_por_tienda_que_llega_hasta_hoy(self):
        registrar(
            [self.en_walmart, self.en_gollo], Origen.INICIAL, cuando=hace(20)
        )
        self.cambiar(self.en_walmart, price=900, cuando=hace(5))
        grafico = self.grafico()
        self.assertEqual(
            [s["tienda"] for s in grafico["series"]], ["Walmart", "Gollo"]
        )
        walmart = self.serie(grafico, "Walmart")
        self.assertEqual(
            [valor for _, valor in walmart["puntos"]], [1000, 900, 900]
        )
        self.assertEqual(
            walmart["puntos"][-1][0], int(self.ahora.timestamp() * 1000)
        )
        self.assertEqual(walmart["actual"], 900)
        self.assertEqual(grafico["datos"]["simbolo"], "₡")

    def test_abarca_los_ultimos_6_meses(self):
        registrar([self.en_walmart], Origen.INICIAL, cuando=hace(400))
        self.cambiar(self.en_walmart, price=1100, cuando=hace(300))
        self.cambiar(self.en_walmart, price=950, cuando=hace(30))
        walmart = self.serie(self.grafico(), "Walmart")
        # El precio que tenía hace 6 meses empieza la línea; lo de antes no sale.
        self.assertEqual(
            walmart["puntos"][0], [int(self.desde.timestamp() * 1000), 1100]
        )
        self.assertEqual(
            [valor for _, valor in walmart["puntos"]], [1100, 950, 950]
        )
        datos = self.grafico()["datos"]
        self.assertEqual(datos["desde"], int(self.desde.timestamp() * 1000))
        self.assertIsNone(self.grafico()["empieza_el"])

    def test_dice_desde_cuando_hay_historial(self):
        registrar(
            [self.en_walmart, self.en_gollo], Origen.INICIAL, cuando=hace(10)
        )
        empieza = self.grafico()["empieza_el"]
        self.assertEqual(
            timezone.localtime(empieza).date(),
            timezone.localtime(hace(10)).date(),
        )

    def test_la_linea_se_corta_cuando_no_estaba_disponible(self):
        registrar([self.en_walmart], Origen.INICIAL, cuando=hace(20))
        self.cambiar(self.en_walmart, is_available=False, cuando=hace(10))
        self.cambiar(self.en_walmart, is_available=True, cuando=hace(5))
        walmart = self.serie(self.grafico(), "Walmart")
        self.assertEqual(
            [valor for _, valor in walmart["puntos"]], [1000, None, 1000, 1000]
        )

    def test_sin_historial_usa_el_precio_actual(self):
        gollo = self.serie(self.grafico(), "Gollo")
        self.assertEqual([valor for _, valor in gollo["puntos"]], [1200, 1200])

    def test_el_color_sigue_a_la_tienda(self):
        colores = colores_de_tiendas({self.gollo.pk, self.walmart.pk})
        self.assertEqual(colores[self.walmart.pk], (1, False))
        self.assertEqual(colores[self.gollo.pk], (2, False))
        # Pasadas las 8 tiendas el color se repite, pero con la línea punteada.
        self.assertEqual(colores_de_tiendas(range(10))[8], (1, True))

    def test_la_tabla_del_grafico_tiene_el_precio_de_cada_tienda(self):
        registrar(
            [self.en_walmart, self.en_gollo], Origen.INICIAL, cuando=hace(20)
        )
        self.cambiar(self.en_gollo, price=1150, cuando=hace(3))
        columnas, filas = self.grafico()["tabla"]
        self.assertEqual([c["nombre"] for c in columnas], ["Walmart", "Gollo"])
        ultima = filas[0]  # la más reciente primero
        self.assertEqual(ultima["tienda"], "Gollo")
        self.assertEqual([c["final"] for c in ultima["celdas"]], [1000, 1150])
        self.assertEqual([c["cambio"] for c in ultima["celdas"]], ["", BAJO])
        self.assertEqual(
            ultima["celdas"][1]["diferencia"],
            {"monto": "₡50", "porcentaje": "4"},
        )
        self.assertTrue(ultima["celdas"][0]["es_mejor"])


class FechasDelGraficoTests(TestCase):
    def test_seis_meses_atras(self):
        cuando = datetime(2026, 11, 25, 15, 30, tzinfo=ZONA)
        self.assertEqual(
            inicio_del_grafico(cuando),
            datetime(2026, 5, 25, 15, 30, tzinfo=ZONA),
        )
        self.assertEqual(
            inicio_del_grafico(datetime(2026, 3, 10, tzinfo=ZONA)),
            datetime(2025, 9, 10, tzinfo=ZONA),
        )
        # El 31 de agosto no tiene febrero: se recorta al último día del mes.
        self.assertEqual(
            inicio_del_grafico(datetime(2028, 8, 31, tzinfo=ZONA)).date(),
            datetime(2028, 2, 29).date(),
        )

    def test_un_mes_por_marca_en_el_idioma_de_la_pagina(self):
        desde = datetime(2026, 5, 25, tzinfo=ZONA)
        hasta = datetime(2026, 11, 25, tzinfo=ZONA)
        with translation.override("es"):
            meses = [m["texto"] for m in marcas_de_meses(desde, hasta)]
        self.assertEqual(meses, ["Jun", "Jul", "Ago", "Sep", "Oct", "Nov"])
        with translation.override("en"):
            self.assertEqual(marcas_de_meses(desde, hasta)[1]["texto"], "Jul")


class DetalleDelProductoTests(HistorialTestCase):
    def test_el_detalle_muestra_el_grafico(self):
        registrar(
            [self.en_walmart, self.en_gollo], Origen.INICIAL, cuando=hace(40)
        )
        self.cambiar(self.en_walmart, price=900, cuando=hace(2))
        respuesta = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )
        self.assertContains(respuesta, "Historial de precios")
        self.assertContains(
            respuesta, "Precio final de cada tienda en los últimos 6 meses."
        )
        self.assertContains(
            respuesta, 'data-historial="historial-datos-7441001234567"'
        )
        self.assertContains(respuesta, "js/historial-precios.js")
        datos = json.loads(
            respuesta.content.decode()
            .split(
                '<script id="historial-datos-7441001234567" type="application/json">'
            )[1]
            .split("</script>")[0]
        )
        self.assertEqual(
            [s["tienda"] for s in datos["series"]], ["Walmart", "Gollo"]
        )
        self.assertEqual(len(datos["meses"]), 6)
        # La tabla de datos, para leerlo sin el gráfico.
        self.assertContains(respuesta, "Ver los datos del gráfico")
        self.assertContains(respuesta, "Bajó ₡100 (10 %)")

    def test_en_ingles(self):
        registrar([self.en_walmart], Origen.INICIAL, cuando=hace(2))
        self.client.cookies["django_language"] = "en"
        with translation.override("en"):
            respuesta = self.client.get(
                reverse("detalle_producto", args=[self.leche.pk]),
                headers={"accept-language": "en"},
            )
        self.assertContains(respuesta, "Price history")
        self.assertContains(
            respuesta, "Final price at each store over the last 6 months."
        )

    def test_sin_precios_no_hay_grafico(self):
        Prices.objects.all().delete()
        respuesta = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )
        self.assertNotContains(respuesta, "Historial de precios")
        self.assertNotContains(respuesta, "historial-precios.js")


class PanelDelHistorialTests(HistorialTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )
        cls.empresa = User.objects.create_user(
            email="empresa@example.com", password=CLAVE, role="enterprise"
        )

    def setUp(self):
        super().setUp()
        registrar(
            [self.en_walmart, self.en_gollo], Origen.INICIAL, cuando=hace(60)
        )
        self.cambiar(self.en_walmart, price=900, cuando=hace(3))
        self.cambiar(
            self.en_gollo, price=1300, origen=Origen.EMPRESA, cuando=hace(2)
        )
        self.cambiar(self.en_gollo, is_available=False, cuando=hace(1))
        self.client.force_login(self.admin)

    def test_solo_los_administradores(self):
        self.client.force_login(self.empresa)
        self.assertEqual(
            self.client.get(reverse("historial_de_precios")).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                reverse("historial_de_presentacion", args=["7441001234567"])
            ).status_code,
            403,
        )

    def test_lista_los_cambios_sin_el_precio_inicial(self):
        respuesta = self.client.get(reverse("historial_de_precios"))
        cambios = list(respuesta.context["pagina"].object_list)
        self.assertEqual([c.cambio for c in cambios], [AGOTADO, SUBIO, BAJO])
        self.assertContains(respuesta, "Bajó ₡100 (10 %)")
        self.assertContains(respuesta, "Subió ₡100 (8 %)")
        self.assertContains(respuesta, "Dejó de estar disponible")
        self.assertContains(respuesta, "Portal de empresas")
        self.assertContains(
            respuesta,
            reverse("historial_de_presentacion", args=["7441001234567"]),
        )
        # La barra lateral del panel lleva a esta pantalla.
        self.assertContains(respuesta, 'aria-current="page"')

    def test_las_pestanas_y_los_filtros(self):
        url = reverse("historial_de_precios")
        bajaron = (
            self.client.get(url, {"cambio": "bajaron"})
            .context["pagina"]
            .object_list
        )
        self.assertEqual([c.store_id for c in bajaron], [self.walmart.pk])
        subieron = (
            self.client.get(url, {"cambio": "subieron"})
            .context["pagina"]
            .object_list
        )
        self.assertEqual([c.store_id for c in subieron], [self.gollo.pk])
        disponibilidad = self.client.get(
            url, {"cambio": "disponibilidad"}
        ).context["pagina"]
        self.assertEqual(disponibilidad.paginator.count, 1)
        en_gollo = self.client.get(url, {"tienda": self.gollo.pk}).context[
            "pagina"
        ]
        self.assertEqual(en_gollo.paginator.count, 2)
        self.assertEqual(
            self.client.get(url, {"q": "leche"})
            .context["pagina"]
            .paginator.count,
            3,
        )
        self.assertEqual(
            self.client.get(url, {"q": "salsa"})
            .context["pagina"]
            .paginator.count,
            0,
        )

    def test_el_periodo(self):
        self.cambiar(self.en_walmart, price=800, cuando=hace(45))
        url = reverse("historial_de_precios")
        self.assertEqual(
            self.client.get(url).context["pagina"].paginator.count, 3
        )  # 30 días
        self.assertEqual(
            self.client.get(url, {"periodo": "180"})
            .context["pagina"]
            .paginator.count,
            4,
        )
        self.assertEqual(
            self.client.get(url, {"periodo": "7"})
            .context["pagina"]
            .paginator.count,
            3,
        )

    def test_la_comparativa_de_una_presentacion(self):
        respuesta = self.client.get(
            reverse("historial_de_presentacion", args=["7441001234567"])
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Comparativa en cada actualización")
        self.assertContains(
            respuesta, 'data-historial="historial-datos-7441001234567"'
        )
        filas = list(respuesta.context["pagina"].object_list)
        # Los 3 cambios y los 2 precios iniciales, el más reciente primero.
        self.assertEqual(len(filas), 5)
        self.assertEqual(
            [c.get("final") for c in filas[0]["celdas"]], [900, 1300]
        )
        self.assertEqual(
            [c.get("disponible") for c in filas[0]["celdas"]], [True, False]
        )
        self.assertEqual(filas[-1]["celdas"][1], {"sin_datos": True})
        self.assertContains(respuesta, "Precio al empezar el historial")
        self.assertContains(respuesta, "₡900")  # el mejor precio de hoy

    def test_una_presentacion_que_no_existe(self):
        respuesta = self.client.get(
            reverse("historial_de_presentacion", args=["000"])
        )
        self.assertEqual(respuesta.status_code, 404)

    def test_comparativa_sin_tiendas_repetidas(self):
        columnas, filas = comparativa("7441001234567")
        self.assertEqual([c["nombre"] for c in columnas], ["Walmart", "Gollo"])
        self.assertEqual(filas[0]["cambio"], AGOTADO)


class PreciosVigentesAlMigrarTests(HistorialTestCase):
    def test_la_migracion_guarda_el_precio_vigente_de_cada_tienda(self):
        migracion = importlib.import_module(
            "products.migrations.0007_historial_de_precios"
        )
        editor = SimpleNamespace(connection=connection)
        # Los modelos como los ve la migración (sin las llaves foráneas de
        # prices, que Django no sigue en los modelos managed = False).
        historicos = (
            MigrationLoader(connection)
            .project_state(("products", "0007_historial_de_precios"))
            .apps
        )
        self.assertNotIn(
            "id_store",
            {
                f.name
                for f in historicos.get_model(
                    "products", "Prices"
                )._meta.fields
            },
        )
        Prices.objects.filter(pk=self.en_gollo.pk).update(
            discount=Decimal("0.10"), is_available=False
        )
        migracion.guardar_precios_vigentes(historicos, editor)
        registros = PriceHistory.objects.order_by("store_id")
        self.assertEqual(
            [(r.final_price, r.is_available, r.source) for r in registros],
            [(1000, True, Origen.INICIAL), (1080, False, Origen.INICIAL)],
        )
        self.assertEqual(
            registros[0].recorded_at,
            Prices.objects.get(pk=self.en_walmart.pk).updated_at,
        )
        # Si ya hay historial no se vuelve a llenar.
        migracion.guardar_precios_vigentes(historicos, editor)
        self.assertEqual(PriceHistory.objects.count(), 2)
