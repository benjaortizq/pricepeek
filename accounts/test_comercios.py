"""Issue «Gestión de comercios asociados»: el administrador registra el comercio con su cuenta de
empresa, define cómo se obtienen sus datos y lo activa o desactiva."""

import re
from unittest import mock

from django.core import mail
from django.urls import reverse

from products.models import PartnerStore, Stores
from products.tests import CatalogoTestCase, fechas

from .models import AccountsUser, User

CLAVE = "Clave2026segura"
SCRAPING = PartnerStore.DataSource.SCRAPING
PROVISTOS = PartnerStore.DataSource.PROVIDED


class ComerciosTestCase(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(email="admin@example.com", password=CLAVE, role="admin")
        cls.cliente = User.objects.create_user(email="cliente@example.com", password=CLAVE)
        # Walmart ya existía (sin PartnerStore) y PricePeek sabe leer su página.
        cls.walmart = Stores.objects.create(name="Walmart\n", **fechas())
        precio = cls.precio(cls.variante_leche, cls.walmart, 1200)
        precio.product_web_url = "https://www.walmart.co.cr/leche/p"
        precio.save(update_fields=["product_web_url"])
        cls.empresa = User.objects.create_user(email="empresa@walmart.test", password=CLAVE, role="enterprise")
        AccountsUser.objects.filter(pk=cls.empresa.pk).update(from_store_id=cls.walmart.pk)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def mensajes(self, respuesta):
        return [str(mensaje) for mensaje in respuesta.wsgi_request._messages]

    def datos_de_registro(self, **cambios):
        return {
            "name": "Super La Esquina",
            "description": "Supermercado de barrio en Cartago.",
            "data_source": PROVISTOS,
            "email": "Gerencia@LaEsquina.test",
            "first_name": "Ana",
            "last_name": "Mora",
            "is_active": "on",
            **cambios,
        }

    def registrar(self, **cambios):
        return self.client.post(reverse("registrar_comercio"), self.datos_de_registro(**cambios))


class RegistrarComercioTests(ComerciosTestCase):
    def test_registra_el_comercio_con_su_cuenta_de_empresa(self):
        respuesta = self.registrar()
        tienda = Stores.objects.get(name="Super La Esquina")
        self.assertRedirects(respuesta, reverse("detalle_comercio", args=[tienda.pk]))
        self.assertEqual(tienda.description, "Supermercado de barrio en Cartago.")
        perfil = tienda.asociado
        self.assertEqual((perfil.data_source, perfil.is_active, perfil.status_changed_by), (PROVISTOS, True, self.admin))
        cuenta = User.objects.get(email="gerencia@laesquina.test")
        self.assertEqual((cuenta.role, cuenta.get_full_name()), (User.Role.ENTERPRISE, "Ana Mora"))
        self.assertEqual(AccountsUser.objects.get(pk=cuenta.pk).from_store_id, tienda.pk)
        self.assertEqual(
            self.mensajes(respuesta),
            [
                "Se registró el comercio «Super La Esquina» con su cuenta de empresa.",
                "Se envió a gerencia@laesquina.test el enlace para elegir su contraseña.",
            ],
        )

    def test_la_cuenta_elige_su_contrasena_y_entra_al_portal_de_su_comercio(self):
        self.registrar()
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["gerencia@laesquina.test"])
        self.assertEqual(correo.subject, "Su cuenta de empresa de Super La Esquina en PricePeek")
        enlace = re.search(r"http://testserver(/accounts/reset/\S+)", correo.body).group(1)

        self.client.logout()
        formulario = self.client.get(enlace, follow=True)
        self.assertEqual(formulario.status_code, 200)
        nueva = "OtraClave2026segura"
        self.client.post(formulario.redirect_chain[-1][0], {"new_password1": nueva, "new_password2": nueva})
        self.assertTrue(self.client.login(email="gerencia@laesquina.test", password=nueva))
        portal = self.client.get(reverse("enterprise:panel"))
        self.assertEqual(portal.status_code, 200)
        self.assertContains(portal, "Super La Esquina")

    def test_puede_quedar_desactivado_desde_el_registro(self):
        self.registrar(is_active="")
        self.assertFalse(Stores.objects.get(name="Super La Esquina").asociado.is_active)

    def test_el_nombre_no_se_puede_repetir(self):
        respuesta = self.registrar(name="  walmart ")
        self.assertEqual(respuesta.context["form"].errors["name"], ["Ya hay un comercio con ese nombre."])
        self.assertEqual(Stores.objects.count(), 1)

    def test_el_correo_no_puede_ser_de_otra_cuenta(self):
        respuesta = self.registrar(email="EMPRESA@walmart.test")
        self.assertEqual(
            respuesta.context["form"].errors["email"], ["Ya existe una cuenta con este correo electrónico."]
        )
        self.assertFalse(Stores.objects.filter(name="Super La Esquina").exists())

    def test_hay_que_elegir_como_se_obtienen_los_datos(self):
        respuesta = self.registrar(data_source="")
        self.assertEqual(
            respuesta.context["form"].errors["data_source"], ["Elija cómo se obtienen los datos del comercio."]
        )

    def test_si_el_correo_no_sale_la_cuenta_queda_creada_y_lo_avisa(self):
        with mock.patch("accounts.comercios.send_mail", side_effect=OSError("sin conexión")):
            respuesta = self.registrar()
        self.assertTrue(User.objects.filter(email="gerencia@laesquina.test").exists())
        self.assertIn(
            "No se pudo enviar el correo a gerencia@laesquina.test. La cuenta quedó creada: use «Reenviar acceso» más tarde.",
            self.mensajes(respuesta),
        )


