from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reviews.models import Reviews

from .busqueda import buscar_productos
from .models import Brands, Categories, Currencies, Prices, ProductImages, Products, ProductVariants, Stores

# Los modelos son managed = False (las tablas viven en Supabase),
# así que en la base de pruebas hay que crear las tablas a mano.
# accounts_user ya existe porque User sí es managed.
MODELOS = [Brands, Categories, Currencies, Stores, Products, ProductVariants, ProductImages, Prices, Reviews]


def fechas():
    ahora = timezone.now()
    return {"created_at": ahora, "updated_at": ahora}


class CatalogoTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for modelo in MODELOS:
                editor.create_model(modelo)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for modelo in reversed(MODELOS):
                editor.delete_model(modelo)

    @classmethod
    def setUpTestData(cls):
        cls.dos_pinos = Brands.objects.create(name="Dos Pinos", slug="dos-pinos", **fechas())
        cls.heinz = Brands.objects.create(name="Kraft Heinz", slug="kraft-heinz", **fechas())
        cls.lacteos = Categories.objects.create(name="Lácteos", **fechas())
        cls.salsas = Categories.objects.create(name="Salsas", **fechas())

        cls.leche = cls.producto("Leche entera 1L", cls.dos_pinos, cls.lacteos, "Leche entera pasteurizada.")
        cls.variante_leche = cls.variante(cls.leche, "7441001234567")
        cls.ketchup = cls.producto("Salsa de tomate", cls.heinz, cls.salsas)
        cls.variante_ketchup = cls.variante(cls.ketchup, "0013000000765")

    @classmethod
    def producto(cls, nombre, marca, categoria, descripcion=None):
        return Products.objects.create(
            name=nombre, brand=marca, category=categoria, description=descripcion, **fechas()
        )

    @classmethod
    def variante(cls, producto, gtin):
        return ProductVariants.objects.create(product=producto, gtin=gtin, name=producto.name, **fechas())

    @classmethod
    def precio(cls, variante, tienda, precio, descuento="0", disponible=True):
        colones, _ = Currencies.objects.get_or_create(name="colones", symbol="₡", defaults=fechas())
        return Prices.objects.create(
            gtin=variante,
            id_store=tienda,
            price=precio,
            discount=Decimal(descuento),
            is_available=disponible,
            currency=colones,
            product_web_url=f"https://tienda.test/{variante.gtin}",
            **fechas(),
        )

    @classmethod
    def imagen(cls, variante, url, principal=False):
        return ProductImages.objects.create(
            variant=variante, image_url=url, is_main=principal, number_image=1, **fechas()
        )


