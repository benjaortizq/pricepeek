from datetime import timedelta
from unittest import mock

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .busqueda import buscar_productos, con_imagen
from .models import ProductView
from .popularidad import DIAS_DE_POPULARIDAD, mas_populares
from .tests import CatalogoTestCase


def esta_hora():
    return timezone.now().replace(minute=0, second=0, microsecond=0)


class RegistrarVisitaTests(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")

    def ver(self, cliente=None, **extra):
        return (cliente or self.client).get(reverse("detalle_producto", args=[self.leche.pk]), **extra)

    def test_ver_el_detalle_guarda_una_visita_del_cliente(self):
        self.client.force_login(self.cliente)
        ahora = esta_hora() + timedelta(minutes=42)
        with mock.patch("products.popularidad.timezone.now", return_value=ahora):
            self.ver()
        visita = ProductView.objects.get()
        self.assertEqual(visita.product_id, self.leche.pk)
        self.assertEqual(visita.visitor, f"u{self.cliente.pk}")
        self.assertEqual(visita.user, self.cliente)
        self.assertEqual(visita.hour, esta_hora())  # sin minutos: una por hora

    def test_recargar_en_la_misma_hora_no_suma(self):
        self.client.force_login(self.cliente)
        for _ in range(3):
            self.ver()
        self.assertEqual(ProductView.objects.count(), 1)

    def test_en_otra_hora_se_guarda_otra_visita(self):
        self.client.force_login(self.cliente)
        for horas in (0, 1):
            with mock.patch("products.popularidad.timezone.now", return_value=esta_hora() + timedelta(hours=horas)):
                self.ver()
        self.assertEqual(ProductView.objects.count(), 2)

    def test_el_anonimo_se_reconoce_por_su_sesion(self):
        self.ver()
        self.ver()  # el mismo anónimo: no suma
        self.ver(Client())  # otro anónimo: sí
        visitas = list(ProductView.objects.all())
        self.assertEqual(len(visitas), 2)
        for visita in visitas:
            self.assertTrue(visita.visitor.startswith("s"))
            self.assertIsNone(visita.user)

    def test_administradores_y_empresas_no_cuentan(self):
        for rol in ("admin", "enterprise"):
            usuario = User.objects.create_user(email=f"{rol}@correo.com", password="Clave2026segura", role=rol)
            self.client.force_login(usuario)
            self.ver()
        self.assertFalse(ProductView.objects.exists())

    def test_los_robots_no_cuentan(self):
        self.ver(HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
        self.ver(HTTP_USER_AGENT="WhatsApp/2.23.20.0")  # vista previa de un enlace compartido
        self.assertFalse(ProductView.objects.exists())

    def test_publicar_una_resena_no_cuenta_como_visita(self):
        self.client.force_login(self.cliente)
        self.client.post(reverse("detalle_producto", args=[self.leche.pk]), {})  # formulario incompleto
        self.assertFalse(ProductView.objects.exists())

    def test_un_producto_que_no_existe_no_guarda_nada(self):
        self.client.get(reverse("detalle_producto", args=[999999]))
        self.assertFalse(ProductView.objects.exists())

    def test_si_el_cliente_borra_su_cuenta_se_borran_sus_visitas(self):
        self.client.force_login(self.cliente)
        self.ver()
        self.cliente.delete()
        self.assertFalse(ProductView.objects.exists())


class MasPopularesTests(CatalogoTestCase):
    def visitas(self, producto, *visitantes, hace=timedelta()):
        for visitante in visitantes:
            ProductView.objects.create(product_id=producto.pk, visitor=visitante, hour=esta_hora() - hace)

    def populares(self):
        return [(producto, producto.popularidad) for producto in mas_populares(buscar_productos(""))]

    def entrar_al_inicio(self):
        cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")
        self.client.force_login(cliente)
        return self.client.get(reverse("inicio_cliente"))

    def test_sin_visitas_quedan_en_orden_alfabetico(self):
        self.assertEqual(self.populares(), [(self.leche, 0), (self.ketchup, 0)])

    def test_primero_el_que_tuvo_mas_visitantes_distintos(self):
        self.visitas(self.leche, "u1")
        self.visitas(self.ketchup, "u1", "sabc")
        self.assertEqual(self.populares(), [(self.ketchup, 2), (self.leche, 1)])

    def test_un_visitante_cuenta_una_vez_aunque_vuelva_en_varias_horas(self):
        for horas in range(5):
            self.visitas(self.leche, "u1", hace=timedelta(hours=horas))
        self.visitas(self.ketchup, "u1", "u2")
        self.assertEqual(self.populares(), [(self.ketchup, 2), (self.leche, 1)])

    def test_las_visitas_de_hace_mas_de_7_dias_no_cuentan(self):
        self.visitas(self.leche, "u1", "u2", "u3", hace=timedelta(days=DIAS_DE_POPULARIDAD, hours=1))
        self.visitas(self.ketchup, "u4")
        self.assertEqual(self.populares(), [(self.ketchup, 1), (self.leche, 0)])

    def test_la_popularidad_no_agrega_consultas(self):
        self.visitas(self.ketchup, "u1")
        with self.assertNumQueries(2):  # los productos (con su popularidad) y las imágenes de todos
            con_imagen(mas_populares(buscar_productos(""))[:12])

    def test_el_inicio_muestra_primero_los_populares(self):
        self.visitas(self.ketchup, "u1")
        respuesta = self.entrar_al_inicio()
        self.assertEqual(respuesta.context["productos"], [self.ketchup, self.leche])
        self.assertContains(respuesta, "Populares esta semana")

    def test_sin_visitas_el_inicio_no_dice_populares(self):
        respuesta = self.entrar_al_inicio()
        self.assertEqual(respuesta.context["productos"], [self.leche, self.ketchup])
        self.assertNotContains(respuesta, "Populares esta semana")
