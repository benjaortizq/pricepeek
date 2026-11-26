"""Pruebas automatizadas de test_reportes para la aplicación reviews."""

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ReviewDeletion, ReviewPhoto, ReviewReport, Reviews
from products.models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
    Stores,
)

# Las fotos se guardan en memoria para que las pruebas no toquen el Storage de Supabase.
ALMACENAMIENTO_EN_MEMORIA = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


class ReportesBase(TestCase):
    modelos_sin_migracion = [
        Brands,
        Categories,
        Currencies,
        Stores,
        Products,
        ProductVariants,
        ProductImages,
        Prices,  # la página del producto también muestra los precios
        Reviews,
    ]

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for modelo in cls.modelos_sin_migracion:
                editor.create_model(modelo)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.modelos_sin_migracion):
                editor.delete_model(modelo)

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        marca = Brands.objects.create(
            name="Marca", slug="marca", created_at=now, updated_at=now
        )
        categoria = Categories.objects.create(
            name="Categoría", created_at=now, updated_at=now
        )
        cls.product = Products.objects.create(
            name="Producto",
            brand=marca,
            category=categoria,
            created_at=now,
            updated_at=now,
        )
        cls.variant = ProductVariants.objects.create(
            product=cls.product,
            gtin="1234567890123",
            name="Variante",
            created_at=now,
            updated_at=now,
        )
        usuarios = get_user_model().objects
        cls.autor = usuarios.create_user(
            email="autor@example.com", password="Clave2026segura"
        )
        cls.reportante = usuarios.create_user(
            email="reporta@example.com", password="Clave2026segura"
        )
        cls.otro_cliente = usuarios.create_user(
            email="otro@example.com", password="Clave2026segura"
        )
        cls.admin = usuarios.create_user(
            email="admin@example.com", password="Clave2026segura", role="admin"
        )
        cls.empresa = usuarios.create_user(
            email="empresa@example.com",
            password="Clave2026segura",
            role="enterprise",
        )
        cls.resena = Reviews.objects.create(
            user_id=cls.autor.pk,
            variant=cls.variant,
            content="Contenido ofensivo.",
            score=1,
            created_at=now,
            updated_at=now,
        )

    def reportar(self, usuario, motivo="Es ofensiva.", review_id=None):
        self.client.force_login(usuario)
        return self.client.post(
            reverse(
                "reportar_resena",
                kwargs={"review_id": review_id or self.resena.pk},
            ),
            {"reason": motivo},
            follow=True,
        )

    def crear_reporte(self, reportante=None, motivo="Es ofensiva."):
        return ReviewReport.objects.create(
            review_id=self.resena.pk,
            reporter=reportante or self.reportante,
            reason=motivo,
        )


class ReportarResenaTests(ReportesBase):
    def test_cliente_reporta_una_resena_con_motivo(self):
        respuesta = self.reportar(self.reportante, "Insulta a otros usuarios.")
        self.assertRedirects(
            respuesta,
            reverse("detalle_producto", kwargs={"pk": self.product.pk}),
        )
        self.assertContains(respuesta, "Su reporte fue enviado")
        reporte = ReviewReport.objects.get()
        self.assertEqual(reporte.review_id, self.resena.pk)
        self.assertEqual(reporte.review_author, self.autor)
        self.assertEqual(reporte.reporter, self.reportante)
        self.assertEqual(reporte.reason, "Insulta a otros usuarios.")
        self.assertEqual(reporte.status, ReviewReport.Status.PENDING)

    def test_el_motivo_es_obligatorio(self):
        for motivo in ["", "   "]:
            with self.subTest(motivo=motivo):
                respuesta = self.reportar(self.reportante, motivo)
                self.assertContains(respuesta, "Indique el motivo del reporte")
                self.assertEqual(ReviewReport.objects.count(), 0)

    def test_rechaza_un_motivo_de_mas_de_500_caracteres(self):
        respuesta = self.reportar(self.reportante, "a" * 501)
        self.assertContains(respuesta, "Indique el motivo del reporte")
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_un_cliente_solo_puede_reportar_una_vez_la_misma_resena(self):
        self.reportar(self.reportante)
        respuesta = self.reportar(self.reportante, "Otra vez.")
        self.assertContains(respuesta, "Usted ya reportó esta reseña")
        self.assertEqual(ReviewReport.objects.count(), 1)
        self.assertEqual(ReviewReport.objects.get().reason, "Es ofensiva.")

    def test_otro_cliente_si_puede_reportar_la_misma_resena(self):
        self.reportar(self.reportante)
        self.reportar(self.otro_cliente)
        self.assertEqual(
            ReviewReport.objects.filter(review_id=self.resena.pk).count(), 2
        )

    def test_no_se_puede_reportar_la_propia_resena(self):
        respuesta = self.reportar(self.autor)
        self.assertContains(respuesta, "No puede reportar su propia reseña")
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_visitante_es_enviado_a_iniciar_sesion(self):
        url = reverse("reportar_resena", kwargs={"review_id": self.resena.pk})
        respuesta = self.client.post(url, {"reason": "Ofensiva."})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_empresa_y_administrador_no_pueden_reportar(self):
        for usuario in (self.empresa, self.admin):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                url = reverse(
                    "reportar_resena", kwargs={"review_id": self.resena.pk}
                )
                self.assertEqual(
                    self.client.post(url, {"reason": "Ofensiva."}).status_code,
                    403,
                )
        self.assertEqual(ReviewReport.objects.count(), 0)

    def test_solo_acepta_post(self):
        self.client.force_login(self.reportante)
        url = reverse("reportar_resena", kwargs={"review_id": self.resena.pk})
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_resena_inexistente_da_404(self):
        self.client.force_login(self.reportante)
        url = reverse("reportar_resena", kwargs={"review_id": 99999})
        self.assertEqual(
            self.client.post(url, {"reason": "Ofensiva."}).status_code, 404
        )


