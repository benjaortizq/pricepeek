"""Pruebas de «Todas las reseñas» y de la eliminación por incumplir las políticas de uso."""

import importlib

from django.apps import apps
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .models import ReviewDeletion, ReviewReport, Reviews
from .test_reportes import ReportesBase

POLITICA = ReviewDeletion.Policy.DISRESPECTFUL


class TodasLasResenasBase(ReportesBase):
    url = reverse("todas_las_resenas")

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ahora = timezone.now()
        cls.otra = Reviews.objects.create(
            user_id=cls.otro_cliente.pk,
            variant=cls.variant,
            content="Muy buen producto.",
            score=5,
            created_at=ahora,
            updated_at=ahora,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def eliminar(self, resena=None, follow=True, **datos):
        url = reverse(
            "eliminar_por_incumplimiento",
            kwargs={"review_id": (resena or self.resena).pk},
        )
        return self.client.post(
            url,
            {"policy": POLITICA, "note": "Insulta a otros usuarios.", **datos},
            follow=follow,
        )


class ListaTests(TodasLasResenasBase):
    def test_solo_el_administrador(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.reportante)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_muestra_todas_las_resenas_aunque_no_tengan_reportes(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Contenido ofensivo.")
        self.assertContains(respuesta, "Muy buen producto.")
        self.assertContains(respuesta, f'id="eliminar-{self.resena.pk}"')
        self.assertContains(respuesta, f'id="eliminar-{self.otra.pk}"')
        self.assertContains(respuesta, "2 reseñas")

    def test_la_ventana_pide_una_politica_de_los_terminos(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'name="policy" required')
        self.assertContains(
            respuesta, "Irrespetuoso, ofensivo o discriminatorio"
        )
        self.assertNotContains(respuesta, 'value="sin_clasificar"')

    def test_pestana_con_reportes_pendientes(self):
        self.crear_reporte()
        respuesta = self.client.get(self.url, {"vista": "reportadas"})
        self.assertContains(respuesta, "Contenido ofensivo.")
        self.assertNotContains(respuesta, "Muy buen producto.")
        self.assertContains(respuesta, "1 reporte")

    def test_busca_por_texto_o_autor_y_filtra_por_calificacion(self):
        for filtros in (
            {"q": "buen producto"},
            {"q": "otro@example"},
            {"calificacion": "5"},
        ):
            with self.subTest(**filtros):
                respuesta = self.client.get(self.url, filtros)
                self.assertContains(respuesta, "Muy buen producto.")
                self.assertNotContains(respuesta, "Contenido ofensivo.")

    def test_se_llega_desde_la_barra_lateral(self):
        self.assertContains(
            self.client.get(reverse("clientes")), f'href="{self.url}"'
        )

    def test_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.client.get(self.url)
        for texto in (
            "All reviews",
            "Published reviews",
            "Choose a policy",
            "Disrespectful, offensive or discriminatory",
            "2 reviews found",
        ):
            self.assertContains(respuesta, texto)
        self.assertNotContains(respuesta, "Elija una política")


class EliminarTests(TodasLasResenasBase):
    def test_elimina_y_registra_la_politica_y_la_razon(self):
        self.crear_reporte()
        respuesta = self.eliminar()
        self.assertContains(respuesta, "Reseña eliminada.")
        self.assertFalse(Reviews.objects.filter(pk=self.resena.pk).exists())
        registro = ReviewDeletion.objects.get()
        self.assertEqual(
            (
                registro.review_id,
                registro.author,
                registro.deleted_by,
                registro.policy,
                registro.reason,
            ),
            (
                self.resena.pk,
                self.autor,
                self.admin,
                POLITICA,
                "Insulta a otros usuarios.",
            ),
        )
        self.assertEqual(
            (
                registro.product_name,
                registro.content,
                registro.score,
                registro.reports,
            ),
            ("Producto", "Contenido ofensivo.", 1, 1),
        )
        # Los reportes pendientes de esa reseña quedan resueltos con la misma razón.
        reporte = ReviewReport.objects.get()
        self.assertEqual(
            (reporte.status, reporte.resolution_note),
            (ReviewReport.Status.DELETED, "Insulta a otros usuarios."),
        )

    def test_tambien_se_eliminan_resenas_sin_reportes(self):
        self.eliminar(
            self.otra,
            policy=ReviewDeletion.Policy.PROMOTIONAL,
            note="Publicidad.",
        )
        self.assertFalse(Reviews.objects.filter(pk=self.otra.pk).exists())
        self.assertEqual(ReviewDeletion.objects.get().reports, 0)

    def test_sin_politica_o_sin_razon_no_se_elimina(self):
        casos = {
            "": (
                "Insulta.",
                "Elija la política de uso que incumple la reseña.",
            ),
            "sin_clasificar": (
                "Insulta.",
                "Elija la política de uso que incumple la reseña.",
            ),
            POLITICA: ("", "Indique el motivo de la eliminación."),
        }
        for politica, (razon, aviso) in casos.items():
            with self.subTest(politica=politica, razon=razon):
                self.assertContains(
                    self.eliminar(policy=politica, note=razon), aviso
                )
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())
        self.assertFalse(ReviewDeletion.objects.exists())

    def test_puede_suspender_al_autor(self):
        respuesta = self.eliminar(suspend="on")
        self.assertContains(respuesta, "La cuenta del autor fue suspendida.")
        self.assertFalse(
            get_user_model().objects.get(pk=self.autor.pk).is_active
        )
        self.assertTrue(ReviewDeletion.objects.get().author_suspended)

    def test_cuenta_como_infraccion_del_cliente(self):
        self.eliminar()
        detalle = self.client.get(
            reverse("detalle_cliente", kwargs={"pk": self.autor.pk})
        )
        self.assertContains(
            detalle, "1 reseña de este cliente fue eliminada por moderación."
        )
        self.assertContains(
            detalle, "Irrespetuoso, ofensivo o discriminatorio"
        )
        self.assertContains(detalle, "Insulta a otros usuarios.")
        self.assertContains(
            self.client.get(reverse("clientes")), "1 reseña eliminada"
        )

    def test_queda_en_la_pestana_de_eliminadas(self):
        self.eliminar()
        respuesta = self.client.get(self.url, {"vista": "eliminadas"})
        self.assertContains(respuesta, f"#REV-{self.resena.pk}")
        self.assertContains(
            respuesta, "Irrespetuoso, ofensivo o discriminatorio"
        )
        self.assertContains(respuesta, "Insulta a otros usuarios.")
        self.assertContains(respuesta, "admin@example.com")
        self.assertContains(respuesta, "Contenido ofensivo.")

    def test_solo_el_administrador_y_solo_por_post(self):
        url = reverse(
            "eliminar_por_incumplimiento", kwargs={"review_id": self.resena.pk}
        )
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.reportante)
        self.assertEqual(self.eliminar(follow=False).status_code, 403)
        self.assertTrue(Reviews.objects.filter(pk=self.resena.pk).exists())

    def test_vuelve_a_la_lista_con_sus_filtros_y_nunca_fuera(self):
        volver = self.url + "?calificacion=1"
        self.assertRedirects(
            self.eliminar(follow=False, volver=volver),
            volver,
            fetch_redirect_response=False,
        )
        respuesta = self.eliminar(
            self.otra, follow=False, volver="https://malicioso.example/"
        )
        self.assertRedirects(
            respuesta, self.url, fetch_redirect_response=False
        )

    def test_una_resena_que_ya_no_existe(self):
        Reviews.objects.filter(pk=self.resena.pk).delete()
        self.assertEqual(self.eliminar(follow=False).status_code, 404)


class TraspasoDeEliminacionesAnterioresTests(TodasLasResenasBase):
    def test_las_eliminadas_por_reportes_pasan_al_registro_sin_clasificar(
        self,
    ):
        for reportante in (self.reportante, self.otro_cliente):
            ReviewReport.objects.create(
                review_id=777,
                reporter=reportante,
                review_author=self.autor,
                reason="Spam.",
                status=ReviewReport.Status.DELETED,
                resolved_by=self.admin,
                resolved_at=timezone.now(),
                resolution_note="Era spam.",
            )
        migracion = importlib.import_module(
            "reviews.migrations.0005_traspasar_eliminaciones_anteriores"
        )
        migracion.traspasar(apps, None)
        migracion.traspasar(apps, None)  # dos veces: no se duplica
        registro = ReviewDeletion.objects.get()
        self.assertEqual(
            (
                registro.review_id,
                registro.author,
                registro.policy,
                registro.reason,
                registro.reports,
            ),
            (
                777,
                self.autor,
                ReviewDeletion.Policy.UNCLASSIFIED,
                "Era spam.",
                2,
            ),
        )