class DetalleProductoTests(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.imagen(cls.variante_leche, "https://img.test/secundaria.png")
        cls.imagen(cls.variante_leche, "https://img.test/principal.png", principal=True)

    def url(self, pk=None):
        return reverse("detalle_producto", kwargs={"pk": pk or self.leche.pk})

    def test_muestra_todos_los_detalles_del_producto(self):
        respuesta = self.client.get(self.url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "Dos Pinos")
        self.assertContains(respuesta, "Lácteos")
        self.assertContains(respuesta, "Leche entera pasteurizada.")
        self.assertContains(respuesta, "7441001234567")

    def test_muestra_la_imagen_principal(self):
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, 'src="https://img.test/principal.png"')
        self.assertNotContains(respuesta, "secundaria.png")

    def test_muestra_el_codigo_de_barras_de_cada_variante(self):
        self.variante(self.leche, "7441001234574")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "7441001234567")
        self.assertContains(respuesta, "7441001234574")

    def test_producto_sin_imagen_descripcion_ni_variantes(self):
        sencillo = self.producto("Arroz", self.dos_pinos, self.lacteos)
        respuesta = self.client.get(self.url(sencillo.pk))
        self.assertContains(respuesta, "Este producto no tiene imagen.")
        self.assertContains(respuesta, "Sin descripción.")
        self.assertContains(respuesta, "Sin código de barras.")

    def test_producto_inexistente_responde_404(self):
        respuesta = self.client.get(self.url(999))
        self.assertEqual(respuesta.status_code, 404)

    def test_lista_el_precio_de_cada_tienda(self):
        walmart = Stores.objects.create(name="Walmart\n", **fechas())
        automercado = Stores.objects.create(name="Automercado\n", **fechas())
        self.precio(self.variante_leche, walmart, 1760)
        self.precio(self.variante_leche, automercado, 1940, descuento="0.25")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "₡1.760")
        self.assertContains(respuesta, "₡1.455")  # 1940 con 25 % de descuento
        self.assertContains(respuesta, "Descuento de 25 %")
        self.assertContains(respuesta, '<span class="font-bold text-on-surface text-body-lg">Walmart</span>', html=False)
        self.assertContains(respuesta, 'href="https://tienda.test/7441001234567"')

    def test_no_marca_ningun_precio_como_el_mejor(self):
        tienda = Stores.objects.create(name="Walmart", **fechas())
        self.precio(self.variante_leche, tienda, 1760)
        self.assertNotContains(self.client.get(self.url()), "Mejor precio")

    def test_indica_precios_no_disponibles(self):
        tienda = Stores.objects.create(name="Peri", **fechas())
        self.precio(self.variante_leche, tienda, None, disponible=False)
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "No disponible")
        self.assertContains(respuesta, "Sin precio")

    def test_producto_sin_precios_lo_indica(self):
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "Todavía no hay precios registrados")

    def test_orden_precios_descripcion_y_resenas(self):
        html = self.client.get(self.url()).content.decode()
        precios = html.index('id="precios-heading"')
        descripcion = html.index('id="descripcion-heading"')
        resenas = html.index('id="resenas-heading"')
        self.assertLess(precios, descripcion)
        self.assertLess(descripcion, resenas)


class BuscarProductosTests(CatalogoTestCase):
    def buscar(self, palabra):
        return list(buscar_productos(palabra))

    def test_encuentra_por_nombre_del_producto(self):
        self.assertEqual(self.buscar("leche"), [self.leche])

    def test_encuentra_por_nombre_de_la_marca(self):
        self.assertEqual(self.buscar("heinz"), [self.ketchup])

    def test_no_importan_mayusculas_ni_espacios_alrededor(self):
        self.assertEqual(self.buscar("  DOS pinos "), [self.leche])

    def test_palabra_vacia_devuelve_todos_los_productos(self):
        self.assertEqual(self.buscar(""), [self.leche, self.ketchup])

    def test_sin_coincidencias_devuelve_lista_vacia(self):
        self.assertEqual(self.buscar("televisor"), [])


class PaginaBusquedaTests(CatalogoTestCase):
    def test_muestra_los_resultados(self):
        respuesta = self.client.get(reverse("buscar_productos"), {"q": "heinz"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_todavia_no_muestra_precio(self):
        tienda = Stores.objects.create(name="Walmart", **fechas())
        self.precio(self.variante_ketchup, tienda, 1760)
        respuesta = self.client.get(reverse("buscar_productos"), {"q": "heinz"})
        self.assertNotContains(respuesta, "₡")

    def test_avisa_cuando_no_hay_resultados(self):
        respuesta = self.client.get(reverse("buscar_productos"), {"q": "televisor"})
        self.assertContains(respuesta, "No encontramos productos")

    def test_los_resultados_se_paginan_de_24_en_24(self):
        for i in range(25):
            self.producto(f"Yogur {i:02d}", self.dos_pinos, self.lacteos)
        primera = self.client.get(reverse("buscar_productos"), {"q": "yogur"})
        self.assertEqual(len(primera.context["productos"]), 24)
        self.assertContains(primera, "Página 1 de 2")
        segunda = self.client.get(reverse("buscar_productos"), {"q": "yogur", "pagina": 2})
        self.assertEqual(len(segunda.context["productos"]), 1)

    def test_la_pantalla_principal_muestra_los_productos(self):
        cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse("inicio_cliente"))
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertContains(respuesta, "Leche entera 1L")
