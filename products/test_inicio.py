"""Pruebas del inicio con el diseño de frontend/html/index.html."""

from decimal import Decimal

from django.urls import reverse

from accounts.models import User

from .models import Prices, Stores
from .ofertas import icono_de_categoria, mejores_ofertas
from .tests import CatalogoTestCase, fechas


class InicioTestCase(CatalogoTestCase):
    """La leche se vende en tres comercios; la salsa, en uno solo."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.walmart = Stores.objects.create(name="Walmart\n", **fechas())
        cls.peri = Stores.objects.create(name="Peri", **fechas())
        cls.gollo = Stores.objects.create(name="Gollo", **fechas())
        cls.precio(cls.variante_leche, cls.walmart, 2000)
        cls.precio(cls.variante_leche, cls.peri, 1500)
        cls.precio(cls.variante_leche, cls.gollo, 2500, descuento="0.20")  # final 2000
        cls.precio(cls.variante_ketchup, cls.walmart, 1760)
        cls.cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")

    def entrar(self):
        self.client.force_login(self.cliente)
        return self.client.get(reverse("inicio_cliente"))


class MejoresOfertasTests(InicioTestCase):
    def test_solo_los_productos_con_precio_en_dos_o_mas_comercios(self):
        ofertas = mejores_ofertas()
        self.assertEqual([oferta["variante"].gtin for oferta in ofertas], [self.variante_leche.gtin])

    def test_el_mas_barato_primero_y_el_ahorro_contra_el_mas_caro(self):
        oferta = mejores_ofertas()[0]
        self.assertEqual(oferta["mejor"].id_store, self.peri)
        self.assertEqual(oferta["ahorro"], Decimal("500"))
        self.assertEqual(oferta["porcentaje"], 25)  # 500 de 2000
        self.assertEqual(oferta["comercios"], 3)
        self.assertEqual([otro["diferencia"] for otro in oferta["otros"]], [Decimal("500"), Decimal("500")])

    def test_no_cuentan_los_precios_no_disponibles(self):
        Prices.objects.filter(id_store=self.peri).update(is_available=False)
        Prices.objects.filter(id_store=self.gollo).update(is_available=False)
        self.assertEqual(mejores_ofertas(), [])

    def test_si_todos_cobran_lo_mismo_no_es_oferta(self):
        Prices.objects.filter(gtin=self.variante_leche).update(price=2000, discount=Decimal("0"))
        self.assertEqual(mejores_ofertas(), [])

    def test_van_primero_las_de_mayor_diferencia(self):
        self.precio(self.variante_ketchup, self.peri, 880)  # la mitad: 50 %
        self.assertEqual(
            [oferta["variante"].gtin for oferta in mejores_ofertas()],
            [self.variante_ketchup.gtin, self.variante_leche.gtin],
        )


class PaginaDeInicioTests(InicioTestCase):
    def test_tiene_las_secciones_del_diseno(self):
        respuesta = self.entrar()
        for texto in (
            "Busca, compara y ahorra",
            "Buscar precios",
            "Mejores ofertas del día",
            "¿Cómo funciona PricePeek?",
            "Garantía de Imparcialidad y Transparencia",
        ):
            self.assertContains(respuesta, texto)

    def test_la_tarjeta_de_la_oferta(self):
        respuesta = self.entrar()
        self.assertContains(respuesta, "Mejor precio en Peri")
        self.assertContains(respuesta, "Ahorro de ₡500 (25%)")
        self.assertContains(respuesta, "+₡500")
        self.assertContains(respuesta, "Comparativa de 3 comercios")
        self.assertContains(respuesta, f'href="{reverse("detalle_producto", args=[self.leche.pk])}"')
        self.assertContains(respuesta, "Verificado hoy")

    def test_el_buscador_lleva_a_la_busqueda(self):
        respuesta = self.entrar()
        self.assertContains(respuesta, f'action="{reverse("buscar_productos")}"')
        self.assertContains(respuesta, 'placeholder="Buscar por producto, marca o código de barras"')

    def test_las_categorias_llevan_a_la_busqueda_filtrada(self):
        respuesta = self.entrar()
        self.assertContains(respuesta, f'{reverse("buscar_productos")}?categoria={self.lacteos.pk}')
        self.assertContains(respuesta, "Todo el catálogo")
        self.assertContains(respuesta, "2 productos")

    def test_el_encabezado_no_repite_el_buscador(self):
        respuesta = self.entrar()
        self.assertNotContains(respuesta, "Buscar producto o marca...")
        busqueda = self.client.get(reverse("buscar_productos"), {"q": "leche"})
        self.assertContains(busqueda, "Buscar producto o marca...")

    def test_sin_ofertas_lo_dice(self):
        Prices.objects.filter(id_store__in=[self.peri, self.gollo]).delete()
        self.assertContains(self.entrar(), "Todavía no hay productos con precio en dos o más comercios para comparar.")

    def test_la_empresa_ve_el_mismo_inicio(self):
        empresa = User.objects.create_user(email="empresa@correo.com", password="Clave2026segura", role="enterprise")
        self.client.force_login(empresa)
        self.assertContains(self.client.get(reverse("inicio_empresa")), "Mejores ofertas del día")

    def test_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.entrar()
        self.assertContains(respuesta, "Search, compare and save")
        self.assertContains(respuesta, "Best deals of the day")


class IconosDeCategoriaTests(CatalogoTestCase):
    def test_iconos(self):
        self.assertEqual(icono_de_categoria("Electrodomésticos"), "kitchen")
        self.assertEqual(icono_de_categoria("Abarrotes"), "shopping_basket")
        self.assertEqual(icono_de_categoria("Artículos para el hogar"), "chair")
        self.assertEqual(icono_de_categoria("Higiene"), "clean_hands")
        self.assertEqual(icono_de_categoria("Lácteos"), "category")
