import re
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import views
from .models import User


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
        respuesta = self.client.post(reverse("register"), self.datos())
        self.assertRedirects(respuesta, reverse("login"), fetch_redirect_response=False)
        user = User.objects.get(email="ana@correo.com")
        self.assertEqual(user.first_name, "Ana")
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertTrue(user.check_password("Clave2026segura"))

    def test_no_permite_correo_duplicado(self):
        User.objects.create_user(email="ana@correo.com", password="Otra2026clave")
        respuesta = self.client.post(reverse("register"), self.datos(email="ANA@correo.com"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ya existe una cuenta con este correo")
        self.assertEqual(User.objects.filter(email__iexact="ana@correo.com").count(), 1)


class RecuperarContrasenaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@correo.com", password="Vieja2026clave", first_name="Ana"
        )

    def url_de_cambio(self, user=None):
        user = user or self.user
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        return reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})

    def restablecer(self, password):
        # Django guarda el token en la sesión y redirige a una URL "set-password".
        respuesta = self.client.get(self.url_de_cambio())
        return self.client.post(
            respuesta.url, {"new_password1": password, "new_password2": password}
        )

    def test_solicitud_envia_correo_con_enlace_al_correo_registrado(self):
        respuesta = self.client.post(reverse("password_reset"), {"email": "ana@correo.com"})
        self.assertRedirects(respuesta, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@correo.com"])
        self.assertIn("/accounts/reset/", mail.outbox[0].body)
        self.assertIn("24 horas", mail.outbox[0].body)

    def test_correo_no_registrado_no_envia_correo_ni_revela_que_no_existe(self):
        respuesta = self.client.post(reverse("password_reset"), {"email": "nadie@correo.com"})
        self.assertRedirects(respuesta, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_enlace_valido_permite_cambiar_la_contrasena(self):
        respuesta = self.restablecer("Nueva2026clave")
        self.assertRedirects(
            respuesta, reverse("password_reset_complete"), fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Nueva2026clave"))
        self.assertFalse(self.user.check_password("Vieja2026clave"))

    def test_cambio_actualiza_la_fecha_del_ultimo_cambio_de_contrasena(self):
        antes = timezone.now() - timedelta(days=30)
        User.objects.filter(pk=self.user.pk).update(last_password_change=antes)
        self.restablecer("Nueva2026clave")
        self.user.refresh_from_db()
        self.assertGreater(self.user.last_password_change, antes)

    def test_rechaza_contrasena_sin_numero(self):
        respuesta = self.restablecer("SoloLetrasAqui")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "al menos un número")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_rechaza_contrasena_sin_letra(self):
        respuesta = self.restablecer("90817263544")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "al menos una letra")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_rechaza_contrasena_de_menos_de_8_caracteres(self):
        respuesta = self.restablecer("Ab1")
        self.assertEqual(respuesta.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_el_enlace_vence_a_las_24_horas(self):
        token = default_token_generator.make_token(self.user)
        ahora = datetime.now()
        with patch.object(PasswordResetTokenGenerator, "_now", return_value=ahora + timedelta(hours=23)):
            self.assertTrue(default_token_generator.check_token(self.user, token))
        with patch.object(PasswordResetTokenGenerator, "_now", return_value=ahora + timedelta(hours=24, minutes=1)):
            self.assertFalse(default_token_generator.check_token(self.user, token))

    def test_enlace_no_se_puede_reutilizar(self):
        url = self.url_de_cambio()
        self.restablecer("Nueva2026clave")
        respuesta = self.client.get(url, follow=True)
        self.assertContains(respuesta, "Enlace no válido")

    def test_cuenta_suspendida_no_recibe_enlace(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.client.post(reverse("password_reset"), {"email": "ana@correo.com"})
        self.assertEqual(len(mail.outbox), 0)


class EliminarCuentaTests(TestCase):
    def setUp(self):
        self.cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")
        self.otro = User.objects.create_user(email="luis@correo.com", password="Otra2026clave")
        self.url = reverse("eliminar_cuenta")

    def test_cliente_elimina_su_cuenta_con_la_contrasena_correcta(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.post(self.url, {"password": "Clave2026segura"})
        self.assertRedirects(respuesta, reverse("login"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(email="ana@correo.com").exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_eliminar_cuenta_no_afecta_a_otros_usuarios(self):
        self.client.force_login(self.cliente)
        self.client.post(self.url, {"password": "Clave2026segura"})
        self.assertTrue(User.objects.filter(email="luis@correo.com").exists())

    def test_contrasena_incorrecta_no_elimina_la_cuenta(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.post(self.url, {"password": "incorrecta123"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "no es correcta")
        self.assertTrue(User.objects.filter(email="ana@correo.com").exists())

    def test_contrasena_vacia_no_elimina_la_cuenta(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.post(self.url, {"password": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(User.objects.filter(email="ana@correo.com").exists())

    def test_get_muestra_el_formulario_sin_eliminar(self):
        self.client.force_login(self.cliente)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(User.objects.filter(email="ana@correo.com").exists())

    def test_visitante_es_redirigido_al_login(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    def test_empresa_y_administrador_no_pueden_eliminar_por_esta_via(self):
        for rol in (User.Role.ENTERPRISE, User.Role.ADMIN):
            with self.subTest(rol=rol):
                usuario = User.objects.create_user(
                    email=f"{rol}@correo.com", password="Clave2026segura", role=rol
                )
                self.client.force_login(usuario)
                respuesta = self.client.post(self.url, {"password": "Clave2026segura"})
                self.assertEqual(respuesta.status_code, 403)
                self.assertTrue(User.objects.filter(pk=usuario.pk).exists())


class CambioContrasenaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@correo.com", password="Vieja2026clave", first_name="Ana"
        )
        self.client.force_login(self.user)
        self.url = reverse("password_change")
        self.url_confirmar = reverse("password_change_confirm")

    def solicitar(self, actual="Vieja2026clave", nueva="Nueva2026clave"):
        return self.client.post(
            self.url,
            {"old_password": actual, "new_password1": nueva, "new_password2": nueva},
        )

    def codigo_enviado(self):
        return re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()

    def confirmar(self, codigo):
        return self.client.post(self.url_confirmar, {"codigo": codigo})

    def test_reemplaza_la_vista_de_django_que_no_pide_codigo(self):
        self.assertEqual(resolve("/accounts/password_change/").func, views.cambiar_contrasena)

    def test_solicitud_envia_codigo_al_correo_sin_cambiar_aun_la_contrasena(self):
        respuesta = self.solicitar()
        self.assertRedirects(respuesta, self.url_confirmar)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@correo.com"])
        self.assertIn("10 minutos", mail.outbox[0].body)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_codigo_correcto_cambia_la_contrasena_y_mantiene_la_sesion(self):
        antes = timezone.now() - timedelta(days=30)
        User.objects.filter(pk=self.user.pk).update(last_password_change=antes)
        self.solicitar()
        respuesta = self.confirmar(self.codigo_enviado())
        self.assertRedirects(respuesta, reverse("panel"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Nueva2026clave"))
        self.assertFalse(self.user.check_password("Vieja2026clave"))
        self.assertGreater(self.user.last_password_change, antes)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertNotIn(views.CAMBIO_PENDIENTE, self.client.session)

    def test_contrasena_actual_incorrecta_no_envia_codigo(self):
        respuesta = self.solicitar(actual="Incorrecta2026")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_nueva_contrasena_sin_numero_no_envia_codigo(self):
        respuesta = self.solicitar(nueva="SoloLetrasAqui")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "al menos un número")
        self.assertEqual(len(mail.outbox), 0)

    def test_nuevas_contrasenas_distintas_no_envian_codigo(self):
        respuesta = self.client.post(
            self.url,
            {
                "old_password": "Vieja2026clave",
                "new_password1": "Nueva2026clave",
                "new_password2": "Otra2026clave",
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_codigo_incorrecto_no_cambia_la_contrasena(self):
        self.solicitar()
        codigo = self.codigo_enviado()
        incorrecto = "000000" if codigo != "000000" else "111111"
        respuesta = self.confirmar(incorrecto)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "no es correcto")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_demasiados_intentos_invalidan_el_codigo(self):
        self.solicitar()
        codigo = self.codigo_enviado()
        incorrecto = "000000" if codigo != "000000" else "111111"
        for _ in range(5):
            respuesta = self.confirmar(incorrecto)
        self.assertRedirects(respuesta, self.url)
        respuesta = self.confirmar(codigo)
        self.assertRedirects(respuesta, self.url)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_codigo_vencido_no_cambia_la_contrasena(self):
        self.solicitar()
        codigo = self.codigo_enviado()
        with patch("accounts.views.timezone.now", return_value=timezone.now() + timedelta(minutes=11)):
            respuesta = self.confirmar(codigo)
        self.assertRedirects(respuesta, self.url)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Vieja2026clave"))

    def test_nuevo_codigo_reemplaza_al_anterior(self):
        self.solicitar()
        primero = self.codigo_enviado()
        self.solicitar(nueva="Otra2026clave")
        segundo = self.codigo_enviado()
        if primero != segundo:
            self.assertEqual(self.confirmar(primero).status_code, 200)
        self.confirmar(segundo)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Otra2026clave"))

    def test_confirmar_sin_solicitud_previa_redirige_al_formulario(self):
        respuesta = self.client.get(self.url_confirmar)
        self.assertRedirects(respuesta, self.url)

    def test_visitante_es_redirigido_al_login(self):
        self.client.logout()
        for url in (self.url, self.url_confirmar):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn(reverse("login"), respuesta.url)

    def test_cualquier_rol_puede_cambiar_su_contrasena(self):
        for rol in (User.Role.ENTERPRISE, User.Role.ADMIN):
            with self.subTest(rol=rol):
                usuario = User.objects.create_user(
                    email=f"{rol}@correo.com", password="Vieja2026clave", role=rol
                )
                self.client.force_login(usuario)
                self.solicitar()
                self.confirmar(self.codigo_enviado())
                usuario.refresh_from_db()
                self.assertTrue(usuario.check_password("Nueva2026clave"))
