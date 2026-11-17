from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reviews.models import Reviews

from .models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
    Stores,
)
from .views import buscar_variantes_por_nombre, obtener_precios_por_gtin

# Los modelos son managed = False (las tablas viven en Supabase),
# así que en la base de pruebas hay que crear las tablas a mano.
MODELOS = [
    Brands,
    Categories,
    Currencies,
    Stores,
    Products,
    ProductVariants,
    ProductImages,
    Prices,
    Reviews,
]


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
        ahora = timezone.now()
        marca = Brands.objects.create(
            name="Dos Pinos",
            slug="dos-pinos",
            logo_url="https://img.test/dos-pinos.png",
            created_at=ahora,
            updated_at=ahora,
        )
        categoria = Categories.objects.create(
            name="Lácteos",
            created_at=ahora,
            updated_at=ahora,
        )
        cls.producto = Products.objects.create(
            name="Leche entera 1L",
            description="Leche entera pasteurizada.",
            brand=marca,
            category=categoria,
            created_at=ahora,
            updated_at=ahora,
        )
        cls.variante = ProductVariants.objects.create(
            product=cls.producto,
            gtin="7441001234567",
            name="Leche entera 1L",
            created_at=ahora,
            updated_at=ahora,
        )
        ProductImages.objects.create(
            variant=cls.variante,
            image_url="https://img.test/secundaria.png",
            is_main=False,
            number_image=1,
            created_at=ahora,
            updated_at=ahora,
        )
        ProductImages.objects.create(
            variant=cls.variante,
            image_url="https://img.test/principal.png",
            is_main=True,
            number_image=2,
            created_at=ahora,
            updated_at=ahora,
        )

        moneda = Currencies.objects.create(
            name="Colón costarricense",
            symbol="₡",
            created_at=ahora,
            updated_at=ahora,
        )
        tienda_a = Stores.objects.create(
            name="Tienda A", created_at=ahora, updated_at=ahora
        )
        tienda_b = Stores.objects.create(
            name="Tienda B", created_at=ahora, updated_at=ahora
        )
        tienda_c = Stores.objects.create(
            name="Tienda C", created_at=ahora, updated_at=ahora
        )
        tienda_d = Stores.objects.create(
            name="Tienda D", created_at=ahora, updated_at=ahora
        )
        for tienda, precio, disponible in [
            (tienda_a, 2500, True),
            (tienda_b, 2000, True),
            (tienda_c, 2000, True),
            (tienda_d, 1000, False),
        ]:
            Prices.objects.create(
                id_store=tienda,
                gtin=cls.variante,
                price=precio,
                is_available=disponible,
                created_at=ahora,
                updated_at=ahora,
                currency=moneda,
                product_web_url=f"https://tienda.test/{precio}",
                discount=0,
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
        ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234574",
            name="Leche entera 1L",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "7441001234567")
        self.assertContains(respuesta, "7441001234574")

    def test_busca_variantes_por_nombre_sin_distinguir_mayusculas(self):
        variantes = buscar_variantes_por_nombre("LECHE")

        self.assertEqual(list(variantes), [self.variante])

    def test_filtra_variantes_por_categoria_y_marca(self):
        por_categoria = buscar_variantes_por_nombre(
            "leche", categoria=self.producto.category
        )
        por_marca = buscar_variantes_por_nombre("leche", marca=self.producto.brand)

        self.assertEqual(list(por_categoria), [self.variante])
        self.assertEqual(list(por_marca), [self.variante])
        self.assertFalse(
            buscar_variantes_por_nombre("leche", categoria="Bebidas").exists()
        )
        self.assertFalse(
            buscar_variantes_por_nombre("leche", marca="Marca inexistente").exists()
        )

    def test_obtiene_los_precios_del_mismo_gtin_rankeados(self):
        precios = list(obtener_precios_por_gtin(self.variante.gtin))

        self.assertEqual([precio.price for precio in precios], [2000, 2000, 2500])
        self.assertEqual([precio.ranking for precio in precios], [1, 1, 3])
        self.assertEqual(
            {precio.id_store.name for precio in precios},
            {"Tienda B", "Tienda C", "Tienda A"},
        )

    def test_api_compara_precios_con_filtros_opcionales(self):
        respuesta = self.client.get(
            reverse("comparar_precios"),
            {"nombre": "leche", "categoria": "Lácteos", "marca": "dos-pinos"},
        )

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.json()
        self.assertEqual(contenido["total"], 1)
        self.assertEqual(contenido["resultados"][0]["gtin"], self.variante.gtin)
        self.assertEqual(
            [precio["ranking"] for precio in contenido["resultados"][0]["precios"]],
            [1, 1, 3],
        )

    def test_api_exige_el_nombre_para_comparar(self):
        respuesta = self.client.get(reverse("comparar_precios"))

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("error", respuesta.json())

    def test_api_devuelve_las_categorias_y_marcas_para_filtrar(self):
        respuesta = self.client.get(reverse("filtros_productos"))

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.json()
        self.assertIn(
            {"id": self.producto.category_id, "name": "Lácteos"},
            contenido["categorias"],
        )
        self.assertIn(
            {"id": self.producto.brand_id, "name": "Dos Pinos", "slug": "dos-pinos"},
            contenido["marcas"],
        )

    def test_producto_sin_imagen_descripcion_ni_variantes(self):
        sencillo = Products.objects.create(
            name="Arroz",
            brand=self.producto.brand,
            category=self.producto.category,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        respuesta = self.client.get(self.url(sencillo.pk))
        self.assertContains(respuesta, "Este producto no tiene imagen.")
        self.assertContains(respuesta, "Sin descripción.")
        self.assertContains(respuesta, "Sin código de barras.")

    def test_producto_inexistente_responde_404(self):
        respuesta = self.client.get(self.url(999))
        self.assertEqual(respuesta.status_code, 404)
