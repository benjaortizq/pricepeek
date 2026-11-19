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
        cls.dos_pinos = marca
        cls.lacteos = categoria
        cls.producto = Products.objects.create(
            name="Leche entera 1L",
            description="Leche entera pasteurizada.",
            brand=marca,
            category=categoria,
            created_at=ahora,
            updated_at=ahora,
        )
        cls.leche = cls.producto
        cls.variante = ProductVariants.objects.create(
            product=cls.producto,
            gtin="7441001234567",
            name="Leche entera 1L",
            created_at=ahora,
            updated_at=ahora,
        )
        cls.variante_leche = cls.variante
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

        cls.heinz = Brands.objects.create(
            name="Kraft Heinz",
            slug="kraft-heinz",
            logo_url="https://img.test/kraft-heinz.png",
            created_at=ahora,
            updated_at=ahora,
        )
        cls.salsas = Categories.objects.create(
            name="Salsas",
            created_at=ahora,
            updated_at=ahora,
        )
        cls.ketchup = Products.objects.create(
            name="Salsa de tomate",
            description="Salsa de tomate Ketchup.",
            brand=cls.heinz,
            category=cls.salsas,
            created_at=ahora,
            updated_at=ahora,
        )
        cls.variante_ketchup = ProductVariants.objects.create(
            product=cls.ketchup,
            gtin="7441009876543",
            name="Salsa de tomate",
            created_at=ahora,
            updated_at=ahora,
        )

        cls.moneda = Currencies.objects.create(
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
                currency=cls.moneda,
                product_web_url=f"https://tienda.test/{precio}",
                discount=0,
            )

    def url(self, pk=None):
        return reverse("detalle_producto", kwargs={"pk": pk or self.producto.pk})

    def precio(self, variante, tienda, precio, descuento=0, disponible=True):
        return Prices.objects.create(
            id_store=tienda,
            gtin=variante,
            price=precio,
            is_available=disponible,
            created_at=timezone.now(),
            updated_at=timezone.now(),
            currency=self.moneda,
            product_web_url=f"https://tienda.test/{variante.gtin}",
            discount=Decimal(str(descuento)),
        )

    def crear_producto(self, nombre, marca, categoria):
        return Products.objects.create(
            name=nombre,
            description="",
            brand=marca,
            category=categoria,
            **fechas(),
        )

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

    def test_muestra_las_tiendas_y_el_porcentaje_sobre_el_minimo(self):
        walmart = Stores.objects.create(name="Walmart\n", **fechas())
        automercado = Stores.objects.create(name="Automercado\n", **fechas())
        self.precio(self.variante, walmart, 1760)
        self.precio(self.variante, automercado, 1940, descuento="0.25")
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "₡1.455")
        self.assertEqual(respuesta.content.decode().count("₡1.455"), 1)
        self.assertContains(respuesta, "₡1.760")
        self.assertContains(respuesta, "+₡305 (+21%)")
        self.assertContains(respuesta, "25 % de descuento")
        self.assertContains(respuesta, "Automercado")
        self.assertContains(respuesta, "Walmart")
        self.assertContains(respuesta, 'href="https://tienda.test/7441001234567"')
        grupos = respuesta.context["grupos_precios"]
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["mejor"].final, 1455)
        self.assertEqual(grupos[0]["mejor"].tienda, "Automercado")
        self.assertEqual(len(grupos[0]["opciones"]), 5)

    def test_destaca_un_solo_mejor_precio_disponible(self):
        respuesta = self.client.get(self.url())

        html = respuesta.content.decode()
        self.assertContains(respuesta, "Mejor precio disponible")
        self.assertEqual(html.count("data-best-price-card"), 1)
        self.assertEqual(html.count("data-best-price-badge"), 1)
        precios = list(respuesta.context["precios"])
        disponibles = [precio for precio in precios if precio.is_available]
        self.assertEqual(
            [precio.final for precio in disponibles],
            sorted(precio.final for precio in disponibles),
        )
        self.assertTrue(disponibles[0].es_mejor)
        self.assertEqual(sum(precio.es_mejor for precio in precios), 1)
        self.assertEqual(disponibles[0].diferencia_vs_minimo, Decimal("0"))
        mas_caro = next(precio for precio in disponibles if precio.final == 2500)
        self.assertEqual(mas_caro.diferencia_vs_minimo, Decimal("500"))
        self.assertAlmostEqual(float(mas_caro.diferencia_porcentaje), 25.0, places=2)
        self.assertContains(respuesta, "+₡500 (+25%)")
        grupos = respuesta.context["grupos_precios"]
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["mejor"].final, 2000)
        self.assertEqual(len(grupos[0]["opciones"]), 3)

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

        html = respuesta.content.decode()
        self.assertEqual(html.count("data-best-price-card"), 2)
        self.assertEqual(html.count("data-best-price-badge"), 2)
        self.assertEqual(html.count('role="tab"'), 2)
        self.assertEqual(html.count("data-gtin-panel="), 2)
        precios = respuesta.context["precios"]
        mejores = {precio.gtin_id for precio in precios if precio.es_mejor}
        self.assertEqual(mejores, {self.variante.gtin, otra_variante.gtin})
        self.assertEqual(
            [precio.gtin_id for precio in precios],
            [self.variante.gtin] * 4 + [otra_variante.gtin],
        )
        grupos = {grupo["gtin"]: grupo for grupo in respuesta.context["grupos_precios"]}
        self.assertEqual(len(grupos), 2)
        self.assertEqual(grupos[self.variante.gtin]["mejor"].final, 2000)
        self.assertEqual(grupos[otra_variante.gtin]["mejor"].final, 1800)
        self.assertEqual(len(grupos[self.variante.gtin]["opciones"]), 3)
        self.assertEqual(len(grupos[otra_variante.gtin]["opciones"]), 0)

    def test_el_porcentaje_se_calcula_contra_el_minimo_del_mismo_gtin(self):
        otra_variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234581",
            name=self.producto.name,
            **fechas(),
        )
        tienda_f = Stores.objects.create(name="Tienda F", **fechas())
        tienda_g = Stores.objects.create(name="Tienda G", **fechas())
        self.precio(otra_variante, tienda_f, 1800)
        self.precio(otra_variante, tienda_g, 2160)

        respuesta = self.client.get(self.url())

        grupos = {grupo["gtin"]: grupo for grupo in respuesta.context["grupos_precios"]}
        mas_caro_primero = next(
            precio for precio in grupos[self.variante.gtin]["opciones"]
            if precio.final == 2500
        )
        mas_caro_segundo = grupos[otra_variante.gtin]["opciones"][0]
        self.assertAlmostEqual(float(mas_caro_primero.diferencia_porcentaje), 25.0)
        self.assertAlmostEqual(float(mas_caro_segundo.diferencia_porcentaje), 20.0)
        self.assertContains(respuesta, "+₡500 (+25%)")
        self.assertContains(respuesta, "+₡360 (+20%)")

    def test_indica_precios_no_disponibles(self):
        variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234598",
            name=self.producto.name,
            **fechas(),
        )
        tienda = Stores.objects.create(name="Peri", **fechas())
        self.precio(variante, tienda, None, disponible=False)
        respuesta = self.client.get(self.url())
        self.assertContains(respuesta, "Precio no disponible")
        self.assertContains(respuesta, "No disponible")
        self.assertContains(respuesta, "Sin precio")
        self.assertContains(respuesta, variante.gtin)

    def test_producto_sin_precios_lo_indica(self):
        producto = Products.objects.create(
            name="Arroz",
            brand=self.producto.brand,
            category=self.producto.category,
            **fechas(),
        )
        respuesta = self.client.get(self.url(producto.pk))
        self.assertContains(respuesta, "Todavía no hay precios registrados")

    def test_orden_precios_descripcion_y_resenas(self):
        html = self.client.get(self.url()).content.decode()
        precios = html.index('id="comparativa-gtin"')
        descripcion = html.index('id="descripcion-heading"')
        resenas = html.index('id="resenas-heading"')
        self.assertLess(precios, descripcion)
        self.assertLess(descripcion, resenas)

    def test_no_muestra_la_comparativa_generica_redundante(self):
        respuesta = self.client.get(self.url())

        self.assertNotContains(
            respuesta,
            "Comparativa de precios en comercios de Costa Rica",
        )
        self.assertContains(respuesta, f'id="precio-heading-{self.variante.gtin}"')


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
        producto = self.crear_producto("Producto 2024", marca, categoria)

        productos = buscar_productos_con_filtros(
            "2024", categoria="2024", marca="2024"
        )

        self.assertEqual(list(productos), [producto])

    def test_devuelve_una_variante_distinta_por_gtin(self):
        otra_variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234581",
            name=self.producto.name,
            **fechas(),
        )
        tienda = Stores.objects.create(name="Tienda E", **fechas())
        self.precio(otra_variante, tienda, 1800)

        variantes = buscar_variantes_por_nombre("leche")

        self.assertEqual(
            {variante.gtin for variante in variantes},
            {self.variante.gtin, otra_variante.gtin},
        )

    def test_la_comparacion_conserva_las_opciones_de_cada_gtin(self):
        otra_variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234581",
            name=self.producto.name,
            **fechas(),
        )
        tienda = Stores.objects.create(name="Tienda E", **fechas())
        self.precio(otra_variante, tienda, 1800)

        respuesta = self.client.get(reverse("comparar_precios"), {"nombre": "leche"})

        contenido = respuesta.json()
        self.assertEqual(contenido["total"], 2)
        resultados = {resultado["gtin"]: resultado for resultado in contenido["resultados"]}
        self.assertEqual(
            set(resultados),
            {self.variante.gtin, otra_variante.gtin},
        )
        self.assertEqual(len(resultados[self.variante.gtin]["precios"]), 3)
        self.assertEqual(len(resultados[otra_variante.gtin]["precios"]), 1)
        self.assertEqual(
            [precio["ranking"] for precio in resultados[self.variante.gtin]["precios"]],
            [1, 1, 3],
        )
        self.assertEqual(
            [precio["ranking"] for precio in resultados[otra_variante.gtin]["precios"]],
            [1],
        )


