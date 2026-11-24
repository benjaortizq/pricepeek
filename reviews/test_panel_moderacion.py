"""Pruebas del panel de moderación (templates/panel/): resumen, barra lateral y reseñas reportadas."""

from django.urls import reverse
from django.utils import timezone

from core.templatetags.panel import estrellas, pendientes_del_panel
from core.translations import translate_text
from ingestion.models import Incident

from .models import ReviewReport, Reviews
from .test_reportes import ReportesBase


class PanelBase(ReportesBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def incidencia(self, producto, kind=Incident.Kind.DOWNLOAD_FAILED, **datos):
        return Incident.objects.create(
            kind=kind, store_name="Gollo", product_name=producto, gtin="7441001234567", reason="Error 503.", **datos
        )

    def otra_resena(self, contenido="Otra reseña."):
        ahora = timezone.now()
        return Reviews.objects.create(
            user_id=self.otro_cliente.pk, variant=self.variant, content=contenido, score=4, created_at=ahora, updated_at=ahora
        )


class ResumenDelPanelTests(PanelBase):
    url = reverse("inicio_administrador")

    def test_junta_en_una_cola_las_resenas_y_las_extracciones_pendientes(self):
        self.crear_reporte(motivo="Insulta a otros usuarios.")
        pendiente = self.incidencia("Cafetera pendiente")
        self.incidencia("Cafetera resuelta", status=Incident.Status.RESOLVED)
        self.incidencia("Llanta sin código", kind=Incident.Kind.INVALID_BARCODE)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Centro de Moderación y Control de Calidad")
        self.assertContains(respuesta, f"#REV-{self.resena.pk}")
        self.assertContains(respuesta, "Insulta a otros usuarios.")
        self.assertContains(respuesta, f"#INC-{pendiente.pk}")
        self.assertNotContains(respuesta, "Cafetera resuelta")
        self.assertNotContains(respuesta, "Llanta sin código")
        self.assertEqual(respuesta.context["en_la_cola"], 2)

    def test_las_pestanas_separan_la_cola(self):
        self.crear_reporte()
        incidencia = self.incidencia("Cafetera pendiente")
        datos = self.client.get(self.url, {"cola": "datos"})
        self.assertContains(datos, f"#INC-{incidencia.pk}")
        self.assertNotContains(datos, f"#REV-{self.resena.pk}")
        resenas = self.client.get(self.url, {"cola": "resenas"})
        self.assertContains(resenas, f"#REV-{self.resena.pk}")
        self.assertNotContains(resenas, f"#INC-{incidencia.pk}")

    def test_sin_pendientes(self):
        self.assertContains(self.client.get(self.url), "No hay casos pendientes de revisión.")

    def test_solo_el_administrador(self):
        self.client.force_login(self.reportante)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_el_panel_lleva_al_administrador_al_resumen(self):
        self.assertRedirects(self.client.get(reverse("panel")), self.url)


class BarraLateralTests(PanelBase):
    def test_cuenta_las_resenas_y_las_extracciones_que_esperan_revision(self):
        self.crear_reporte(self.reportante)
        self.crear_reporte(self.otro_cliente)  # la misma reseña: cuenta una vez
        self.incidencia("Cafetera")
        self.incidencia("Resuelta", status=Incident.Status.RESOLVED)
        self.incidencia("Sin código", kind=Incident.Kind.INVALID_BARCODE)
        self.assertEqual(pendientes_del_panel(), {"resenas": 1, "incidencias": 1, "ejecuciones": 0})

    def test_enlaza_las_pantallas_del_panel(self):
        respuesta = self.client.get(reverse("clientes"))
        for nombre in ("inicio_administrador", "clientes", "resenas_reportadas", "incidencias"):
            self.assertContains(respuesta, f'href="{reverse(nombre)}"')

    def test_estrellas(self):
        self.assertEqual(estrellas(3), "★★★☆☆")
        self.assertEqual(estrellas(None), "")


class ResenasReportadasEnElPanelTests(PanelBase):
    url = reverse("resenas_reportadas")

    def test_la_primera_de_la_cola_queda_en_el_panel_de_inspeccion(self):
        self.crear_reporte()
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context["seleccionado"]["resena"].pk, self.resena.pk)
        self.assertContains(respuesta, 'id="inspeccion"')

    def test_inspeccionar_elige_otra_resena(self):
        self.crear_reporte()
        otra = self.otra_resena()
        ReviewReport.objects.create(review_id=otra.pk, reporter=self.reportante, reason="Es spam.")
        respuesta = self.client.get(self.url, {"revisar": otra.pk})
        self.assertEqual(respuesta.context["seleccionado"]["resena"].pk, otra.pk)

    def test_la_ventana_para_eliminar_pide_el_motivo_y_ofrece_suspender(self):
        self.crear_reporte()
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, f'id="eliminar-{self.resena.pk}"')
        self.assertContains(respuesta, f'href="#eliminar-{self.resena.pk}"')
        self.assertContains(respuesta, 'name="suspend"')
        self.assertContains(respuesta, "¿Eliminar esta reseña definitivamente?")

    def test_pestana_de_autores_reiterados(self):
        self.crear_reporte()
        self.assertNotContains(self.client.get(self.url, {"filtro": "reiterados"}), f"#REV-{self.resena.pk}")
        for review_id in (900, 901):
            ReviewReport.objects.create(
                review_id=review_id, reporter=self.otro_cliente, review_author=self.autor,
                reason="Spam.", status=ReviewReport.Status.DELETED,
            )
        self.assertContains(self.client.get(self.url, {"filtro": "reiterados"}), f"#REV-{self.resena.pk}")

    def test_pestana_con_foto_sin_resultados(self):
        self.crear_reporte()
        respuesta = self.client.get(self.url, {"filtro": "con-foto"})
        self.assertContains(respuesta, "No hay reseñas reportadas con este filtro.")

    def test_tarjetas_con_lo_que_espera_revision(self):
        self.crear_reporte(self.reportante)
        self.crear_reporte(self.otro_cliente)
        tarjeta = self.client.get(self.url).context["kpis"][0]
        self.assertEqual((tarjeta["valor"], tarjeta["pie_izq"]), (1, "2 reportes pendientes"))


