from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from reviews.models import Reviews
from .busqueda import buscar_productos
from .views import (
    _serializar_precio,
    buscar_productos_con_filtros,
    buscar_variantes_por_nombre,
    obtener_precios_por_gtin,
)

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



# Los modelos son managed = False (las tablas viven en Supabase),
# así que en la base de pruebas hay que crear las tablas a mano.
# accounts_user ya existe porque User sí es managed.
def fechas():
    ahora = timezone.now()
    return {"created_at": ahora, "updated_at": ahora}

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

    def test_serializa_un_descuento_nulo_como_cero(self):
        precio = SimpleNamespace(
            ranking=1,
            id_store=SimpleNamespace(name="Tienda"),
            final_price=Decimal("1000"),
            currency=SimpleNamespace(symbol="₡"),
            discount=None,
            is_available=True,
            product_web_url="https://tienda.test/producto",
        )

        self.assertEqual(_serializar_precio(precio)["descuento"], 0.0)

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

    def test_lista_el_precio_de_cada_tienda(self):
        walmart = Stores.objects.create(name="Walmart\n", **fechas())
        automercado = Stores.objects.create(name="Automercado\n", **fechas())
        self.precio(self.variante_leche, walmart, 1760)
        self.precio(self.variante_leche, automercado, 1940, descuento="0.25")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "₡1.760")
        self.assertContains(respuesta, "₡1.940")
        self.assertContains(respuesta, "Descuento de 25 %")
        self.assertContains(respuesta, '<span class="font-bold text-on-surface text-body-lg">Walmart</span>', html=False)
        self.assertContains(respuesta, 'href="https://tienda.test/7441001234567"')
        html = respuesta.content.decode()
        self.assertLess(html.index("₡1.455"), html.index("₡1.760"))

    def test_destaca_el_mejor_precio_disponible(self):
        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, "Mejor precio")
        self.assertEqual(respuesta.content.decode().count("Mejor precio"), 1)
        precios = respuesta.context["precios"]
        disponibles = [precio for precio in precios if precio.is_available]
        self.assertEqual(
            [precio.final for precio in disponibles],
            sorted(precio.final for precio in disponibles),
        )
        self.assertTrue(disponibles[0].es_mejor)
        self.assertEqual(
            [precio.final for precio in precios],
            [2000, 2000, 2500, 1000],
        )
        self.assertFalse(precios[-1].es_mejor)

    def test_destaca_el_mejor_precio_de_cada_gtin(self):
        otra_variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234581",
            name=self.producto.name,
            **fechas(),
        )
        tienda = Stores.objects.create(name="Tienda E", **fechas())
        self.precio(otra_variante, tienda, 1800)

        respuesta = self.client.get(self.url())

        self.assertEqual(respuesta.content.decode().count("Mejor precio"), 2)
        precios = respuesta.context["precios"]
        mejores = {precio.gtin_id for precio in precios if precio.es_mejor}
        self.assertEqual(mejores, {self.variante.gtin, otra_variante.gtin})
        precios_por_gtin = {}
        for precio in precios:
            precios_por_gtin.setdefault(precio.gtin_id, []).append(precio)
        self.assertEqual(
            [precio.final for precio in precios_por_gtin[self.variante.gtin]],
            [2000, 2000, 2500, 1000],
        )
        self.assertEqual(
            [precio.final for precio in precios_por_gtin[otra_variante.gtin]],
            [1800],
        )

    def test_indica_precios_no_disponibles(self):
        tienda = Stores.objects.create(name="Peri", **fechas())
        self.precio(self.variante_leche, tienda, None, disponible=False)
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "No disponible")
        self.assertContains(respuesta, "Sin precio")

    def test_producto_sin_precios_lo_indica(self):
        producto = Products.objects.create(
            name="Arroz",
            brand=self.dos_pinos,
            category=self.lacteos,
            **fechas(),
        )
        respuesta = self.client.get(self.url(producto.pk))
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

    def test_combina_la_busqueda_con_el_filtro_de_categoria(self):
        productos = buscar_productos_con_filtros("", categoria="Salsas")

        self.assertEqual(list(productos), [self.ketchup])

    def test_combina_la_busqueda_con_el_filtro_de_marca(self):
        productos = buscar_productos_con_filtros("", marca="kraft-heinz")

        self.assertEqual(list(productos), [self.ketchup])

    def test_combina_una_busqueda_no_vacia_con_categoria_y_marca(self):
        productos = buscar_productos_con_filtros(
            "heinz", categoria="Salsas", marca="kraft-heinz"
        )
        sin_coincidencia = buscar_productos_con_filtros(
            "leche", categoria="Salsas", marca="kraft-heinz"
        )

        self.assertEqual(list(productos), [self.ketchup])
        self.assertEqual(list(sin_coincidencia), [])

    def test_filtra_por_nombres_numericos_cuando_no_son_ids(self):
        categoria = Categories.objects.create(name="2024", **fechas())
        marca = Brands.objects.create(name="Marca 2024", slug="2024", **fechas())
        producto = self.producto("Producto 2024", marca, categoria)

        productos = buscar_productos_con_filtros(
            "2024", categoria="2024", marca="2024"
        )

        self.assertEqual(list(productos), [producto])


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

    def test_filtra_los_resultados_por_categoria(self):
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "", "categoria": "Salsas"}
        )

        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_filtra_los_resultados_por_marca(self):
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "", "marca": "kraft-heinz"}
        )

        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_filtra_los_resultados_por_ids_de_categoria_y_marca(self):
        respuesta = self.client.get(
            reverse("buscar_productos"),
            {
                "q": "heinz",
                "categoria": self.salsas.pk,
                "marca": self.heinz.pk,
            },
        )

        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_canonicaliza_los_filtros_para_seleccionar_sus_opciones(self):
        respuesta = self.client.get(
            reverse("buscar_productos"),
            {"q": "heinz", "categoria": "salsas", "marca": "KRAFT-HEINZ"},
        )

        self.assertEqual(
            respuesta.context["categoria_seleccionada"], str(self.salsas.pk)
        )
        self.assertEqual(
            respuesta.context["marca_seleccionada"], str(self.heinz.pk)
        )
        self.assertContains(
            respuesta, f'<option value="{self.salsas.pk}" selected>Salsas</option>'
        )
        self.assertContains(
            respuesta,
            f'<option value="{self.heinz.pk}" selected>Kraft Heinz</option>',
        )

    def test_muestra_las_opciones_de_categoria_y_marca(self):
        respuesta = self.client.get(reverse("buscar_productos"))

        self.assertContains(respuesta, "Todas las categorías")
        self.assertContains(respuesta, "Todas las marcas")
        self.assertContains(respuesta, 'name="categoria"')
        self.assertContains(respuesta, 'name="marca"')

    def test_los_resultados_se_paginan_de_24_en_24(self):
        for i in range(25):
            self.producto(f"Yogur {i:02d}", self.dos_pinos, self.lacteos)
        primera = self.client.get(reverse("buscar_productos"), {"q": "yogur"})
        self.assertEqual(len(primera.context["productos"]), 24)
        self.assertContains(primera, "Página 1 de 2")
        segunda = self.client.get(reverse("buscar_productos"), {"q": "yogur", "pagina": 2})
        self.assertEqual(len(segunda.context["productos"]), 1)

    def test_la_paginacion_conserva_categoria_y_marca(self):
        for i in range(25):
            self.producto(f"Yogur {i:02d}", self.dos_pinos, self.lacteos)

        respuesta = self.client.get(
            reverse("buscar_productos"),
            {
                "q": "yogur",
                "categoria": self.lacteos.pk,
                "marca": self.dos_pinos.pk,
            },
        )

        html = respuesta.content.decode()
        self.assertIn(f"categoria={self.lacteos.pk}", html)
        self.assertIn(f"marca={self.dos_pinos.pk}", html)
        self.assertIn("pagina=2", html)

    def test_la_pantalla_principal_muestra_los_productos(self):
        cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse("inicio_cliente"))
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertContains(respuesta, "Leche entera 1L")
