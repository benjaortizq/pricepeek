from django.test import TestCase
from django.urls import reverse

from .models import Usuario


class RegistroClienteTests(TestCase):
    def datos(self, **extra):
        datos = {
            "first_name": "Ana",
            "email": "ana@correo.com",
            "password1": "Clave2026segura",
            "password2": "Clave2026segura",
        }
        datos.update(extra)
        return datos

    def test_crea_cuenta_de_cliente_con_nombre_correo_y_contrasena(self):
        respuesta = self.client.post(reverse("registro"), self.datos())
        self.assertRedirects(respuesta, reverse("login"), fetch_redirect_response=False)
        usuario = Usuario.objects.get(email="ana@correo.com")
        self.assertEqual(usuario.first_name, "Ana")
        self.assertEqual(usuario.rol, Usuario.Rol.CLIENTE)
        self.assertTrue(usuario.check_password("Clave2026segura"))

    def test_no_permite_correo_duplicado(self):
        Usuario.objects.create_user(email="ana@correo.com", password="Otra2026clave")
        respuesta = self.client.post(reverse("registro"), self.datos(email="ANA@correo.com"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya existe una cuenta con este correo")
        self.assertEqual(Usuario.objects.filter(email__iexact="ana@correo.com").count(), 1)