class PaginaBusquedaTests(CatalogoTestCase):
    def crear_variantes_yogur(self, cantidad):
        for i in range(cantidad):
            producto = self.crear_producto(f"Yogur {i:02d}", self.dos_pinos, self.lacteos)
            ProductVariants.objects.create(
                product=producto,
                gtin=f"7441000000{i:04d}",
                name=producto.name,
                **fechas(),
            )

    def test_muestra_los_resultados(self):
        respuesta = self.client.get(reverse("buscar_productos"), {"q": "heinz"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertNotContains(respuesta, "Leche entera 1L")

    def test_muestra_el_precio_mas_bajo_de_cada_variante(self):
        walmart = Stores.objects.create(name="Walmart", **fechas())
        automercado = Stores.objects.create(name="Automercado", **fechas())
        self.precio(self.variante_ketchup, walmart, 1760)
        self.precio(self.variante_ketchup, automercado, 1500)
        respuesta = self.client.get(reverse("buscar_productos"), {"q": "heinz"})
        self.assertContains(respuesta, "Precio más bajo")
        self.assertContains(respuesta, "₡1.500")
        self.assertNotContains(respuesta, "₡1.760")
        self.assertContains(respuesta, self.variante_ketchup.gtin)

    def test_muestra_un_producto_distinto_por_gtin_de_la_misma_familia(self):
        otra_variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234581",
            name=self.producto.name,
            **fechas(),
        )
        tienda = Stores.objects.create(name="Tienda E", **fechas())
        self.precio(otra_variante, tienda, 1800)

        respuesta = self.client.get(reverse("buscar_productos"), {"q": "leche"})

        self.assertEqual(len(respuesta.context["variantes"]), 2)
        self.assertEqual(
            {variante.gtin for variante in respuesta.context["variantes"]},
            {self.variante.gtin, otra_variante.gtin},
        )
        html = respuesta.content.decode()
        self.assertEqual(html.count("data-resultado-gtin="), 2)
        self.assertContains(respuesta, f"#precio-{self.variante.gtin}")
        self.assertContains(respuesta, f"#precio-{otra_variante.gtin}")

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
        self.crear_variantes_yogur(25)
        primera = self.client.get(reverse("buscar_productos"), {"q": "yogur"})
        self.assertEqual(len(primera.context["variantes"]), 24)
        self.assertContains(primera, "Página 1 de 2")
        segunda = self.client.get(reverse("buscar_productos"), {"q": "yogur", "pagina": 2})
        self.assertEqual(len(segunda.context["variantes"]), 1)

    def test_la_paginacion_conserva_categoria_y_marca(self):
        self.crear_variantes_yogur(25)

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
