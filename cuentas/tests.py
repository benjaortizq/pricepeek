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



class InicioSesionTests(TestCase):
    def setUp(self):
        self.clave = "Clave2026segura"
        self.cliente = Usuario.objects.create_user(
            email="cliente@correo.com", password=self.clave, rol=Usuario.Rol.CLIENTE)
        self.empresa = Usuario.objects.create_user(
            email="empresa@correo.com", password=self.clave, rol=Usuario.Rol.EMPRESA)
        self.admin = Usuario.objects.create_user(
            email="admin@correo.com", password=self.clave, rol=Usuario.Rol.ADMINISTRADOR)

    def iniciar(self, email, clave=None):
        datos = {"username": email, "password": clave or self.clave}
        return self.client.post(reverse("login"), datos, follow=True)

    def test_cada_rol_inicia_sesion_con_correo_y_llega_a_su_pagina(self):
        casos = [
            (self.cliente, "inicio_cliente"),
            (self.empresa, "inicio_empresa"),
            (self.admin, "inicio_administrador"),
        ]
        for usuario, destino in casos:
            with self.subTest(rol=usuario.rol):
                respuesta = self.iniciar(usuario.email)
                self.assertRedirects(respuesta, reverse(destino))
                self.client.logout()

    def test_contrasena_incorrecta_no_inicia_sesion(self):
        respuesta = self.iniciar(self.cliente.email, "incorrecta")
        self.assertFalse(respuesta.wsgi_request.user.is_authenticated)

    def test_cliente_no_puede_entrar_al_panel_de_empresa(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.get(reverse("inicio_empresa"))
        self.assertEqual(respuesta.status_code, 403)

    def test_menu_muestra_solo_lo_del_rol(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.get(reverse("inicio_cliente"))
        self.assertNotContains(respuesta, "Panel de empresa")
        self.assertNotContains(respuesta, "Administración")

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(reverse("inicio_cliente"))
        esperado = f"{reverse('login')}?next={reverse('inicio_cliente')}"
        self.assertRedirects(respuesta, esperado)