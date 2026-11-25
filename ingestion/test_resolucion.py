"""Pruebas de los botones del registro de incidencias para resolver las extracciones fallidas."""

from decimal import Decimal
from unittest import mock

from django.urls import reverse

from accounts.models import User
from products.models import Prices

from .actualizacion import SIN_CAMBIOS, revisar
from .models import Incident, StoreProduct
from .resolucion import codigos_de_la_tienda
from .scrapers import ErrorDescarga, ProductoNoEncontrado
from .test_actualizacion import API_LECHE, GTIN_LECHE, URL_LECHE, PrecioGuardadoTestCase, respuesta_vtex
from .test_scrapers import HttpFalso

CLAVE = "Clave2026segura"
URL_NUEVA = "https://www.walmart.co.cr/leche-entera-dos-pinos-1l/p"
API_NUEVA = "https://www.walmart.co.cr/api/catalog_system/pub/products/search/leche-entera-dos-pinos-1l/p"
CODIGO_DE_LA_TIENDA = "7401006400901"
SIN_RED = mock.patch("ingestion.resolucion.cliente_http", side_effect=AssertionError("no debía descargar nada"))


class ResolucionTestCase(PrecioGuardadoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(email="admin@example.com", password=CLAVE, role="admin")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.fila = self.guardado(precio=1760)

    def incidencia_de(self, respuesta):
        """La incidencia que anota la revisión de cada hora cuando la tienda responde esto."""
        revision = revisar(self.recargar(self.fila), HttpFalso({API_LECHE: respuesta}))
        self.assertIsNotNone(revision.incidencia)
        return revision.incidencia

    def resolver(self, incidencia, accion, http=None, **datos):
        url = reverse("resolver_incidencia", args=[incidencia.pk])
        parche = SIN_RED if http is None else mock.patch("ingestion.resolucion.cliente_http", return_value=http)
        with parche:
            return self.client.post(url, {"accion": accion, **datos}, follow=True)

    def assertResuelta(self, incidencia, nota):
        incidencia.refresh_from_db()
        self.assertEqual(incidencia.status, Incident.Status.RESOLVED)
        self.assertEqual(incidencia.resolved_by, self.admin)
        self.assertIsNotNone(incidencia.resolved_at)
        self.assertIn(nota, incidencia.resolution)

    def assertPendiente(self, incidencia):
        incidencia.refresh_from_db()
        self.assertEqual(incidencia.status, Incident.Status.PENDING)


class CambioDePrecioSospechosoTests(ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(respuesta_vtex(lista=5000, final=4000))

    def test_la_revision_guarda_el_precio_que_leyo(self):
        self.assertEqual(
            self.incidencia.details,
            {"precio_antes": 1760, "precio_lista": 5000, "precio_final": 4000, "disponible": True},
        )

    def test_aceptar_el_precio_nuevo_lo_guarda_sin_volver_a_descargar_la_pagina(self):
        respuesta = self.resolver(self.incidencia, "aceptar_precio")
        fila = self.recargar(self.fila)
        self.assertEqual((fila.price, fila.discount), (5000, Decimal("0.20")))
        self.assertGreater(fila.updated_at, self.hace_tres_dias)
        self.assertResuelta(self.incidencia, "Se aceptó el precio nuevo: ₡4.000.")
        self.assertContains(respuesta, "Se aceptó el precio nuevo: ₡4.000.")

    def test_resuelve_tambien_las_repetidas_del_mismo_precio(self):
        repetida = self.incidencia_de(respuesta_vtex(lista=5000, final=4000))
        respuesta = self.resolver(self.incidencia, "aceptar_precio")
        self.assertResuelta(repetida, "Se aceptó el precio nuevo")
        self.assertContains(respuesta, "También se resolvió 1 incidencia repetida del mismo precio.")

    def test_una_incidencia_anotada_antes_de_guardar_el_precio_vuelve_a_leer_la_pagina(self):
        Incident.objects.filter(pk=self.incidencia.pk).update(details={})
        self.resolver(self.incidencia, "aceptar_precio", http=HttpFalso({API_LECHE: respuesta_vtex(lista=4500, final=4500)}))
        self.assertEqual(self.recargar(self.fila).price, 4500)  # aunque cambie más del 50 %
        self.assertResuelta(self.incidencia, "₡4.500")

    def test_mantener_el_precio_guardado_no_lo_toca(self):
        respuesta = self.resolver(self.incidencia, "descartar")
        self.assertEqual(self.recargar(self.fila).price, 1760)
        self.assertResuelta(self.incidencia, "Se mantuvo el precio guardado.")
        self.assertContains(respuesta, "Se mantuvo el precio guardado.")

    def test_no_se_resuelve_dos_veces(self):
        self.resolver(self.incidencia, "descartar")
        respuesta = self.resolver(self.incidencia, "aceptar_precio")
        self.assertContains(respuesta, "Esta incidencia ya estaba resuelta.")
        self.assertEqual(self.recargar(self.fila).price, 1760)

    def test_si_el_precio_ya_no_existe_lo_avisa(self):
        Prices.objects.filter(pk=self.fila.pk).delete()
        respuesta = self.resolver(self.incidencia, "aceptar_precio")
        self.assertContains(respuesta, "El precio de esta incidencia ya no existe en el catálogo.")
        self.assertPendiente(self.incidencia)


class CodigoDistintoTests(ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(respuesta_vtex(ean=CODIGO_DE_LA_TIENDA, lista=1800, final=1800))

    def test_la_revision_guarda_los_codigos_de_la_tienda(self):
        self.assertEqual(self.incidencia.details, {"codigos": [CODIGO_DE_LA_TIENDA]})

    def test_aceptar_el_codigo_hace_que_la_proxima_revision_lo_reconozca(self):
        respuesta = self.resolver(self.incidencia, "aceptar_codigo")
        producto = StoreProduct.objects.get(url=URL_LECHE)
        self.assertEqual(producto.status, StoreProduct.Status.CONFIRMED)
        self.assertEqual((producto.suggested_gtin, producto.barcodes), (GTIN_LECHE, [CODIGO_DE_LA_TIENDA]))
        self.assertResuelta(self.incidencia, f"Se aceptó el código {CODIGO_DE_LA_TIENDA}")
        self.assertContains(respuesta, "El precio se actualizará en la próxima revisión.")

        revision = revisar(self.recargar(self.fila), HttpFalso({API_LECHE: respuesta_vtex(ean=CODIGO_DE_LA_TIENDA, lista=1760, final=1760)}))
        self.assertEqual((revision.resultado, revision.incidencia), (SIN_CAMBIOS, None))

    def test_agrega_el_codigo_al_producto_de_tienda_que_ya_existia(self):
        StoreProduct.objects.create(url=URL_LECHE, store_name="Walmart", name="Leche", barcodes=["0000000000017"])
        self.resolver(self.incidencia, "aceptar_codigo")
        producto = StoreProduct.objects.get(url=URL_LECHE)
        self.assertEqual(producto.barcodes, ["0000000000017", CODIGO_DE_LA_TIENDA])
        self.assertEqual(producto.status, StoreProduct.Status.CONFIRMED)

    def test_no_lo_acepta_si_la_pagina_ya_es_de_otra_variante(self):
        StoreProduct.objects.create(
            url=URL_LECHE, store_name="Walmart", name="Salsa", status=StoreProduct.Status.CONFIRMED,
            suggested_gtin=self.variante_ketchup.gtin,
        )
        respuesta = self.resolver(self.incidencia, "aceptar_codigo")
        self.assertContains(respuesta, "Esa página ya está vinculada a otra variante del catálogo")
        self.assertPendiente(self.incidencia)

    def test_saca_los_codigos_del_motivo_en_las_incidencias_anteriores(self):
        vieja = Incident(
            kind=Incident.Kind.BARCODE_MISMATCH,
            reason=f"La página es del código 01307605, {CODIGO_DE_LA_TIENDA}, pero el precio guardado es del {GTIN_LECHE}.\n{URL_LECHE}",
        )
        self.assertEqual(codigos_de_la_tienda(vieja), ["01307605", CODIGO_DE_LA_TIENDA])


class VolverARevisarTests(ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(ErrorDescarga("La tienda respondió con el error 503."))

    def test_si_ya_funciona_actualiza_el_precio_y_la_resuelve(self):
        respuesta = self.resolver(self.incidencia, "revisar", http=HttpFalso({API_LECHE: respuesta_vtex(lista=1900, final=1900)}))
        self.assertEqual(self.recargar(self.fila).price, 1900)
        self.assertResuelta(self.incidencia, "Se volvió a revisar y el precio quedó al día.")
        self.assertContains(respuesta, "Se volvió a revisar y el precio quedó al día.")

    def test_si_sigue_fallando_queda_solo_la_incidencia_nueva(self):
        respuesta = self.resolver(self.incidencia, "revisar", http=HttpFalso({API_LECHE: ErrorDescarga("Sin conexión.")}))
        self.assertContains(respuesta, "Sigue fallando: Sin conexión.")
        self.assertResuelta(self.incidencia, "siguió fallando")
        nueva = Incident.objects.get(status=Incident.Status.PENDING)
        self.assertNotEqual(nueva.pk, self.incidencia.pk)
        self.assertEqual(nueva.motivo, "Sin conexión.")

    def test_una_accion_que_no_aplica_a_este_tipo(self):
        respuesta = self.resolver(self.incidencia, "aceptar_precio")
        self.assertContains(respuesta, "Esa acción no aplica a esta incidencia.")
        self.assertPendiente(self.incidencia)


class CambiarEnlaceTests(ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(ProductoNoEncontrado("La tienda ya no tiene este producto en su catálogo."))

    def test_revisa_la_pagina_nueva_y_la_guarda(self):
        http = HttpFalso({API_NUEVA: respuesta_vtex(lista=1800, final=1800)})
        respuesta = self.resolver(self.incidencia, "enlace", http=http, url=URL_NUEVA)
        fila = self.recargar(self.fila)
        self.assertEqual((fila.product_web_url, fila.price, fila.is_available), (URL_NUEVA, 1800, True))
        self.assertResuelta(self.incidencia, "Se cambió el enlace del precio y quedó al día.")
        self.assertContains(respuesta, "Se cambió el enlace del precio y quedó al día.")

    def test_no_la_guarda_si_la_pagina_nueva_tambien_falla(self):
        http = HttpFalso({API_NUEVA: ProductoNoEncontrado("No existe.")})
        respuesta = self.resolver(self.incidencia, "enlace", http=http, url=URL_NUEVA)
        self.assertContains(respuesta, "No se cambió el enlace porque la página nueva falló: No existe.")
        self.assertEqual(self.recargar(self.fila).product_web_url, URL_LECHE)
        self.assertPendiente(self.incidencia)

    def test_rechaza_enlaces_que_no_sirven(self):
        casos = {
            "no es un enlace": "Escriba la dirección completa de la página, con https://.",
            URL_LECHE: "Es el mismo enlace que ya tiene el precio.",
            "https://www.ejemplo.com/leche": "PricePeek no sabe leer las páginas de ese sitio.",
            "https://www.gollo.com/leche": "El enlace nuevo tiene que ser de la misma tienda (walmart.co.cr).",
        }
        for url, aviso in casos.items():
            with self.subTest(url=url):
                self.assertContains(self.resolver(self.incidencia, "enlace", url=url), aviso)
        self.assertPendiente(self.incidencia)

    def test_marcar_como_revisada(self):
        self.resolver(self.incidencia, "descartar")
        self.assertResuelta(self.incidencia, "Se marcó como revisada sin cambios.")


class PermisosYNavegacionTests(ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(ErrorDescarga("Error 503."))
        self.url = reverse("resolver_incidencia", args=[self.incidencia.pk])

    def test_solo_el_administrador_puede_resolver(self):
        cliente = User.objects.create_user(email="cliente@example.com", password=CLAVE)
        self.client.force_login(cliente)
        self.assertEqual(self.client.post(self.url, {"accion": "descartar"}).status_code, 403)
        self.assertPendiente(self.incidencia)

    def test_solo_por_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_los_productos_excluidos_no_se_resuelven_aqui(self):
        excluido = Incident.objects.create(kind=Incident.Kind.INVALID_BARCODE, gtin="ABC", reason="No es un código.")
        url = reverse("resolver_incidencia", args=[excluido.pk])
        self.assertEqual(self.client.post(url, {"accion": "descartar"}).status_code, 404)

    def test_vuelve_a_la_lista_con_sus_filtros(self):
        volver = reverse("incidencias") + "?tipo=download_failed&pagina=1"
        respuesta = self.client.post(self.url, {"accion": "descartar", "volver": volver})
        self.assertRedirects(respuesta, volver, fetch_redirect_response=False)

    def test_no_redirige_fuera_del_registro(self):
        for volver in ("https://malicioso.example/", "//malicioso.example/", reverse("clientes")):
            with self.subTest(volver=volver):
                incidencia = self.incidencia_de(ErrorDescarga("Error 503."))
                url = reverse("resolver_incidencia", args=[incidencia.pk])
                respuesta = self.client.post(url, {"accion": "descartar", "volver": volver})
                self.assertRedirects(respuesta, reverse("incidencias"), fetch_redirect_response=False)


class ListaConBotonesTests(ResolucionTestCase):
    def test_cada_tipo_ofrece_sus_botones(self):
        self.incidencia_de(respuesta_vtex(lista=5000, final=4000))
        respuesta = self.client.get(reverse("incidencias"))
        self.assertContains(respuesta, 'value="aceptar_precio"')
        self.assertContains(respuesta, 'value="descartar"')
        self.assertContains(respuesta, "Mantener el precio guardado")
        self.assertContains(respuesta, 'name="url"')
        self.assertNotContains(respuesta, 'value="aceptar_codigo"')
        self.assertContains(respuesta, "₡1.760")
        self.assertContains(respuesta, "₡4.000")

    def test_codigo_distinto_muestra_los_dos_codigos(self):
        self.incidencia_de(respuesta_vtex(ean=CODIGO_DE_LA_TIENDA))
        respuesta = self.client.get(reverse("incidencias"))
        self.assertContains(respuesta, 'value="aceptar_codigo"')
        self.assertContains(respuesta, CODIGO_DE_LA_TIENDA)
        self.assertNotContains(respuesta, 'value="aceptar_precio"')

    def test_las_resueltas_se_ven_aparte_y_sin_botones(self):
        incidencia = self.incidencia_de(ErrorDescarga("Error 503."))
        self.resolver(incidencia, "descartar")
        pendientes = self.client.get(reverse("incidencias"))
        self.assertContains(pendientes, "No hay extracciones fallidas pendientes de revisar.")
        self.assertEqual(pendientes.context["totales"]["fallidas"], 0)

        resueltas = self.client.get(reverse("incidencias"), {"estado": "resueltas"})
        self.assertContains(resueltas, "Error 503.")
        self.assertContains(resueltas, "Se marcó como revisada sin cambios.")
        self.assertContains(resueltas, "admin@example.com")
        self.assertNotContains(resueltas, 'name="accion"')

        self.assertContains(self.client.get(reverse("incidencias"), {"estado": "todas"}), "Error 503.")
