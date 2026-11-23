from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reviews.models import Reviews


from .correccion import olvidar_vocabulario
from .models import Brands, Categories, Currencies, Prices, ProductImages, Products, ProductVariants, Stores

from .busqueda import buscar_productos, con_imagen, con_imagen_variante
from .views import _serializar_precio, buscar_variantes_por_nombre, obtener_precios_por_gtin

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

    def setUp(self):
        super().setUp()
        olvidar_vocabulario()  # el «¿quiso decir…?» se arma con los productos de cada prueba

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


class DetalleMarcaTests(CatalogoTestCase):
    def url(self, slug="dos-pinos"):
        return reverse("detalle_marca", kwargs={"slug": slug})

    def test_muestra_el_nombre_y_la_descripcion_de_la_marca(self):
        Brands.objects.filter(pk=self.dos_pinos.pk).update(
            description="Productos lácteos de la familia Dos Pinos."
        )

        respuesta = self.client.get(self.url())

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Dos Pinos")
        self.assertContains(respuesta, "Productos lácteos de la familia Dos Pinos.")
        self.assertContains(respuesta, "Sobre la marca")

    def test_muestra_solo_los_productos_de_la_marca(self):
        yogurt = self.producto("Yogur natural", self.dos_pinos, self.lacteos)

        respuesta = self.client.get(self.url())

        self.assertContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "Yogur natural")
        self.assertNotContains(respuesta, "Salsa de tomate")
        self.assertEqual(
            [producto.pk for producto in respuesta.context["productos"]],
            [self.leche.pk, yogurt.pk],
        )

    def test_el_nombre_de_la_marca_en_el_detalle_es_un_enlace(self):
        respuesta = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )

        self.assertContains(respuesta, f'href="{self.url()}"')

    def test_omite_la_descripcion_cuando_la_marca_no_tiene_una(self):
        respuesta = self.client.get(self.url())

        self.assertNotContains(respuesta, "Sobre la marca")

    def test_una_marca_inexistente_responde_404(self):
        respuesta = self.client.get(self.url("marca-inexistente"))

        self.assertEqual(respuesta.status_code, 404)


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

    def test_letras_repetidas_de_mas_o_de_menos(self):
        tutto = Brands.objects.create(name="Tutto", slug="tutto", **fechas())
        bombon = self.producto("Bombón TUTTO de chocolate", tutto, self.salsas)
        galleta = self.producto("Galleta de vainilla", tutto, self.salsas)
        for palabra in ("tuto", "Tutto", "TUTTO", "tUtTo"):
            with self.subTest(palabra=palabra):
                self.assertEqual(self.buscar(palabra), [bombon, galleta])  # por el nombre o por la marca
        self.assertEqual(self.buscar("galeta"), [galleta])

    def test_sin_importar_tildes(self):
        cafe = self.producto("Café molido", self.dos_pinos, self.lacteos)
        pina = self.producto("Jugo de piña", self.dos_pinos, self.lacteos)
        self.assertEqual(self.buscar("cafe"), [cafe])
        self.assertEqual(self.buscar("CAFÉ"), [cafe])
        self.assertEqual(self.buscar("pina"), [pina])
        self.assertEqual(self.buscar("bombón"), [])

    def test_sin_signos(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        refresco = self.producto("Refresco Coca-Cola 600 ml", self.heinz, self.salsas)
        self.assertEqual(self.buscar("mms"), [chocolate])
        self.assertEqual(self.buscar("m&m"), [chocolate])
        self.assertEqual(self.buscar("cocacola"), [refresco])
        self.assertEqual(self.buscar("coca-cola"), [refresco])

    def test_cada_palabra_en_el_nombre_o_la_marca_en_cualquier_orden(self):
        self.assertEqual(self.buscar("leche dos pinos"), [self.leche])
        self.assertEqual(self.buscar("pinos leche"), [self.leche])
        self.assertEqual(self.buscar("leche heinz"), [])

    def test_m_y_m_no_es_cualquier_cosa_con_m(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        self.assertEqual(self.buscar("m&m"), [chocolate])  # no "Salsa de tomate"
        self.assertEqual(self.buscar("mms"), [chocolate])

    def test_primero_lo_que_tiene_el_texto_tal_cual(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        chocolate = self.producto("Chocolate con maní", mars, self.salsas)
        boquita = self.producto("Boquita Yummies", self.dos_pinos, self.salsas)  # "mm" se parece a "m&m"
        self.assertEqual(self.buscar("m&m"), [chocolate, boquita])

    def test_un_espacio_no_cuenta_como_signo(self):
        crema = self.producto("Galletas a la crema", self.dos_pinos, self.lacteos)
        sal = self.producto("Sal de mesa", self.dos_pinos, self.lacteos)
        self.assertEqual(self.buscar("sal"), [sal, self.ketchup])  # "Salsa", pero no "galleta[s a l]a"
        self.assertEqual(self.buscar("galletas"), [crema])

    def test_los_numeros_no_se_estiran(self):
        agua = self.producto("Agua 100 ml", self.dos_pinos, self.lacteos)
        self.assertEqual(self.buscar("100"), [agua])
        self.assertEqual(self.buscar("1000"), [])

    def test_solo_signos_es_como_no_buscar_nada(self):
        self.assertEqual(self.buscar(" - & "), [self.leche, self.ketchup])

    def test_imagen_de_cada_producto_en_una_sola_consulta(self):
        self.imagen(self.variante_leche, "https://img.test/secundaria.png")
        self.imagen(self.variante_leche, "https://img.test/principal.png", principal=True)
        self.imagen(self.variante_ketchup, "https://img.test/ketchup.png")
        self.producto("Yogur natural", self.dos_pinos, self.lacteos)  # sin imagen
        with self.assertNumQueries(2):  # los productos y las imágenes de todos
            productos = con_imagen(buscar_productos(""))
        self.assertEqual(
            [p.imagen_url for p in productos],
            ["https://img.test/principal.png", "https://img.test/ketchup.png", None],
        )

    def test_imagen_de_cada_variante_en_una_sola_consulta(self):
        otra_leche = self.variante(self.leche, "7441001234598")  # misma familia, sin imagen propia
        self.imagen(self.variante_leche, "https://img.test/secundaria.png")
        self.imagen(self.variante_leche, "https://img.test/principal.png", principal=True)
        self.imagen(self.variante_ketchup, "https://img.test/ketchup.png")
        variantes = [self.variante_leche, otra_leche, self.variante_ketchup]
        with self.assertNumQueries(1):  # las imágenes de todas
            variantes = con_imagen_variante(variantes)
        self.assertEqual(
            [v.imagen_url for v in variantes],
            ["https://img.test/principal.png", None, "https://img.test/ketchup.png"],
        )


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
            yogur = self.producto(f"Yogur {i:02d}", self.dos_pinos, self.lacteos)
            self.variante(yogur, f"7441000{i:06d}")  # la búsqueda muestra variantes
        primera = self.client.get(reverse("buscar_productos"), {"q": "yogur"})
        self.assertEqual(len(primera.context["variantes"]), 24)
        self.assertContains(primera, "Página 1 de 2")
        segunda = self.client.get(reverse("buscar_productos"), {"q": "yogur", "pagina": 2})
        self.assertEqual(len(segunda.context["variantes"]), 1)

    def test_la_pagina_busca_sin_tildes_ni_signos_ni_letras_repetidas(self):
        mars = Brands.objects.create(name="M&M's", slug="mms", **fechas())
        cafe = self.variante(self.producto("Café molido", self.dos_pinos, self.lacteos), "7441000999901")
        tutto = self.variante(self.producto("Bombón TUTTO", self.dos_pinos, self.salsas), "7441000999902")
        mms = self.variante(self.producto("Chocolate con maní", mars, self.salsas), "7441000999903")
        for palabra, esperada in (("cafe", cafe), ("tuto", tutto), ("mms", mms), ("pinos leche", self.variante_leche)):
            with self.subTest(palabra=palabra):
                respuesta = self.client.get(reverse("buscar_productos"), {"q": palabra})
                self.assertEqual(list(respuesta.context["variantes"]), [esperada])

    def test_la_correccion_respeta_los_filtros(self):
        sin_filtro = self.client.get(reverse("buscar_productos"), {"q": "lece"})
        self.assertContains(sin_filtro, "Mostrando resultados para «leche»")
        respuesta = self.client.get(
            reverse("buscar_productos"), {"q": "lece", "categoria": self.salsas.pk}
        )  # «leche» existe, pero no en Salsas
        self.assertEqual(list(respuesta.context["variantes"]), [])
        self.assertNotContains(respuesta, "Mostrando resultados")
        self.assertContains(respuesta, "No encontramos productos con «lece» en la categoría o marca seleccionada")

    def test_la_pantalla_principal_muestra_los_productos(self):
        cliente = User.objects.create_user(email="ana@correo.com", password="Clave2026segura")
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse("inicio_cliente"))
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertContains(respuesta, "Leche entera 1L")
