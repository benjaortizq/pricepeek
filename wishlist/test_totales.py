from decimal import Decimal

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
    ProductImages,
    ProductVariants,
    Products,
    Stores,
)

from .models import WishlistItem
from .totales import totales_por_tienda

LECHE, ARROZ, ATUN = "4006381333931", "036000291452", "96385074"


class TotalesBase(TestCase):
    modelos_sin_migracion = [
        Brands, Categories, Currencies, Stores, Products, ProductVariants, ProductImages, Prices,
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
        ahora = timezone.now()
        cls.colones = Currencies.objects.create(id=1, name="Colón", symbol="₡", created_at=ahora, updated_at=ahora)
        cls.dolares = Currencies.objects.create(id=2, name="Dólar", symbol="$", created_at=ahora, updated_at=ahora)
        cls.automercado = Stores.objects.create(name="Automercado", created_at=ahora, updated_at=ahora)
        cls.walmart = Stores.objects.create(name="Walmart", created_at=ahora, updated_at=ahora)
        cls.gollo = Stores.objects.create(name="Gollo", created_at=ahora, updated_at=ahora)
        marca = Brands.objects.create(name="Marca", slug="marca", created_at=ahora, updated_at=ahora)
        categoria = Categories.objects.create(name="Categoría", created_at=ahora, updated_at=ahora)
        cls.variantes = {}
        for nombre, gtin in (("Leche", LECHE), ("Arroz", ARROZ), ("Atún", ATUN)):
            producto = Products.objects.create(
                name=nombre, brand=marca, category=categoria, created_at=ahora, updated_at=ahora
            )
            cls.variantes[gtin] = ProductVariants.objects.create(
                product=producto, gtin=gtin, name=nombre, created_at=ahora, updated_at=ahora
            )
        cls.cliente = User.objects.create_user(email="ana@example.com", password="Clave2026segura")

    def setUp(self):
        for gtin in (LECHE, ARROZ, ATUN):
            self.guardar(gtin)

    def guardar(self, gtin, moneda=None):
        return WishlistItem.objects.create(
            user=self.cliente, variant=self.variantes[gtin], currency=moneda or self.colones
        )

    def poner(self, tienda, gtin, precio, descuento="0.00", disponible=True, moneda=None):
        ahora = timezone.now()
        Prices.objects.update_or_create(
            id_store=tienda,
            gtin=self.variantes[gtin],
            defaults={
                "price": precio,
                "discount": Decimal(descuento),
                "is_available": disponible,
                "currency": moneda or self.colones,
                "product_web_url": "https://tienda.test/producto",
                "created_at": ahora,
                "updated_at": ahora,
            },
        )

    def poner_los_tres(self, tienda, leche, arroz, atun):
        for gtin, precio in ((LECHE, leche), (ARROZ, arroz), (ATUN, atun)):
            self.poner(tienda, gtin, precio)

    def comparar(self):
        items = list(
            WishlistItem.objects.filter(user=self.cliente).select_related(
                "variant__product", "currency"
            )
        )
        return totales_por_tienda(items)

    def filas(self):
        (comparativa,) = self.comparar()
        return {fila.tienda: fila for fila in comparativa.tiendas}


class TotalesPorTiendaTests(TotalesBase):
    def test_suma_una_unidad_de_cada_producto_en_cada_comercio(self):
        self.poner_los_tres(self.automercado, 1000, 2000, 500)
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        filas = self.filas()
        self.assertEqual(filas["Automercado"].total, 3500)
        self.assertEqual(filas["Walmart"].total, 3400)
        self.assertEqual(filas["Walmart"].disponibles, 3)

    def test_destaca_el_total_mas_bajo_entre_los_comercios_que_lo_tienen_todo(self):
        self.poner_los_tres(self.automercado, 1000, 2000, 500)
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        filas = self.filas()
        self.assertTrue(filas["Walmart"].mas_barata)
        self.assertFalse(filas["Automercado"].mas_barata)

    def test_un_comercio_incompleto_nunca_se_destaca_aunque_su_total_sea_menor(self):
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        self.poner(self.gollo, LECHE, 800)
        self.poner(self.gollo, ARROZ, 1800)  # total 2.600, pero le falta el atún
        filas = self.filas()
        self.assertLess(filas["Gollo"].total, filas["Walmart"].total)
        self.assertFalse(filas["Gollo"].mas_barata)
        self.assertTrue(filas["Walmart"].mas_barata)

    def test_indica_cuantos_y_cuales_productos_no_tiene_disponibles(self):
        self.poner(self.gollo, LECHE, 800)
        fila = self.filas()["Gollo"]
        self.assertEqual(fila.disponibles, 1)
        self.assertFalse(fila.completa)
        self.assertCountEqual(fila.faltantes, ["Arroz", "Atún"])

    def test_si_hay_empate_se_destacan_todos_los_empatados(self):
        self.poner_los_tres(self.automercado, 1000, 2000, 500)
        self.poner_los_tres(self.walmart, 1000, 2000, 500)
        filas = self.filas()
        self.assertTrue(filas["Automercado"].mas_barata and filas["Walmart"].mas_barata)

    def test_si_ningun_comercio_lo_tiene_todo_no_destaca_ninguno(self):
        self.poner(self.automercado, LECHE, 1000)
        self.poner(self.walmart, ARROZ, 1000)
        (comparativa,) = self.comparar()
        self.assertFalse(comparativa.hay_completa)
        self.assertFalse(any(fila.mas_barata for fila in comparativa.tiendas))

    def test_usa_el_precio_final_con_descuento(self):
        self.poner(self.automercado, LECHE, 1000, descuento="0.50")
        self.assertEqual(self.filas()["Automercado"].total, 500)

    def test_los_precios_no_disponibles_o_nulos_cuentan_como_faltantes(self):
        self.poner(self.automercado, LECHE, 1000)
        self.poner(self.automercado, ARROZ, 2000, disponible=False)
        self.poner(self.automercado, ATUN, None)
        fila = self.filas()["Automercado"]
        self.assertEqual((fila.total, fila.disponibles), (1000, 1))
        self.assertCountEqual(fila.faltantes, ["Arroz", "Atún"])

    def test_ordena_primero_los_comercios_completos_de_menor_a_mayor_total(self):
        self.poner_los_tres(self.automercado, 1000, 2000, 500)
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        self.poner(self.gollo, LECHE, 100)
        (comparativa,) = self.comparar()
        self.assertEqual([fila.tienda for fila in comparativa.tiendas], ["Walmart", "Automercado", "Gollo"])

    def test_no_lista_comercios_que_no_ofrecen_ningun_producto_de_la_lista(self):
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        self.assertEqual(list(self.filas()), ["Walmart"])

    def test_cada_moneda_se_compara_por_separado(self):
        WishlistItem.objects.filter(variant=self.variantes[ATUN]).delete()
        self.guardar(ATUN, moneda=self.dolares)
        self.poner(self.walmart, LECHE, 1000)
        self.poner(self.walmart, ARROZ, 2000)
        self.poner(self.automercado, ATUN, 5, moneda=self.dolares)
        comparativas = self.comparar()
        self.assertEqual(len(comparativas), 2)
        por_moneda = {c.moneda.symbol: c for c in comparativas}
        self.assertEqual(por_moneda["₡"].productos, 2)
        self.assertEqual(por_moneda["$"].productos, 1)
        self.assertEqual(por_moneda["₡"].tiendas[0].total, 3000)
        self.assertEqual(por_moneda["$"].tiendas[0].total, 5)

    def test_lista_vacia_no_devuelve_comparativas(self):
        self.assertEqual(totales_por_tienda([]), [])


class ListaDeDeseosConTotalesTests(TotalesBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("wishlist:lista")
        self.client.force_login(self.cliente)

    def test_muestra_el_total_por_comercio_y_destaca_la_mejor_opcion_completa(self):
        self.poner_los_tres(self.automercado, 1000, 2000, 500)
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        self.poner(self.gollo, LECHE, 800)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Total de tu lista por comercio")
        self.assertContains(respuesta, "₡3.400")
        self.assertContains(respuesta, "₡3.500")
        self.assertContains(respuesta, "Opción completa más barata", count=1)
        self.assertContains(respuesta, "Le faltan 2 productos")
        self.assertContains(respuesta, "Tiene todos los productos de tu lista.")

    def test_usa_singular_cuando_falta_un_solo_producto(self):
        self.poner(self.gollo, LECHE, 800)
        self.poner(self.gollo, ARROZ, 900)
        self.assertContains(self.client.get(self.url), "Le falta 1 producto: Atún.")

    def test_avisa_cuando_ningun_comercio_ofrece_todo(self):
        self.poner(self.walmart, LECHE, 900)
        self.assertContains(self.client.get(self.url), "Ningún comercio ofrece todos los productos de tu lista.")

    def test_avisa_cuando_todavia_no_hay_precios(self):
        self.assertContains(self.client.get(self.url), "Todavía no hay precios disponibles para comparar.")

    def test_la_lista_vacia_no_muestra_los_totales(self):
        WishlistItem.objects.all().delete()
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Tu lista de deseos está vacía")
        self.assertNotContains(respuesta, "Total de tu lista por comercio")

    def test_cada_cliente_solo_ve_los_totales_de_su_lista(self):
        self.poner_los_tres(self.walmart, 900, 1900, 600)
        otro = User.objects.create_user(email="luis@example.com", password="Clave2026segura")
        self.client.force_login(otro)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Tu lista de deseos está vacía")
        self.assertNotContains(respuesta, "₡3.400")

    def test_el_visitante_es_enviado_a_iniciar_sesion(self):
        self.client.logout()
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