class ListaDeComerciosTests(ComerciosTestCase):
    def test_lista_los_comercios_con_su_estado_y_su_mecanismo(self):
        self.registrar(data_source=SCRAPING, is_active="")
        respuesta = self.client.get(reverse("comercios"))
        self.assertEqual(respuesta.status_code, 200)
        filas = {fila["nombre"]: fila for fila in respuesta.context["pagina"].object_list}
        # Walmart nunca se configuró: sigue activo y con web scraping porque PricePeek lee su página.
        self.assertEqual(
            {nombre: (f["activo"], f["mecanismo"], f["con_lector"], f["cuentas"]) for nombre, f in filas.items()},
            {"Walmart": (True, SCRAPING, True, 1), "Super La Esquina": (False, SCRAPING, False, 1)},
        )
        self.assertContains(respuesta, "Sin lector de su página")
        self.assertContains(respuesta, reverse("registrar_comercio"))

    def test_filtra_por_estado_y_busca_por_nombre(self):
        self.registrar(is_active="")
        Stores.objects.create(name="Sin Cuenta S.A.", **fechas())
        casos = {
            ("activos", ""): ["Sin Cuenta S.A.", "Walmart"],
            ("desactivados", ""): ["Super La Esquina"],
            ("sin-cuenta", ""): ["Sin Cuenta S.A."],
            ("", "esquina"): ["Super La Esquina"],
        }
        for (estado, busqueda), esperados in casos.items():
            with self.subTest(estado=estado, busqueda=busqueda):
                respuesta = self.client.get(reverse("comercios"), {"estado": estado, "q": busqueda})
                self.assertEqual([fila["nombre"] for fila in respuesta.context["pagina"].object_list], esperados)

    def test_esta_en_la_barra_lateral_del_panel(self):
        self.assertContains(self.client.get(reverse("inicio_administrador")), reverse("comercios"))


