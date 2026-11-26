"""Pruebas automatizadas de test_incidencias para la aplicación ingestion."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from products.tests import CatalogoTestCase

from .models import Incident
from .views import INCIDENCIAS_POR_PAGINA

CLAVE = "Clave2026segura"


def incidencia(
    kind,
    producto,
    tienda="Gollo",
    gtin="7441234567890",
    motivo="Motivo de prueba.",
    hace=None,
):
    creada = Incident.objects.create(
        kind=kind,
        store_name=tienda,
        product_name=producto,
        gtin=gtin,
        reason=motivo,
    )
    if (
        hace is not None
    ):  # created_at es auto_now_add: se cambia después de crearla
        Incident.objects.filter(pk=creada.pk).update(
            created_at=timezone.now() - hace
        )
    return creada


class RegistroDeIncidenciasBase(TestCase):
    url = reverse("incidencias")

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )
        cls.empresa = User.objects.create_user(
            email="empresa@example.com", password=CLAVE, role="enterprise"
        )
        cls.cliente = User.objects.create_user(
            email="cliente@example.com", password=CLAVE
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def consultar(self, **filtros):
        return self.client.get(self.url, filtros)


class AccesoTests(RegistroDeIncidenciasBase):
    def test_solo_el_administrador_puede_consultarlo(self):
        self.client.logout()
        respuesta = self.consultar()
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
        for usuario in (self.cliente, self.empresa):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                self.assertEqual(self.consultar().status_code, 403)


class EnlaceDesdeElPanelTests(
    CatalogoTestCase
):  # el inicio muestra productos del catálogo
    url = reverse("incidencias")

    def test_se_llega_desde_el_panel_de_administracion(self):
        self.client.force_login(
            User.objects.create_user(
                email="admin@example.com", password=CLAVE, role="admin"
            )
        )
        respuesta = self.client.get(reverse("inicio_administrador"))
        self.assertContains(respuesta, f'href="{self.url}"')
        self.assertContains(respuesta, "Incidencias de datos")

    def test_los_demas_roles_no_ven_el_enlace(self):
        self.client.force_login(
            User.objects.create_user(
                email="cliente@example.com", password=CLAVE
            )
        )
        self.assertNotContains(
            self.client.get(reverse("inicio_cliente")), f'href="{self.url}"'
        )


class ExtraccionesFallidasTests(RegistroDeIncidenciasBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        incidencia(
            Incident.Kind.DOWNLOAD_FAILED,
            "Cafetera Black+Decker",
            motivo="Error 503 al descargar.",
        )
        incidencia(
            Incident.Kind.PRICE_NOT_FOUND,
            "Leche entera 1L",
            tienda="Walmart\n",
        )
        incidencia(
            Incident.Kind.SUSPICIOUS_PRICE,
            "Refrigeradora Samsung",
            tienda="Monge",
            hace=timedelta(days=10),
        )
        incidencia(
            Incident.Kind.INVALID_BARCODE, "Llanta sin GTIN", gtin="ABC123"
        )

    def test_por_defecto_muestra_las_extracciones_fallidas(self):
        respuesta = self.consultar()
        self.assertEqual(respuesta.context["registro"], "fallidas")
        for producto in (
            "Cafetera Black+Decker",
            "Leche entera 1L",
            "Refrigeradora Samsung",
        ):
            self.assertContains(respuesta, producto)
        self.assertNotContains(respuesta, "Llanta sin GTIN")
        self.assertContains(respuesta, "3 incidencias")
        self.assertEqual(
            (
                respuesta.context["totales"]["fallidas"],
                respuesta.context["totales"]["excluidos"],
            ),
            (3, 1),
        )

    def test_muestra_el_tipo_el_comercio_y_el_motivo(self):
        respuesta = self.consultar()
        self.assertContains(respuesta, "No se pudo descargar la página")
        self.assertContains(respuesta, "Cambio de precio sospechoso")
        self.assertContains(respuesta, "Gollo")
        self.assertContains(respuesta, "Error 503 al descargar.")

    def test_las_mas_recientes_aparecen_primero(self):
        contenido = self.consultar().content.decode()
        self.assertLess(
            contenido.index("Leche entera 1L"),
            contenido.index("Refrigeradora Samsung"),
        )

    def test_filtra_por_tipo(self):
        respuesta = self.consultar(tipo=Incident.Kind.DOWNLOAD_FAILED)
        self.assertContains(respuesta, "Cafetera Black+Decker")
        self.assertNotContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "1 incidencia")

    def test_un_tipo_de_otro_registro_no_filtra(self):
        respuesta = self.consultar(tipo=Incident.Kind.INVALID_BARCODE)
        self.assertEqual(respuesta.context["tipo"], "")
        self.assertNotContains(respuesta, "Llanta sin GTIN")
        self.assertContains(respuesta, "3 incidencias")

    def test_filtra_por_comercio_aunque_el_nombre_traiga_un_salto_de_linea(
        self,
    ):
        self.assertIn("Walmart", self.consultar().context["comercios"])
        respuesta = self.consultar(comercio="Walmart")
        self.assertContains(respuesta, "Leche entera 1L")
        self.assertNotContains(respuesta, "Cafetera Black+Decker")

    def test_un_comercio_desconocido_no_filtra(self):
        self.assertContains(
            self.consultar(comercio="Tienda inventada"), "3 incidencias"
        )

    def test_filtra_por_periodo(self):
        respuesta = self.consultar(periodo="7d")
        self.assertNotContains(respuesta, "Refrigeradora Samsung")
        self.assertContains(respuesta, "2 incidencias")
        self.assertContains(
            self.consultar(periodo="30d"), "Refrigeradora Samsung"
        )

    def test_busca_por_producto_codigo_o_motivo(self):
        for busqueda in ("cafetera", "503"):
            with self.subTest(busqueda=busqueda):
                respuesta = self.consultar(q=busqueda)
                self.assertContains(respuesta, "Cafetera Black+Decker")
                self.assertNotContains(respuesta, "Leche entera 1L")

    def test_avisa_cuando_ningun_resultado_coincide(self):
        respuesta = self.consultar(q="no existe")
        self.assertContains(
            respuesta, "No hay incidencias que coincidan con los filtros."
        )
        self.assertContains(respuesta, "Limpiar filtros")


class ProductosExcluidosTests(RegistroDeIncidenciasBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        incidencia(
            Incident.Kind.INVALID_BARCODE,
            "Llanta sin GTIN",
            gtin="ABC123",
            motivo="El código contiene caracteres que no son dígitos.",
        )
        incidencia(
            Incident.Kind.INVALID_BARCODE,
            "Galletas Peri",
            tienda="Peri",
            gtin="",
            motivo="No trae código.",
        )
        incidencia(Incident.Kind.PRODUCT_NOT_FOUND, "Leche entera 1L")

    def test_muestra_solo_los_productos_excluidos_por_codigo_invalido(self):
        respuesta = self.consultar(registro="excluidos")
        self.assertContains(respuesta, "Llanta sin GTIN")
        self.assertContains(respuesta, "Galletas Peri")
        self.assertNotContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "2 incidencias")

    def test_muestra_el_codigo_recibido_y_por_que_no_es_valido(self):
        respuesta = self.consultar(registro="excluidos")
        self.assertContains(respuesta, "ABC123")
        self.assertContains(
            respuesta, "El código contiene caracteres que no son dígitos."
        )
        self.assertContains(
            respuesta, "ninguno"
        )  # Galletas Peri no traía código

    def test_no_ofrece_filtrar_por_tipo(self):
        self.assertNotContains(
            self.consultar(registro="excluidos"), 'name="tipo"'
        )
        self.assertContains(self.consultar(registro="fallidas"), 'name="tipo"')

    def test_los_filtros_se_aplican_dentro_del_registro(self):
        respuesta = self.consultar(registro="excluidos", comercio="Peri")
        self.assertContains(respuesta, "Galletas Peri")
        self.assertNotContains(respuesta, "Llanta sin GTIN")
        self.assertContains(respuesta, 'name="registro" value="excluidos"')

    def test_sin_productos_excluidos(self):
        Incident.objects.filter(kind=Incident.Kind.INVALID_BARCODE).delete()
        respuesta = self.consultar(registro="excluidos")
        self.assertContains(
            respuesta,
            "No se ha excluido ningún producto por código de barras inválido.",
        )


class EnlaceALaTiendaTests(RegistroDeIncidenciasBase):
    def test_separa_la_pagina_de_la_tienda_del_motivo(self):
        con_enlace = Incident(
            reason="El precio no aparece.\nhttps://www.gollo.com/cafetera"
        )
        self.assertEqual(con_enlace.motivo, "El precio no aparece.")
        self.assertEqual(con_enlace.enlace, "https://www.gollo.com/cafetera")
        sin_enlace = Incident(
            reason="El código no tiene 8, 12, 13 ni 14 dígitos."
        )
        self.assertEqual(
            sin_enlace.motivo, "El código no tiene 8, 12, 13 ni 14 dígitos."
        )
        self.assertEqual(sin_enlace.enlace, "")

    def test_no_trata_como_enlace_algo_que_no_es_una_direccion_web(self):
        incidencia_ = Incident(reason="Motivo.\njavascript:alert(1)")
        self.assertEqual(incidencia_.enlace, "")
        self.assertEqual(incidencia_.motivo, "Motivo.\njavascript:alert(1)")

    def test_enlaza_la_pagina_donde_ocurrio(self):
        incidencia(
            Incident.Kind.PRICE_NOT_FOUND,
            "Cafetera",
            motivo="El precio no aparece.\nhttps://www.gollo.com/cafetera",
        )
        respuesta = self.consultar()
        self.assertContains(respuesta, 'href="https://www.gollo.com/cafetera"')
        self.assertContains(respuesta, "Ver la página en la tienda")


class PaginacionTests(RegistroDeIncidenciasBase):
    def test_pagina_los_resultados_sin_perder_el_registro(self):
        for numero in range(INCIDENCIAS_POR_PAGINA + 1):
            incidencia(
                Incident.Kind.INVALID_BARCODE,
                f"Producto {numero:02d}",
                gtin=str(numero),
            )
        respuesta = self.consultar(registro="excluidos")
        self.assertEqual(
            len(respuesta.context["pagina"].object_list),
            INCIDENCIAS_POR_PAGINA,
        )
        self.assertContains(respuesta, "Página 1 de 2")
        self.assertContains(respuesta, "?registro=excluidos&amp;pagina=2")
        self.assertEqual(
            len(
                self.consultar(registro="excluidos", pagina=2)
                .context["pagina"]
                .object_list
            ),
            1,
        )


class TraduccionTests(RegistroDeIncidenciasBase):
    def test_se_muestra_en_ingles(self):
        incidencia(Incident.Kind.DOWNLOAD_FAILED, "Cafetera")
        self.client.cookies["django_language"] = "en"
        respuesta = self.consultar()
        self.assertContains(respuesta, "Failed extractions")
        self.assertContains(respuesta, "The page could not be downloaded")
        self.assertContains(respuesta, "1 incident")
