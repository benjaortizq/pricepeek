from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from products.models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductVariants,
    Products,
    Stores,
)

from .alertas import revisar_alertas_de_baja_de_precio
from .models import WishlistItem


class AlertasDeBajaDePrecioTests(TestCase):
    modelos_sin_migracion = [Brands, Categories, Currencies, Stores, Products, ProductVariants, Prices]

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
        ahora = timezone.now()
        cls.colones = Currencies.objects.create(id=1, name="Colón", symbol="₡", created_at=ahora, updated_at=ahora)
        cls.dolares = Currencies.objects.create(id=2, name="Dólar", symbol="$", created_at=ahora, updated_at=ahora)
        cls.automercado = Stores.objects.create(name="Automercado", created_at=ahora, updated_at=ahora)
        cls.walmart = Stores.objects.create(name="Walmart", created_at=ahora, updated_at=ahora)
        marca = Brands.objects.create(name="Dos Pinos", slug="dos-pinos", created_at=ahora, updated_at=ahora)
        categoria = Categories.objects.create(name="Lácteos", created_at=ahora, updated_at=ahora)
        cls.producto = Products.objects.create(
            name="Leche entera 1L", brand=marca, category=categoria, created_at=ahora, updated_at=ahora
        )
        cls.variante = ProductVariants.objects.create(
            product=cls.producto, gtin="4006381333931", name="Leche", created_at=ahora, updated_at=ahora
        )
        cls.cliente = User.objects.create_user(email="ana@example.com", password="Clave2026segura", first_name="Ana")

    def setUp(self):
        self.item = self.guardar_en_la_lista(self.cliente, baseline=2000)

    def guardar_en_la_lista(self, cliente, variante=None, baseline=None):
        return WishlistItem.objects.create(
            user=cliente, variant=variante or self.variante, currency=self.colones, baseline_price=baseline
        )

    def poner_precio(self, tienda, precio, descuento="0.00", disponible=True, moneda=None, variante=None):
        ahora = timezone.now()
        variante = variante or self.variante
        Prices.objects.update_or_create(
            id_store=tienda,
            gtin=variante,
            defaults={
                "price": precio,
                "discount": Decimal(descuento),
                "is_available": disponible,
                "currency": moneda or self.colones,
                "product_web_url": "https://tienda.test/leche",
                "created_at": ahora,
                "updated_at": ahora,
            },
        )

    def baseline(self):
        self.item.refresh_from_db()
        return self.item.baseline_price

    def test_envia_un_correo_cuando_el_precio_mas_bajo_baja(self):
        self.poner_precio(self.automercado, 1500)
        resultado = revisar_alertas_de_baja_de_precio()

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["ana@example.com"])
        self.assertIn("Bajó el precio de un producto", correo.subject)
        self.assertIn("Hola Ana", correo.body)
        self.assertIn("Leche entera 1L", correo.body)
        self.assertIn("₡2.000", correo.body)
        self.assertIn("₡1.500", correo.body)
        self.assertIn("Automercado", correo.body)
        self.assertIn(reverse("detalle_producto", kwargs={"pk": self.producto.pk}), correo.body)
        self.assertIn(reverse("editar_perfil"), correo.body)
        self.assertEqual((resultado.correos_enviados, resultado.productos_con_baja, resultado.errores), (1, 1, 0))

    def test_registra_el_nuevo_precio_y_el_aviso(self):
        self.poner_precio(self.automercado, 1500)
        revisar_alertas_de_baja_de_precio()
        self.item.refresh_from_db()
        self.assertEqual(self.item.baseline_price, 1500)
        self.assertEqual(self.item.last_notified_price, 1500)
        self.assertIsNotNone(self.item.last_notified_at)

    def test_no_vuelve_a_avisar_por_la_misma_baja(self):
        self.poner_precio(self.automercado, 1500)
        revisar_alertas_de_baja_de_precio()
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 1)

    def test_no_avisa_si_el_precio_no_cambia(self):
        self.poner_precio(self.automercado, 2000)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)

    def test_si_el_precio_sube_no_avisa_y_la_siguiente_baja_se_compara_con_el_ultimo_precio(self):
        self.poner_precio(self.automercado, 2400)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.baseline(), 2400)

        self.poner_precio(self.automercado, 2200)  # es más que el 2000 original, pero bajó
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("₡2.400", mail.outbox[0].body)
        self.assertIn("₡2.200", mail.outbox[0].body)

    def test_la_primera_revision_solo_registra_el_precio(self):
        self.item.baseline_price = None
        self.item.save()
        self.poner_precio(self.automercado, 1800)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.baseline(), 1800)

    def test_usa_el_precio_final_con_descuento_y_la_tienda_mas_barata(self):
        self.poner_precio(self.automercado, 2000, descuento="0.25")  # 1.500 finales
        self.poner_precio(self.walmart, 1900)
        revisar_alertas_de_baja_de_precio()
        self.assertIn("₡1.500 en Automercado", mail.outbox[0].body)
        self.assertEqual(self.baseline(), 1500)

    def test_ignora_precios_no_disponibles_nulos_y_de_otra_moneda(self):
        self.poner_precio(self.automercado, 900, disponible=False)
        self.poner_precio(self.walmart, 800, moneda=self.dolares)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.baseline(), 2000)

    def test_sin_precios_disponibles_conserva_el_ultimo_precio(self):
        self.poner_precio(self.automercado, 1500, disponible=False)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.baseline(), 2000)

    def test_respeta_el_interruptor_de_alertas_del_perfil(self):
        self.poner_precio(self.automercado, 1500)
        User.objects.filter(pk=self.cliente.pk).update(active_alerts=False)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.baseline(), 2000)

    def test_respeta_las_alertas_desactivadas_en_el_producto(self):
        self.poner_precio(self.automercado, 1500)
        WishlistItem.objects.filter(pk=self.item.pk).update(alert_enabled=False)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)

    def test_una_cuenta_suspendida_no_recibe_alertas(self):
        self.poner_precio(self.automercado, 1500)
        User.objects.filter(pk=self.cliente.pk).update(is_active=False)
        revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 0)

    def test_un_solo_correo_por_cliente_con_todos_sus_productos_que_bajaron(self):
        ahora = timezone.now()
        otra = ProductVariants.objects.create(
            product=self.producto, gtin="036000291452", name="Leche light", created_at=ahora, updated_at=ahora
        )
        otro_item = self.guardar_en_la_lista(self.cliente, variante=otra, baseline=1000)
        self.poner_precio(self.automercado, 1500)
        self.poner_precio(self.walmart, 700, variante=otra)
        resultado = revisar_alertas_de_baja_de_precio()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Bajó el precio de 2 productos", mail.outbox[0].subject)
        self.assertIn("₡1.500", mail.outbox[0].body)
        self.assertIn("₡700", mail.outbox[0].body)
        self.assertEqual((resultado.correos_enviados, resultado.productos_con_baja), (1, 2))
        otro_item.refresh_from_db()
        self.assertEqual(otro_item.baseline_price, 700)

    def test_si_falla_el_envio_no_se_pierde_la_baja_ni_se_detiene_a_los_demas(self):
        luis = User.objects.create_user(email="luis@example.com", password="Clave2026segura")
        item_luis = self.guardar_en_la_lista(luis, baseline=2000)
        self.poner_precio(self.automercado, 1500)

        with patch("wishlist.alertas.send_mail", side_effect=[Exception("SMTP caído"), 1]) as enviar:
            with self.assertLogs("wishlist.alertas", level="ERROR"):
                resultado = revisar_alertas_de_baja_de_precio()

        self.assertEqual(enviar.call_count, 2)
        self.assertEqual((resultado.errores, resultado.correos_enviados), (1, 1))
        self.item.refresh_from_db()
        item_luis.refresh_from_db()
        self.assertEqual(self.item.baseline_price, 2000)  # ana: se reintenta en la próxima revisión
        self.assertEqual(item_luis.baseline_price, 1500)  # luis: sí se avisó

    def test_comando_de_la_revision_periodica(self):
        self.poner_precio(self.automercado, 1500)
        salida = StringIO()
        call_command("enviar_alertas_de_precio", stdout=salida)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Correos enviados: 1", salida.getvalue())

    def test_sin_listas_de_deseos_no_hace_nada(self):
        WishlistItem.objects.all().delete()
        resultado = revisar_alertas_de_baja_de_precio()
        self.assertEqual(resultado.revisados, 0)
        self.assertEqual(len(mail.outbox), 0)
