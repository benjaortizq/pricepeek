"""Pruebas del portal de empresas."""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from reportlab.platypus import Paragraph, Table

from accounts.models import AccountsUser, User
from enterprise.reports import construir_historia, datos_reporte
from products.models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    Products,
    ProductVariants,
    Stores,
)


MODELOS = [
    Brands,
    Categories,
    Currencies,
    Stores,
    Products,
    ProductVariants,
    ProductImages,
    Prices,
]


def _textos_historia(flujos):
    """Extrae el texto de los flowables para verificar las traducciones."""
    textos = []
    for flujo in flujos:
        if isinstance(flujo, Paragraph):
            textos.append(flujo.getPlainText())
        elif isinstance(flujo, Table):
            for fila in flujo._cellvalues:
                for celda in fila:
                    if isinstance(celda, list):
                        textos.extend(_textos_historia(celda))
                    else:
                        textos.extend(_textos_historia([celda]))
    return textos


class EmpresaTestCase(TestCase):
    """Crea las tablas no administradas y una cuenta de empresa asignada."""

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

    def setUp(self):
        super().setUp()
        ahora = timezone.now()
        self.fechas = {"created_at": ahora, "updated_at": ahora}
        self.marca = Brands.objects.create(
            name="Marca de prueba", slug="marca-prueba", **self.fechas
        )
        self.categoria = Categories.objects.create(name="Categoría de prueba", **self.fechas)
        self.moneda = Currencies.objects.create(
            name="colones", symbol="₡", **self.fechas
        )
        self.store = Stores.objects.create(name="Tienda Empresa\n", **self.fechas)
        self.otra_store = Stores.objects.create(name="Tienda Competencia", **self.fechas)
        self.usuario = User.objects.create_user(
            email="empresa@example.com",
            password="ClaveSegura123",
            role=User.Role.ENTERPRISE,
            first_name="Empresa",
        )
        AccountsUser.objects.filter(pk=self.usuario.pk).update(from_store=self.store.pk)
        self.usuario_sin_tienda = User.objects.create_user(
            email="sin-tienda@example.com",
            password="ClaveSegura123",
            role=User.Role.ENTERPRISE,
        )
        self.producto = Products.objects.create(
            name="Producto de prueba",
            description="Descripción completa",
            brand=self.marca,
            category=self.categoria,
            **self.fechas,
        )
        self.variante = ProductVariants.objects.create(
            product=self.producto,
            gtin="7441001234569",
            name="Variante de prueba",
            attributes={"color": "azul"},
            **self.fechas,
        )
        self.precio = self.crear_precio(self.store, self.variante, 1000, "0.20")
        self.client.force_login(self.usuario)

    def crear_precio(self, store, variante, precio, descuento="0", disponible=True, **extra):
        return Prices.objects.create(
            id_store=store,
            gtin=variante,
            price=precio,
            discount=Decimal(descuento),
            is_available=disponible,
            currency=self.moneda,
            product_web_url=f"https://tienda.test/{variante.gtin}",
            created_at=timezone.now(),
            updated_at=timezone.now(),
            **extra,
        )

    def crear_variante(self, gtin, nombre="Otra variante"):
        producto = Products.objects.create(
            name=nombre,
            description="",
            brand=self.marca,
            category=self.categoria,
            **self.fechas,
        )
        return ProductVariants.objects.create(
            product=producto,
            gtin=gtin,
            name=nombre,
            attributes={},
            **self.fechas,
        )


