from django.test import TestCase
from django.urls import reverse

from .models import User


class AlertasDePrecioEnElPerfilTests(TestCase):
    def setUp(self):
        self.cliente = User.objects.create_user(email="ana@example.com", password="Clave2026segura")
        self.url = reverse("editar_perfil")

    def activas(self, usuario):
        return User.objects.get(pk=usuario.pk).active_alerts

    def test_el_cliente_ve_la_seccion_de_alertas_activada_por_defecto(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Alertas de precio")
        self.assertContains(respuesta, "Recibir alertas de baja de precio por correo")
        self.assertTrue(respuesta.context["form_alertas"]["active_alerts"].value())

    def test_el_cliente_puede_desactivar_las_alertas(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.post(self.url, {"accion": "alertas"}, follow=True)
        self.assertRedirects(respuesta, self.url)
        self.assertContains(respuesta, "quedaron desactivadas")
        self.assertFalse(self.activas(self.cliente))

    def test_el_cliente_puede_volver_a_activar_las_alertas(self):
        User.objects.filter(pk=self.cliente.pk).update(active_alerts=False)
        self.client.force_login(self.cliente)
        respuesta = self.client.post(
            self.url, {"accion": "alertas", "alertas-active_alerts": "on"}, follow=True
        )
        self.assertContains(respuesta, "quedaron activadas")
        self.assertTrue(self.activas(self.cliente))

    def test_solo_los_clientes_ven_y_cambian_las_alertas(self):
        for rol in ("enterprise", "admin"):
            with self.subTest(rol=rol):
                usuario = User.objects.create_user(
                    email=f"{rol}@example.com", password="Clave2026segura", role=rol
                )
                self.client.force_login(usuario)
                self.assertNotContains(self.client.get(self.url), "Alertas de precio")
                self.client.post(self.url, {"accion": "alertas"})
                self.assertTrue(self.activas(usuario))

    def test_el_visitante_es_enviado_a_iniciar_sesion(self):
        respuesta = self.client.post(self.url, {"accion": "alertas"})
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