class BotonDeReporteEnElProductoTests(ReportesBase):
    def setUp(self):
        self.url = reverse("detalle_producto", kwargs={"pk": self.product.pk})

    def test_otro_cliente_ve_la_opcion_de_reportar(self):
        self.client.force_login(self.reportante)
        self.assertContains(
            self.client.get(self.url), "Reportar como inapropiada"
        )

    def test_el_cliente_que_ya_reporto_ve_que_ya_lo_hizo(self):
        self.crear_reporte()
        self.client.force_login(self.reportante)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Ya reportaste esta reseña")
        self.assertNotContains(respuesta, "Reportar como inapropiada")

    def test_el_autor_no_ve_la_opcion_ni_quien_lo_reporto(self):
        self.crear_reporte()
        self.client.force_login(self.autor)
        respuesta = self.client.get(self.url)
        self.assertNotContains(respuesta, "Reportar como inapropiada")
        self.assertNotContains(respuesta, "Ya reportaste")
        self.assertNotContains(respuesta, self.reportante.email)  # RNF-32

    def test_visitante_y_otros_roles_no_ven_la_opcion(self):
        self.assertNotContains(
            self.client.get(self.url), "Reportar como inapropiada"
        )
        for usuario in (self.empresa, self.admin):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                self.assertNotContains(
                    self.client.get(self.url), "Reportar como inapropiada"
                )


class ListaDeResenasReportadasTests(ReportesBase):
    def setUp(self):
        self.url = reverse("resenas_reportadas")

    def test_solo_el_administrador_puede_verla(self):
        self.assertEqual(
            self.client.get(self.url).status_code, 302
        )  # visitante
        for usuario in (
            self.reportante,
            self.otro_cliente,
            self.autor,
            self.empresa,
        ):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                respuesta = self.client.get(self.url)
                self.assertEqual(respuesta.status_code, 403)
                self.assertNotContains(
                    respuesta, self.reportante.email, status_code=403
                )

    def test_muestra_la_resena_reportada_con_sus_motivos_y_quien_reporto(self):
        self.crear_reporte(self.reportante, "Insulta a otros usuarios.")
        self.crear_reporte(self.otro_cliente, "Es spam.")
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Contenido ofensivo.")
        self.assertContains(respuesta, "Insulta a otros usuarios.")
        self.assertContains(respuesta, "Es spam.")
        self.assertContains(
            respuesta, "reporta@example.com"
        )  # solo el administrador lo ve
        self.assertContains(respuesta, "2 reportes")

    def test_no_muestra_resenas_sin_reportes_ni_reportes_ya_resueltos(self):
        ahora = timezone.now()
        otra = Reviews.objects.create(
            user_id=self.otro_cliente.pk,
            variant=self.variant,
            content="Reseña sin reportes.",
            score=5,
            created_at=ahora,
            updated_at=ahora,
        )
        reporte = self.crear_reporte()
        reporte.status = ReviewReport.Status.KEPT
        reporte.save()
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertNotContains(respuesta, "Contenido ofensivo.")
        self.assertNotContains(respuesta, otra.content)
        self.assertContains(respuesta, "No hay reseñas reportadas pendientes")

    def test_muestra_cuantas_resenas_del_autor_ya_se_eliminaron(self):
        self.crear_reporte()
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Sin reseñas eliminadas antes")
        url_historial = reverse(
            "detalle_cliente", kwargs={"pk": self.autor.pk}
        )
        self.assertContains(respuesta, url_historial)

        for review_id in (
            900,
            901,
        ):  # reseñas del mismo autor eliminadas en el pasado
            ReviewDeletion.objects.create(
                review_id=review_id,
                author=self.autor,
                policy=ReviewDeletion.Policy.PROMOTIONAL,
                reason="Spam.",
            )
        self.assertContains(
            self.client.get(self.url), "Le eliminaron 2 reseñas antes"
        )

    def test_una_resena_que_ya_no_existe_no_rompe_la_lista(self):
        self.crear_reporte()
        Reviews.objects.filter(pk=self.resena.pk).delete()
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "No hay reseñas reportadas pendientes")