class DetalleDelComercioTests(ComerciosTestCase):
    def url(self, tienda=None):
        return reverse("detalle_comercio", args=[(tienda or self.walmart).pk])

    def test_muestra_sus_datos_y_sus_cuentas(self):
        respuesta = self.client.get(self.url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "empresa@walmart.test")
        self.assertContains(respuesta, "Comercio activo")
        self.assertEqual(respuesta.context["form_datos"]["data_source"].value(), SCRAPING)

    def test_cambia_el_nombre_la_descripcion_y_el_mecanismo(self):
        respuesta = self.client.post(
            self.url(), {"name": "Walmart Costa Rica", "description": "Hipermercado.", "data_source": PROVISTOS}
        )
        self.assertRedirects(respuesta, self.url())
        self.walmart.refresh_from_db()
        self.assertEqual((self.walmart.name, self.walmart.description), ("Walmart Costa Rica", "Hipermercado."))
        self.assertEqual(self.walmart.asociado.data_source, PROVISTOS)
        self.assertTrue(self.walmart.asociado.is_active)

    def test_sin_cambios_no_crea_nada(self):
        respuesta = self.client.post(self.url(), {"name": "Walmart", "description": "", "data_source": SCRAPING})
        self.assertEqual(self.mensajes(respuesta), ["No había cambios que guardar."])
        self.assertFalse(PartnerStore.objects.exists())

    def test_desactiva_y_vuelve_a_activar(self):
        respuesta = self.client.post(reverse("estado_comercio", args=[self.walmart.pk]), {"activo": "0"})
        self.assertRedirects(respuesta, self.url())
        perfil = PartnerStore.objects.get(store=self.walmart)
        self.assertEqual((perfil.is_active, perfil.data_source, perfil.status_changed_by), (False, SCRAPING, self.admin))
        self.assertIn(
            "Se desactivó el comercio «Walmart». Sus precios ya no se muestran y la obtención de datos deja de revisarlos.",
            self.mensajes(respuesta),
        )
        detalle = self.client.get(self.url())
        self.assertContains(detalle, "Comercio desactivado")
        self.assertContains(detalle, "admin@example.com")

        respuesta = self.client.post(reverse("estado_comercio", args=[self.walmart.pk]), {"activo": "1"})
        self.assertTrue(PartnerStore.objects.get(store=self.walmart).is_active)
        self.assertIn("Se activó el comercio «Walmart». Sus precios vuelven a mostrarse.", self.mensajes(respuesta))

    def test_activar_lo_que_ya_esta_activo_no_cambia_nada(self):
        respuesta = self.client.post(reverse("estado_comercio", args=[self.walmart.pk]), {"activo": "1"})
        self.assertEqual(self.mensajes(respuesta), ["El comercio «Walmart» ya estaba activo."])
        self.assertFalse(PartnerStore.objects.exists())

    def test_crea_otra_cuenta_de_empresa(self):
        respuesta = self.client.post(
            reverse("crear_cuenta_comercio", args=[self.walmart.pk]), {"email": "precios@walmart.test"}
        )
        self.assertRedirects(respuesta, self.url())
        cuenta = User.objects.get(email="precios@walmart.test")
        self.assertEqual(AccountsUser.objects.get(pk=cuenta.pk).from_store_id, self.walmart.pk)
        self.assertEqual(mail.outbox[-1].to, ["precios@walmart.test"])

    def test_una_cuenta_con_correo_repetido_muestra_el_error(self):
        respuesta = self.client.post(
            reverse("crear_cuenta_comercio", args=[self.walmart.pk]), {"email": "cliente@example.com"}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.context["form_cuenta"].errors["email"], ["Ya existe una cuenta con este correo electrónico."]
        )

    def test_reenvia_el_acceso_solo_a_las_cuentas_del_comercio(self):
        respuesta = self.client.post(reverse("reenviar_acceso_comercio", args=[self.walmart.pk, self.empresa.pk]))
        self.assertRedirects(respuesta, self.url())
        self.assertEqual(mail.outbox[-1].to, ["empresa@walmart.test"])
        otra = Stores.objects.create(name="Otra", **fechas())
        self.assertEqual(
            self.client.post(reverse("reenviar_acceso_comercio", args=[otra.pk, self.empresa.pk])).status_code, 404
        )


class TraduccionTests(ComerciosTestCase):
    def test_las_pantallas_y_el_correo_se_traducen_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        lista = self.client.get(reverse("comercios"))
        for texto in ("Partner stores", "Register store", "Business accounts", "Web scraping", "Manage"):
            self.assertContains(lista, texto)
        registro = self.client.get(reverse("registrar_comercio"))
        for texto in ("Register partner store", "Data provided by the store", "Business account", "Activate it right away"):
            self.assertContains(registro, texto)
        detalle = self.client.get(reverse("detalle_comercio", args=[self.walmart.pk]))
        for texto in ("Active store", "Deactivate store", "Resend access", "Create a business account"):
            self.assertContains(detalle, texto)
        self.registrar()
        self.assertEqual(mail.outbox[-1].subject, "Your Super La Esquina business account on PricePeek")
        self.assertIn("To choose your password, open this link:", mail.outbox[-1].body)


class PermisosTests(ComerciosTestCase):
    def test_solo_el_administrador(self):
        urls_get = [reverse("comercios"), reverse("registrar_comercio"), reverse("detalle_comercio", args=[self.walmart.pk])]
        urls_post = [
            reverse("estado_comercio", args=[self.walmart.pk]),
            reverse("crear_cuenta_comercio", args=[self.walmart.pk]),
            reverse("reenviar_acceso_comercio", args=[self.walmart.pk, self.empresa.pk]),
        ]
        self.client.force_login(self.empresa)
        for url in urls_get:
            self.assertEqual(self.client.get(url).status_code, 403)
        for url in urls_post:
            self.assertEqual(self.client.post(url, {"activo": "0", "email": "x@x.test"}).status_code, 403)
        self.client.logout()
        for url in urls_get:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertFalse(PartnerStore.objects.exists())
        self.assertFalse(User.objects.filter(email="x@x.test").exists())

    def test_cambiar_el_estado_solo_por_post(self):
        self.assertEqual(self.client.get(reverse("estado_comercio", args=[self.walmart.pk])).status_code, 405)
