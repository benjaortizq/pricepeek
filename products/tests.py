from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .models import Brand, Category, Product, ProductImage, ProductVariant

# Los modelos son managed = False (las tablas viven en Supabase),
# así que en la base de pruebas hay que crear las tablas a mano.
MODELOS = [Brand, Category, Product, ProductVariant, ProductImage]


class DetalleProductoTests(TestCase):
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
        marca = Brand.objects.create(
            name="Dos Pinos", slug="dos-pinos", logo_url="https://img.test/dos-pinos.png"
        )
        categoria = Category.objects.create(name="Lácteos")
        cls.producto = Product.objects.create(
            id=1,
            name="Leche entera 1L",
            description="Leche entera pasteurizada.",
            brand=marca,
            category=categoria,
        )
        cls.variante = ProductVariant.objects.create(product=cls.producto, gtin="7441001234567")
        ProductImage.objects.create(
            product=cls.producto,
            variant=cls.variante,
            image_url="https://img.test/secundaria.png",
        )
        ProductImage.objects.create(
            product=cls.producto,
            variant=cls.variante,
            image_url="https://img.test/principal.png",
            is_main=True,
        )

    def url(self, pk=None):
        return reverse("detalle_producto", kwargs={"pk": pk or self.producto.pk})

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
        ProductVariant.objects.create(product=self.producto, gtin="7441001234574")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "7441001234567")
        self.assertContains(respuesta, "7441001234574")

    def test_producto_sin_imagen_descripcion_ni_variantes(self):
        sencillo = Product.objects.create(
            id=2, name="Arroz", brand=self.producto.brand, category=self.producto.category
        )
        respuesta = self.client.get(self.url(sencillo.pk))
        self.assertContains(respuesta, "Este producto no tiene imagen.")
        self.assertContains(respuesta, "Sin descripción.")
        self.assertContains(respuesta, "Sin código de barras.")

    def test_producto_inexistente_responde_404(self):
        respuesta = self.client.get(self.url(999))
        self.assertEqual(respuesta.status_code, 404)