class ModerarResenaTests(ReportesBase):
    def setUp(self):
        self.url = reverse(
            "moderar_resena", kwargs={"review_id": self.resena.pk}
        )
        self.crear_reporte(self.reportante)
        self.crear_reporte(self.otro_cliente, "Es spam.")
        self.client.force_login(self.admin)

    def decidir(self, **datos):
        if datos.get("action") == "delete":
            datos.setdefault("policy", ReviewDeletion.Policy.DISRESPECTFUL)
        return self.client.post(self.url, datos, follow=True)

    def test_eliminar_exige_la_politica_que_incumple(self):
        respuesta = self.decidir(
            action="delete", note="Lenguaje ofensivo.", policy=""
        )
        self.assertContains(
            respuesta, "Elija la política de uso que incumple la reseña."
        )
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())
        self.assertFalse(ReviewDeletion.objects.exists())

    def test_eliminar_registra_la_politica_y_la_razon(self):
        self.decidir(
            action="delete",
            note="Lenguaje ofensivo.",
            policy=ReviewDeletion.Policy.DEFAMATORY,
        )
        registro = ReviewDeletion.objects.get()
        self.assertEqual(
            (
                registro.review_id,
                registro.author,
                registro.deleted_by,
                registro.policy,
                registro.reason,
                registro.reports,
            ),
            (
                self.resena.pk,
                self.autor,
                self.admin,
                ReviewDeletion.Policy.DEFAMATORY,
                "Lenguaje ofensivo.",
                2,
            ),
        )
        self.assertEqual(
            (registro.content, registro.score), ("Contenido ofensivo.", 1)
        )

    def test_mantener_deja_la_resena_y_resuelve_los_reportes(self):
        respuesta = self.decidir(
            action="keep", note="No incumple las políticas."
        )
        self.assertRedirects(respuesta, reverse("resenas_reportadas"))
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())
        for reporte in ReviewReport.objects.all():
            self.assertEqual(reporte.status, ReviewReport.Status.KEPT)
            self.assertEqual(reporte.resolved_by, self.admin)
            self.assertIsNotNone(reporte.resolved_at)
            self.assertEqual(
                reporte.resolution_note, "No incumple las políticas."
            )

    def test_eliminar_borra_la_resena_y_resuelve_todos_sus_reportes(self):
        respuesta = self.decidir(action="delete", note="Lenguaje ofensivo.")
        self.assertContains(respuesta, "Reseña eliminada")
        self.assertFalse(Reviews.objects.filter(pk=self.resena.pk).exists())
        reportes = ReviewReport.objects.all()
        self.assertEqual(reportes.count(), 2)
        for reporte in reportes:
            self.assertEqual(reporte.status, ReviewReport.Status.DELETED)
            self.assertEqual(reporte.resolution_note, "Lenguaje ofensivo.")
        self.assertTrue(
            get_user_model().objects.get(pk=self.autor.pk).is_active
        )

    def test_eliminar_exige_el_motivo(self):
        respuesta = self.decidir(action="delete", note="")
        self.assertContains(respuesta, "Indique el motivo de la eliminación")
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())
        self.assertEqual(
            ReviewReport.objects.filter(
                status=ReviewReport.Status.PENDING
            ).count(),
            2,
        )

    def test_eliminar_y_suspender_desactiva_la_cuenta_del_autor(self):
        respuesta = self.decidir(
            action="delete", note="Reiterado.", suspend="on"
        )
        self.assertContains(respuesta, "La cuenta del autor fue suspendida")
        autor = get_user_model().objects.get(pk=self.autor.pk)
        self.assertFalse(autor.is_active)
        self.assertEqual(autor.suspension_reason, "Reiterado.")
        self.assertEqual(autor.suspended_by, self.admin)
        self.assertIsNotNone(autor.suspended_at)
        self.assertFalse(
            self.client.login(
                email="autor@example.com", password="Clave2026segura"
            )
        )

    def test_la_resena_eliminada_cuenta_como_infraccion_del_autor(self):
        # Reportes creados antes de que se guardara el autor: se completa al resolverlos.
        ReviewReport.objects.update(review_author=None)
        self.decidir(action="delete", note="Lenguaje ofensivo.")
        self.assertEqual(
            ReviewReport.objects.filter(
                review_author=self.autor, status=ReviewReport.Status.DELETED
            ).count(),
            2,
        )
        respuesta = self.client.get(
            reverse("detalle_cliente", kwargs={"pk": self.autor.pk})
        )
        self.assertContains(
            respuesta, "1 reseña de este cliente fue eliminada"
        )
        self.assertContains(respuesta, "Lenguaje ofensivo.")

    def test_suspender_solo_aplica_cuando_se_elimina(self):
        self.decidir(action="keep", suspend="on")
        self.assertTrue(
            get_user_model().objects.get(pk=self.autor.pk).is_active
        )

    def test_nunca_suspende_cuentas_que_no_son_de_cliente(self):
        ahora = timezone.now()
        resena = Reviews.objects.create(
            user_id=self.empresa.pk,
            variant=self.variant,
            content="De empresa.",
            score=3,
            created_at=ahora,
            updated_at=ahora,
        )
        ReviewReport.objects.create(
            review_id=resena.pk, reporter=self.reportante, reason="Spam."
        )
        url = reverse("moderar_resena", kwargs={"review_id": resena.pk})
        self.client.post(
            url,
            {
                "action": "delete",
                "note": "Spam.",
                "policy": "promocional",
                "suspend": "on",
            },
        )
        self.assertFalse(Reviews.objects.filter(pk=resena.pk).exists())
        self.assertTrue(
            get_user_model().objects.get(pk=self.empresa.pk).is_active
        )

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_eliminar_tambien_borra_la_foto_de_la_resena(self):
        foto = ReviewPhoto(review_id=self.resena.pk)
        foto.image.save("foto.png", ContentFile(b"contenido"), save=True)
        nombre = foto.image.name
        self.assertTrue(default_storage.exists(nombre))
        self.decidir(action="delete", note="Ofensiva.")
        self.assertFalse(
            ReviewPhoto.objects.filter(review_id=self.resena.pk).exists()
        )
        self.assertFalse(default_storage.exists(nombre))

    def test_no_se_puede_moderar_una_resena_sin_reportes_pendientes(self):
        ahora = timezone.now()
        sin_reportes = Reviews.objects.create(
            user_id=self.otro_cliente.pk,
            variant=self.variant,
            content="Sin reportes.",
            score=4,
            created_at=ahora,
            updated_at=ahora,
        )
        url = reverse("moderar_resena", kwargs={"review_id": sin_reportes.pk})
        respuesta = self.client.post(
            url, {"action": "delete", "note": "Prueba."}, follow=True
        )
        self.assertContains(respuesta, "ya no tiene reportes pendientes")
        self.assertTrue(Reviews.objects.filter(pk=sin_reportes.pk).exists())

    def test_solo_el_administrador_puede_moderar(self):
        for usuario in (self.reportante, self.empresa):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                respuesta = self.client.post(
                    self.url, {"action": "delete", "note": "x"}
                )
                self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_si_el_cliente_borra_su_cuenta_se_borran_sus_reportes(self):
        self.reportante.delete()
        self.assertEqual(ReviewReport.objects.count(), 1)
