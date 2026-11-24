from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reviews.models import ReviewReport

from .models import User

CLAVE = "Clave2026segura"


class SuspensionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(email="admin@example.com", password=CLAVE, role="admin")
        cls.empresa = User.objects.create_user(email="empresa@example.com", password=CLAVE, role="enterprise")
        cls.cliente = User.objects.create_user(
            email="infractor@example.com", password=CLAVE, first_name="Iván", last_name="Infractor"
        )
        cls.otro = User.objects.create_user(email="cumplido@example.com", password=CLAVE, first_name="Ana")

    def eliminar_resena_de(self, autor, review_id, nota="Lenguaje ofensivo.", reportantes=None):
        """Simula una reseña del autor que el administrador eliminó tras uno o más reportes."""
        for reportante in reportantes or [self.otro]:
            ReviewReport.objects.create(
                review_id=review_id,
                reporter=reportante,
                review_author=autor,
                reason="Inapropiada.",
                status=ReviewReport.Status.DELETED,
                resolved_by=self.admin,
                resolved_at=timezone.now(),
                resolution_note=nota,
            )

    def recargar(self, usuario):
        return User.objects.get(pk=usuario.pk)


class ListaDeClientesTests(SuspensionBase):
    url = reverse("clientes")

    def test_solo_el_administrador_de_pricepeek_puede_verla(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
        for usuario in (self.cliente, self.empresa):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_muestra_solo_cuentas_de_cliente(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "infractor@example.com")
        self.assertContains(respuesta, "cumplido@example.com")
        self.assertNotContains(respuesta, "empresa@example.com")
        self.assertContains(respuesta, "2 clientes")

    def test_los_clientes_con_mas_infracciones_aparecen_primero(self):
        self.eliminar_resena_de(self.cliente, 1)
        self.eliminar_resena_de(self.cliente, 2, reportantes=[self.otro, self.admin])  # misma reseña: cuenta 1
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        contenido = respuesta.content.decode()
        self.assertLess(contenido.index("infractor@example.com"), contenido.index("cumplido@example.com"))
        self.assertContains(respuesta, "2 reseñas eliminadas")

    def test_busca_por_correo_o_nombre(self):
        self.client.force_login(self.admin)
        for busqueda in ("infractor@", "Iván", "infractor"):
            with self.subTest(busqueda=busqueda):
                respuesta = self.client.get(self.url, {"q": busqueda})
                self.assertContains(respuesta, "infractor@example.com")
                self.assertNotContains(respuesta, "cumplido@example.com")

    def test_filtra_por_estado_de_la_cuenta(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Reiterado.")
        self.client.force_login(self.admin)
        suspendidas = self.client.get(self.url, {"estado": "suspendidas"})
        self.assertContains(suspendidas, "infractor@example.com")
        self.assertNotContains(suspendidas, "cumplido@example.com")
        activas = self.client.get(self.url, {"estado": "activas"})
        self.assertNotContains(activas, "infractor@example.com")
        self.assertContains(activas, "cumplido@example.com")


    def test_pagina_sin_perder_los_filtros(self):
        for numero in range(20):
            User.objects.create_user(email=f"cliente{numero:02d}@example.com", password=CLAVE)
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url, {"q": "example", "estado": "activas"})
        self.assertContains(respuesta, "Página 1 de 2")
        self.assertContains(respuesta, "?q=example&amp;estado=activas&amp;pagina=2")
        segunda = self.client.get(self.url, {"q": "example", "estado": "activas", "pagina": 2})
        self.assertContains(segunda, "Página 2 de 2")


class DetalleDeClienteTests(SuspensionBase):
    def url(self, usuario):
        return reverse("detalle_cliente", kwargs={"pk": usuario.pk})

    def test_muestra_el_historial_de_incumplimientos(self):
        self.eliminar_resena_de(self.cliente, 1, nota="Insultos a otros clientes.")
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url(self.cliente))
        self.assertContains(respuesta, "1 reseña de este cliente fue eliminada")
        self.assertContains(respuesta, "Insultos a otros clientes.")
        self.assertNotContains(respuesta, "ha incumplido las políticas de uso de forma reiterada")

    def test_avisa_cuando_el_cliente_incumple_de_forma_reiterada(self):
        self.eliminar_resena_de(self.cliente, 1)
        self.eliminar_resena_de(self.cliente, 2)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url(self.cliente)), "ha incumplido las políticas de uso de forma reiterada")

    def test_cliente_sin_incumplimientos(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url(self.otro)), "no tiene reseñas eliminadas por moderación")

    def test_cuentas_que_no_son_de_cliente_no_existen_en_el_panel(self):
        self.client.force_login(self.admin)
        for usuario in (self.empresa, self.admin):
            with self.subTest(rol=usuario.role):
                self.assertEqual(self.client.get(self.url(usuario)).status_code, 404)

    def test_solo_el_administrador_puede_verlo(self):
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(self.url(self.cliente)).status_code, 403)