class AutorizacionEmpresaTests(EmpresaTestCase):
    def test_anónimo_es_redirigido_al_inicio_de_sesión(self):
        self.client.logout()
        respuesta = self.client.get(reverse("enterprise:panel"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta["Location"])

    def test_cliente_no_puede_entrar_al_portal(self):
        cliente = User.objects.create_user(
            email="cliente@example.com",
            password="ClaveSegura123",
            role=User.Role.CLIENT,
        )
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        self.assertEqual(respuesta.status_code, 403)

    def test_empresa_sin_tienda_no_puede_entrar(self):
        self.client.force_login(self.usuario_sin_tienda)
        respuesta = self.client.get(reverse("enterprise:panel"))
        self.assertEqual(respuesta.status_code, 403)

    def test_catalogo_solo_contiene_precios_de_la_tienda_asignada(self):
        otra_variante = self.crear_variante("7441001234576", "Competencia")
        self.crear_precio(self.otra_store, otra_variante, 800)

        respuesta = self.client.get(reverse("enterprise:catalogo"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Producto de prueba")
        self.assertNotContains(respuesta, "Competencia")

    def test_filtros_de_identificador_invalidos_no_provocan_error(self):
        for filtro in ("categoria", "marca"):
            with self.subTest(filtro=filtro):
                respuesta = self.client.get(
                    reverse("enterprise:catalogo"),
                    {filtro: "no-es-un-identificador"},
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(len(respuesta.context["pagina"].object_list), 0)

    def test_no_puede_editar_un_precio_de_otra_tienda(self):
        otra_variante = self.crear_variante("7441001234576", "Competencia")
        otro_precio = self.crear_precio(self.otra_store, otra_variante, 800)

        respuesta = self.client.get(
            reverse("enterprise:editar_producto", kwargs={"price_id": otro_precio.pk})
        )

        self.assertEqual(respuesta.status_code, 404)
        otro_precio.refresh_from_db()
        self.assertEqual(otro_precio.price, 800)

    def test_no_puede_desactivar_ni_quitar_un_precio_de_otra_tienda(self):
        otra_variante = self.crear_variante("7441001234576", "Competencia")
        otro_precio = self.crear_precio(self.otra_store, otra_variante, 800)

        for nombre in ("desactivar_producto", "eliminar_producto"):
            with self.subTest(nombre=nombre):
                respuesta = self.client.post(
                    reverse(
                        f"enterprise:{nombre}",
                        kwargs={"price_id": otro_precio.pk},
                    )
                )
                self.assertEqual(respuesta.status_code, 404)

        otro_precio.refresh_from_db()
        self.assertEqual(otro_precio.price, 800)
        self.assertTrue(otro_precio.is_available)

    def test_inicio_de_empresa_redirige_al_panel_nuevo(self):
        respuesta = self.client.get(reverse("inicio_empresa"))
        self.assertRedirects(respuesta, reverse("enterprise:panel"))


class CompetitividadEmpresaTests(EmpresaTestCase):
    def _competidor(self, precio, descuento="0"):
        return self.crear_precio(
            self.otra_store,
            self.variante,
            precio,
            descuento,
        )

    def test_precio_final_menor_es_verde(self):
        self._competidor(900)
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        precio = next(
            item
            for item in respuesta.context["pagina"].object_list
            if item.pk == self.precio.pk
        )
        self.assertEqual(precio.final_price, Decimal("800.00"))
        self.assertEqual(precio.competitiveness, "green")

    def test_precio_final_igual_es_amarillo(self):
        self._competidor(1000, "0.20")
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        precio = next(
            item
            for item in respuesta.context["pagina"].object_list
            if item.pk == self.precio.pk
        )
        self.assertEqual(precio.competitiveness, "yellow")

    def test_precio_final_mayor_es_rojo(self):
        self._competidor(700)
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        precio = next(
            item
            for item in respuesta.context["pagina"].object_list
            if item.pk == self.precio.pk
        )
        self.assertEqual(precio.competitiveness, "red")

    def test_sin_otras_tiendas_es_neutro(self):
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        precio = next(
            item
            for item in respuesta.context["pagina"].object_list
            if item.pk == self.precio.pk
        )
        self.assertIsNone(precio.competitor_price)
        self.assertEqual(precio.competitiveness, "neutral")

    def test_el_descuento_participa_en_la_comparacion(self):
        self.precio.discount = Decimal("0.50")
        self.precio.save(update_fields=["discount"])
        self._competidor(600)
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        precio = next(
            item
            for item in respuesta.context["pagina"].object_list
            if item.pk == self.precio.pk
        )
        self.assertEqual(precio.final_price, Decimal("500.00"))
        self.assertEqual(precio.competitiveness, "green")


class EscrituraPreciosEmpresaTests(EmpresaTestCase):
    def test_editar_actualiza_solo_el_precio_propio(self):
        otra_variante = self.crear_variante("7441001234576", "Competencia")
        otro_precio = self.crear_precio(self.otra_store, otra_variante, 800)

        respuesta = self.client.post(
            reverse("enterprise:editar_producto", kwargs={"price_id": self.precio.pk}),
            {
                "price": "1250",
                "discount": "0.10",
                "is_available": "on",
                "product_web_url": "https://tienda.test/nuevo",
            },
        )

        self.assertRedirects(
            respuesta,
            reverse("enterprise:detalle_producto", kwargs={"price_id": self.precio.pk}),
        )
        self.precio.refresh_from_db()
        otro_precio.refresh_from_db()
        self.assertEqual(self.precio.price, 1250)
        self.assertEqual(self.precio.discount, Decimal("0.10"))
        self.assertEqual(otro_precio.price, 800)

    def test_descuento_vacio_se_guarda_como_cero(self):
        self.client.post(
            reverse("enterprise:editar_producto", kwargs={"price_id": self.precio.pk}),
            {"price": "1250", "discount": "", "is_available": "on"},
        )
        self.precio.refresh_from_db()
        self.assertEqual(self.precio.discount, Decimal("0.00"))

    def test_descuento_fuera_de_rango_se_rechaza(self):
        self.client.post(
            reverse("enterprise:editar_producto", kwargs={"price_id": self.precio.pk}),
            {"price": "1250", "discount": "1.5", "is_available": "on"},
        )
        self.precio.refresh_from_db()
        self.assertEqual(self.precio.discount, Decimal("0.20"))

    def test_precio_negativo_se_quita_y_se_desactiva(self):
        self.client.post(
            reverse("enterprise:editar_producto", kwargs={"price_id": self.precio.pk}),
            {"price": "-50", "discount": "0", "is_available": "on"},
        )
        self.precio.refresh_from_db()
        self.assertIsNone(self.precio.price)
        self.assertFalse(self.precio.is_available)

    def test_precio_vacio_se_quita_y_se_desactiva(self):
        self.client.post(
            reverse("enterprise:editar_producto", kwargs={"price_id": self.precio.pk}),
            {"price": "", "discount": "0", "is_available": "on"},
        )
        self.precio.refresh_from_db()
        self.assertIsNone(self.precio.price)
        self.assertFalse(self.precio.is_available)

    def test_quitar_precio_solo_afecta_la_tienda_y_no_borra_la_variante(self):
        self.client.post(
            reverse("enterprise:eliminar_producto", kwargs={"price_id": self.precio.pk})
        )
        self.precio.refresh_from_db()
        self.assertIsNone(self.precio.price)
        self.assertFalse(self.precio.is_available)
        self.assertTrue(ProductVariants.objects.filter(pk=self.variante.pk).exists())

    def test_desactivar_conserva_el_precio_de_la_tienda(self):
        self.client.post(
            reverse("enterprise:desactivar_producto", kwargs={"price_id": self.precio.pk})
        )
        self.precio.refresh_from_db()
        self.assertEqual(self.precio.price, 1000)
        self.assertEqual(self.precio.discount, Decimal("0.20"))
        self.assertFalse(self.precio.is_available)

    def test_la_confirmacion_por_get_no_modifica_el_precio(self):
        respuesta = self.client.get(
            reverse("enterprise:desactivar_producto", kwargs={"price_id": self.precio.pk})
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Desactivar el producto")
        self.precio.refresh_from_db()
        self.assertTrue(self.precio.is_available)

    def test_una_accion_destructiva_sin_csrf_no_se_ejecuta(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)

        respuesta = cliente.post(
            reverse("enterprise:desactivar_producto", kwargs={"price_id": self.precio.pk})
        )

        self.assertEqual(respuesta.status_code, 403)
        self.precio.refresh_from_db()
        self.assertTrue(self.precio.is_available)
        self.assertEqual(self.precio.price, 1000)


class AltaProductosEmpresaTests(EmpresaTestCase):
    def test_gtin_existente_crea_solo_el_precio_propio(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        productos_antes = Products.objects.count()
        variantes_antes = ProductVariants.objects.count()
        nombre_canonico = variante_existente.product.name

        respuesta = self.client.post(
            reverse("enterprise:nuevo_producto"),
            {
                "gtin": variante_existente.gtin,
                "product_name": "No debe cambiar",
                "variant_name": "No debe cambiar",
                "brand": self.marca.pk,
                "category": self.categoria.pk,
                "price": "1500",
                "discount": "0.10",
                "is_available": "on",
                "product_web_url": "https://tienda.test/existente",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Products.objects.count(), productos_antes)
        self.assertEqual(ProductVariants.objects.count(), variantes_antes)
        variante_existente.product.refresh_from_db()
        variante_existente.refresh_from_db()
        self.assertEqual(variante_existente.product.name, nombre_canonico)
        self.assertEqual(variante_existente.attributes, {})
        nuevo = Prices.objects.get(id_store=self.store, gtin=variante_existente)
        self.assertEqual(nuevo.price, 1500)

    def test_gtin_existente_heredado_acepta_su_registro_sin_revalidarlo(self):
        variante_heredada = self.crear_variante("7441001234567", "GTIN heredado")

        respuesta = self.client.post(
            reverse("enterprise:nuevo_producto"),
            {
                "gtin": variante_heredada.gtin,
                "price": "1500",
                "discount": "0",
                "is_available": "on",
                "product_web_url": "https://tienda.test/heredado",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(
            Prices.objects.filter(
                id_store=self.store,
                gtin=variante_heredada,
            ).exists()
        )

    def test_identificador_de_marca_fuera_de_rango_se_rechaza_sin_error(self):
        respuesta = self.client.post(
            reverse("enterprise:nuevo_producto"),
            {
                "gtin": "7441001234590",
                "product_name": "Producto nuevo",
                "variant_name": "Variante nueva",
                "brand": str(2**70),
                "category": self.categoria.pk,
                "price": "2000",
                "discount": "0",
                "is_available": "on",
                "product_web_url": "https://tienda.test/nuevo",
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("brand", respuesta.context["form"].errors)
        self.assertEqual(Prices.objects.count(), 1)

    def test_gtin_nuevo_crea_producto_variante_y_precio(self):
        respuesta = self.client.post(
            reverse("enterprise:nuevo_producto"),
            {
                "gtin": "7441001234576",
                "product_name": "Producto nuevo",
                "variant_name": "Variante nueva",
                "brand": self.marca.pk,
                "category": self.categoria.pk,
                "description": "Descripción nueva",
                "attributes": '{"color": "rojo"}',
                "price": "2000",
                "discount": "0.05",
                "is_available": "on",
                "product_web_url": "https://tienda.test/nuevo",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        variante = ProductVariants.objects.get(gtin="7441001234576")
        self.assertEqual(variante.product.name, "Producto nuevo")
        self.assertEqual(variante.attributes, {"color": "rojo"})
        precio = Prices.objects.get(id_store=self.store, gtin=variante)
        self.assertEqual(precio.price, 2000)
        self.assertEqual(precio.discount, Decimal("0.05"))


class ImportacionCSVEmpresaTests(EmpresaTestCase):
    def _subir(self, contenido):
        return SimpleUploadedFile(
            "precios.csv",
            contenido.encode("utf-8"),
            content_type="text/csv",
        )

    def test_importa_filas_validas_y_reporta_errores_por_fila(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,product_name,variant_name,brand_id,category_id,attributes,price,discount,is_available,product_web_url\n"
            f"{variante_existente.gtin},,,,,,1000,0.10,true,https://tienda.test/a\n"
            "no-es-un-gtin,,,,,0.2,1000,0.10,true,\n"
            "7441001234576,Nuevo,Variante,"
            f"{self.marca.pk},{self.categoria.pk},{{}},2000,0,true,\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        self.assertEqual(respuesta.status_code, 200)
        resultados = respuesta.context["resultados"]
        self.assertEqual(len(resultados), 3)
        self.assertTrue(resultados[0].importado)
        self.assertFalse(resultados[1].importado)
        self.assertTrue(resultados[1].errores)
        self.assertTrue(resultados[2].importado)
        self.assertTrue(
            Prices.objects.filter(id_store=self.store, gtin=variante_existente).exists()
        )
        self.assertTrue(
            Prices.objects.filter(id_store=self.store, gtin_id="7441001234576").exists()
        )

    def test_una_fila_invalida_no_bloquea_la_siguiente_del_mismo_gtin(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,product_name,variant_name,brand_id,category_id,attributes,price,discount,is_available,product_web_url\n"
            f"{variante_existente.gtin},,,,,,no-es-un-precio,0,true,\n"
            f"{variante_existente.gtin},,,,,,1000,0,true,\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultados = respuesta.context["resultados"]
        self.assertFalse(resultados[0].importado)
        self.assertTrue(resultados[1].importado)
        self.assertTrue(
            Prices.objects.filter(id_store=self.store, gtin=variante_existente).exists()
        )

    def test_json_no_finito_se_rechaza_sin_romper_las_filas_siguientes(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,attributes,price\n"
            f"{variante_existente.gtin},{{\"valor\": NaN}},1000\n"
            f"{variante_existente.gtin},{{}},1000\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultados = respuesta.context["resultados"]
        self.assertFalse(resultados[0].importado)
        self.assertTrue(resultados[1].importado)

    def test_un_precio_fuera_del_rango_no_rompe_las_filas_siguientes(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,price\n"
            f"{variante_existente.gtin},2147483648\n"
            f"{variante_existente.gtin},1000\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultados = respuesta.context["resultados"]
        self.assertFalse(resultados[0].importado)
        self.assertTrue(resultados[1].importado)

    def test_acepta_encabezados_con_espacios_y_mayusculas(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            " GTIN , PRICE \n"
            f"{variante_existente.gtin},1000\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultado = respuesta.context["resultados"][0]
        self.assertTrue(resultado.importado)
        self.assertTrue(
            Prices.objects.filter(id_store=self.store, gtin=variante_existente).exists()
        )

    def test_rechaza_un_gtin_duplicado_dentro_del_archivo(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,price\n"
            f"{variante_existente.gtin},1000\n"
            f"{variante_existente.gtin},1100\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultados = respuesta.context["resultados"]
        self.assertTrue(resultados[0].importado)
        self.assertFalse(resultados[1].importado)
        self.assertTrue(resultados[1].errores)

    def test_precio_negativo_en_csv_deja_el_producto_no_disponible(self):
        variante_existente = self.crear_variante("7441001234583", "GTIN existente")
        contenido = (
            "gtin,product_name,variant_name,brand_id,category_id,attributes,price,discount,is_available,product_web_url\n"
            f"{variante_existente.gtin},,,,,,-5,0,true,\n"
        )
        respuesta = self.client.post(
            reverse("enterprise:cargar_csv"),
            {"archivo": self._subir(contenido)},
        )

        resultado = respuesta.context["resultados"][0]
        self.assertTrue(resultado.importado)
        self.assertTrue(resultado.avisos)
        precio = Prices.objects.get(id_store=self.store, gtin=variante_existente)
        self.assertIsNone(precio.price)
        self.assertFalse(precio.is_available)

    def test_plantilla_csv_incluye_las_columnas_seguras(self):
        respuesta = self.client.get(reverse("enterprise:plantilla_csv"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "text/csv; charset=utf-8")
        contenido = respuesta.content.decode("utf-8")
        self.assertIn("gtin,product_name,variant_name", contenido)
        self.assertNotIn("id_store", contenido)


class DetalleYReporteEmpresaTests(EmpresaTestCase):
    def test_detalle_muestra_precios_y_alertas(self):
        ProductImages.objects.create(
            variant=self.variante,
            image_url="https://img.test/producto.png",
            is_main=True,
            number_image=1,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self.precio.product_web_url = ""
        self.precio.updated_at = timezone.now() - timezone.timedelta(days=2)
        self.precio.save(update_fields=["product_web_url", "updated_at"])

        respuesta = self.client.get(
            reverse("enterprise:detalle_producto", kwargs={"price_id": self.precio.pk})
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Producto de prueba")
        self.assertContains(respuesta, "Problemas y alertas")
        self.assertContains(respuesta, "Falta el enlace del producto")
        self.assertContains(respuesta, "El precio no cambia desde hace 2 días o más")
        self.assertContains(respuesta, "https://img.test/producto.png")

    def test_el_panel_muestra_el_umbral_de_precios_desactualizados(self):
        respuesta = self.client.get(reverse("enterprise:panel"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Sin cambios desde hace 2 días o más")

    def test_un_precio_reciente_no_se_reporta_como_desactualizado(self):
        self.precio.updated_at = (
            timezone.now()
            - timezone.timedelta(days=2)
            + timezone.timedelta(minutes=1)
        )
        self.precio.save(update_fields=["updated_at"])

        respuesta = self.client.get(
            reverse("enterprise:detalle_producto", kwargs={"price_id": self.precio.pk})
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(
            respuesta,
            "El precio no cambia desde hace 2 días o más",
        )

    @override_settings(STALE_PRICE_DAYS=5)
    def test_el_limite_usa_la_configuracion_y_es_timezone_aware(self):
        from enterprise.selectors import limite_precio_desactualizado

        ahora = timezone.now()
        limite = limite_precio_desactualizado(ahora)

        self.assertTrue(timezone.is_aware(limite))
        self.assertEqual(limite, ahora - timezone.timedelta(days=5))

    def test_los_montos_usan_el_separador_del_idioma_activo(self):
        self.precio.price = 1250
        self.precio.save(update_fields=["price"])

        self.client.cookies["django_language"] = "es"
        respuesta_es = self.client.get(reverse("enterprise:catalogo"))
        self.assertContains(respuesta_es, "₡1.250")

        self.client.cookies["django_language"] = "en"
        respuesta_en = self.client.get(reverse("enterprise:catalogo"))
        self.assertContains(respuesta_en, "₡1,250")

    def test_la_confirmacion_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.client.get(
            reverse("enterprise:desactivar_producto", kwargs={"price_id": self.precio.pk})
        )

        self.assertContains(respuesta, "Deactivate product")
        self.assertContains(respuesta, "The price and discount will be kept")

    def test_reporte_pdf_devuelve_pdf_y_respeta_el_idioma(self):
        self.client.cookies["django_language"] = "en"

        respuesta = self.client.post(reverse("enterprise:reporte_pdf"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertEqual(
            respuesta["Content-Disposition"],
            'attachment; filename="reporte-tienda-empresa.pdf"',
        )
        self.assertTrue(respuesta.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", respuesta.content[-2048:])
        self.assertGreater(len(respuesta.content), 1000)

        with translation.override("en"):
            historia = construir_historia(datos_reporte(self.store))
            textos = "\n".join(_textos_historia(historia))
        self.assertIn("Competitiveness report", textos)
        self.assertIn("Products", textos)
        self.assertIn("Products unchanged for 2 or more days", textos)

    def test_el_reporte_incluye_productos_sobre_el_mercado_y_sin_cambios(self):
        self.precio.updated_at = timezone.now() - timezone.timedelta(days=2)
        self.precio.save(update_fields=["updated_at"])
        self.crear_precio(self.otra_store, self.variante, 500)

        with translation.override("es"):
            historia = construir_historia(datos_reporte(self.store))
            textos = "\n".join(_textos_historia(historia))

        self.assertIn("Productos por encima del mercado", textos)
        self.assertIn("Productos sin cambios desde hace 2 días o más", textos)
        self.assertIn("Producto de prueba", textos)

    def test_el_reporte_solo_contiene_productos_de_la_tienda_asignada(self):
        self.crear_precio(self.otra_store, self.variante, 500)
        otra_variante = self.crear_variante("7441001234576", "Producto de otra tienda")
        precio_ajeno = self.crear_precio(self.otra_store, otra_variante, 800)

        datos = datos_reporte(self.store)
        identificadores = {
            precio.pk for precio in datos["above_market"]
        } | {precio.pk for precio in datos["stale"]}

        self.assertIn(self.precio.pk, identificadores)
        self.assertNotIn(precio_ajeno.pk, identificadores)

    @override_settings(STALE_PRICE_DAYS=5)
    def test_el_pdf_usa_el_umbral_configurado_para_desactualizados(self):
        with translation.override("en"):
            historia = construir_historia(datos_reporte(self.store))
            textos = "\n".join(_textos_historia(historia))

        self.assertIn("Products unchanged for 5 or more days", textos)
        self.assertNotIn("Products unchanged for 2 or more days", textos)

    def test_el_pdf_genera_correctamente_acentos_y_enie(self):
        self.store.name = "Tienda Ñandú"
        self.store.save(update_fields=["name"])
        self.producto.name = "Café de la Peña"
        self.producto.save(update_fields=["name"])

        respuesta = self.client.post(reverse("enterprise:reporte_pdf"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", respuesta.content[-2048:])

    def test_el_html_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.client.get(reverse("enterprise:panel"))
        self.assertContains(respuesta, "Competitiveness dashboard")
        self.assertContains(respuesta, "Need attention")