class PanelEnInglesTests(PanelBase):
    def test_las_pantallas_del_panel_se_traducen(self):
        self.crear_reporte()
        self.incidencia("Cafetera")
        self.client.cookies["django_language"] = "en"
        esperado = {
            "inicio_administrador": "Moderation and Quality Control Center",
            "resenas_reportadas": "Review Moderation and Audit",
            "clientes": "Registered customers",
            "incidencias": "Prices to confirm",
        }
        for nombre, texto in esperado.items():
            with self.subTest(pantalla=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertContains(respuesta, texto)
                self.assertContains(respuesta, "CR Moderation Panel")


    def test_el_historial_del_cliente_y_el_resultado_de_las_ejecuciones(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.client.get(reverse("detalle_cliente", args=[self.otro_cliente.pk]))
        self.assertContains(respuesta, "This customer has no reviews deleted by moderation.")
        self.assertContains(respuesta, "For example: repeatedly posted offensive reviews.")
        self.assertNotContains(respuesta, "Por ejemplo")
        resumen = "120 revisados · 3 actualizados · 117 sin cambios · 0 con fallo · 0 incidencias"
        self.assertEqual(
            translate_text(resumen, language="en"),
            "120 checked · 3 updated · 117 unchanged · 0 failed · 0 incidents",
        )


class ElAutorBorraSuResenaTests(PanelBase):
    def test_sus_reportes_pendientes_salen_de_la_cola(self):
        self.crear_reporte(self.reportante)
        resuelto = ReviewReport.objects.create(
            review_id=self.resena.pk, reporter=self.otro_cliente, reason="Spam.", status=ReviewReport.Status.KEPT
        )
        self.client.force_login(self.autor)
        self.client.post(reverse("eliminar_resena", kwargs={"pk": self.resena.pk}))
        self.assertFalse(Reviews.objects.filter(pk=self.resena.pk).exists())
        self.assertEqual(list(ReviewReport.objects.all()), [resuelto])
        self.assertEqual(pendientes_del_panel()["resenas"], 0)