class SuspenderClienteTests(SuspensionBase):
    def suspender(self, usuario, motivo="Publicó reseñas ofensivas de forma reiterada."):
        url = reverse("suspender_cliente", kwargs={"pk": usuario.pk})
        return self.client.post(url, {"motivo": motivo}, follow=True)

    def test_el_administrador_suspende_la_cuenta_y_queda_registrado(self):
        self.client.force_login(self.admin)
        antes = timezone.now()
        respuesta = self.suspender(self.cliente, "Spam reiterado en reseñas.")
        self.assertRedirects(respuesta, reverse("detalle_cliente", kwargs={"pk": self.cliente.pk}))
        self.assertContains(respuesta, "La cuenta de infractor@example.com fue suspendida")
        self.assertContains(respuesta, "Cuenta suspendida")
        cliente = self.recargar(self.cliente)
        self.assertFalse(cliente.is_active)
        self.assertEqual(cliente.suspension_reason, "Spam reiterado en reseñas.")
        self.assertEqual(cliente.suspended_by, self.admin)
        self.assertGreaterEqual(cliente.suspended_at, antes)
        self.assertTrue(self.recargar(self.otro).is_active)

    def test_el_motivo_es_obligatorio(self):
        self.client.force_login(self.admin)
        for motivo in ("", "   "):
            with self.subTest(motivo=motivo):
                respuesta = self.suspender(self.cliente, motivo)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "Indique el motivo de la suspensión")
                self.assertTrue(self.recargar(self.cliente).is_active)

    def test_el_mensaje_de_suspension_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        self.client.force_login(self.admin)

        respuesta = self.suspender(self.cliente, "Spam reiterado en reseñas.")

        self.assertContains(
            respuesta,
            "The account for infractor@example.com was suspended.",
        )

    def test_el_error_del_formulario_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        self.client.force_login(self.admin)

        respuesta = self.suspender(self.cliente, "")

        self.assertContains(respuesta, "Enter a reason for the suspension.")

    def test_rechaza_un_motivo_de_mas_de_500_caracteres(self):
        self.client.force_login(self.admin)
        self.suspender(self.cliente, "a" * 501)
        self.assertTrue(self.recargar(self.cliente).is_active)

    def test_no_se_puede_suspender_dos_veces(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Primera vez.")
        self.client.force_login(self.admin)
        respuesta = self.suspender(self.cliente, "Segunda vez.")
        self.assertContains(respuesta, "Esa cuenta ya estaba suspendida")
        self.assertEqual(self.recargar(self.cliente).suspension_reason, "Primera vez.")

    def test_no_se_pueden_suspender_cuentas_de_empresa_ni_de_administrador(self):
        self.client.force_login(self.admin)
        for usuario in (self.empresa, self.admin):
            with self.subTest(rol=usuario.role):
                self.assertEqual(self.suspender(usuario).status_code, 404)
                self.assertTrue(self.recargar(usuario).is_active)

    def test_solo_el_administrador_puede_suspender(self):
        for usuario in (self.otro, self.empresa):
            with self.subTest(rol=usuario.role):
                self.client.force_login(usuario)
                self.assertEqual(self.suspender(self.cliente).status_code, 403)
        self.client.logout()
        self.suspender(self.cliente)
        self.assertTrue(self.recargar(self.cliente).is_active)

    def test_solo_acepta_post(self):
        self.client.force_login(self.admin)
        url = reverse("suspender_cliente", kwargs={"pk": self.cliente.pk})
        self.assertEqual(self.client.get(url).status_code, 405)


class EfectosDeLaSuspensionTests(SuspensionBase):
    def setUp(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Reiterado.")

    def iniciar_sesion(self, password):
        return self.client.post(reverse("login"), {"username": "infractor@example.com", "password": password})

    def test_el_cliente_suspendido_no_puede_iniciar_sesion(self):
        self.assertFalse(self.client.login(email="infractor@example.com", password=CLAVE))
        respuesta = self.iniciar_sesion(CLAVE)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Su cuenta está suspendida")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_con_contrasena_incorrecta_no_revela_la_suspension(self):
        respuesta = self.iniciar_sesion("OtraClave2026")
        self.assertNotContains(respuesta, "suspendida")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_los_demas_clientes_inician_sesion_normalmente(self):
        respuesta = self.client.post(reverse("login"), {"username": "cumplido@example.com", "password": CLAVE})
        self.assertRedirects(respuesta, reverse("panel"), fetch_redirect_response=False)

    def test_la_sesion_abierta_del_cliente_se_cierra(self):
        User.objects.reactivar_cliente(self.cliente.pk)
        self.client.force_login(self.recargar(self.cliente))
        self.assertEqual(self.client.get(reverse("editar_perfil")).status_code, 200)
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Otra vez.")
        respuesta = self.client.get(reverse("editar_perfil"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)


class ReactivarClienteTests(SuspensionBase):
    def reactivar(self, usuario):
        return self.client.post(reverse("reactivar_cliente", kwargs={"pk": usuario.pk}), follow=True)

    def test_el_administrador_reactiva_la_cuenta(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Reiterado.")
        self.client.force_login(self.admin)
        respuesta = self.reactivar(self.cliente)
        self.assertContains(respuesta, "La cuenta de infractor@example.com fue reactivada")
        cliente = self.recargar(self.cliente)
        self.assertTrue(cliente.is_active)
        self.assertIsNone(cliente.suspended_at)
        self.assertIsNone(cliente.suspended_by)
        self.assertEqual(cliente.suspension_reason, "")
        self.assertTrue(self.client.login(email="infractor@example.com", password=CLAVE))

    def test_reactivar_una_cuenta_activa_no_hace_nada(self):
        self.client.force_login(self.admin)
        self.assertContains(self.reactivar(self.cliente), "Esa cuenta no estaba suspendida")

    def test_solo_el_administrador_puede_reactivar(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Reiterado.")
        self.client.force_login(self.otro)
        self.assertEqual(self.reactivar(self.cliente).status_code, 403)
        self.assertFalse(self.recargar(self.cliente).is_active)

    def test_solo_acepta_post(self):
        self.client.force_login(self.admin)
        url = reverse("reactivar_cliente", kwargs={"pk": self.cliente.pk})
        self.assertEqual(self.client.get(url).status_code, 405)
