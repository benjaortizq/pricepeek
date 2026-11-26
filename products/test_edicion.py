"""Issue «Edición de datos generales de productos»: el administrador cambia el nombre, la marca,
la categoría, la descripción y la imagen, y todas las tiendas que ofrecen el producto lo ven igual."""

import io
from urllib.parse import urlencode

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User

from .edicion import (
    CARPETA_DE_IMAGENES,
    nombre_de_imagen_subida,
    url_de_imagen_subida,
)
from .models import Brands, Prices, ProductImages, Products, Stores
from .tests import CatalogoTestCase, fechas

CLAVE = "Clave-segura-123"
ALMACENAMIENTO_EN_MEMORIA = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def imagen(nombre="foto.png", formato="PNG"):
    contenido = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(contenido, formato)
    return SimpleUploadedFile(
        nombre, contenido.getvalue(), content_type=f"image/{formato.lower()}"
    )


class EdicionBase(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )
        cls.empresa = User.objects.create_user(
            email="empresa@example.com", password=CLAVE, role="enterprise"
        )
        cls.cliente = User.objects.create_user(
            email="cliente@example.com", password=CLAVE, role="client"
        )
        cls.walmart = Stores.objects.create(name="Walmart", **fechas())
        cls.gollo = Stores.objects.create(name="Gollo", **fechas())
        cls.precio(cls.variante_leche, cls.walmart, 1200)
        cls.precio(cls.variante_leche, cls.gollo, 1150)
        cls.imagen(
            cls.variante_leche, "https://img.test/leche.png", principal=True
        )

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def url(self, producto=None):
        return reverse("editar_producto", args=[(producto or self.leche).pk])

    def datos(self, **cambios):
        datos = {
            "name": "Leche entera 1L",
            "category": self.lacteos.pk,
            "brand": "Dos Pinos",
            "description": "Leche entera pasteurizada.",
        }
        datos.update(cambios)
        return datos

    def guardar(self, producto=None, **cambios):
        return self.client.post(self.url(producto), self.datos(**cambios))

    def imagenes_principales(self, producto=None):
        return list(
            ProductImages.objects.filter(
                variant__product=producto or self.leche, is_main=True
            )
            .order_by("variant_id")
            .values_list("image_url", flat=True)
        )


class EditarDatosGeneralesTests(EdicionBase):
    def test_el_formulario_trae_los_datos_actuales_y_las_tiendas(self):
        respuesta = self.client.get(self.url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'value="Leche entera 1L"')
        self.assertContains(respuesta, 'value="Dos Pinos"')
        self.assertContains(respuesta, "Leche entera pasteurizada.")
        self.assertContains(respuesta, "https://img.test/leche.png")
        self.assertContains(respuesta, "Walmart")
        self.assertContains(respuesta, "Gollo")
        self.assertContains(respuesta, "Lo ofrecen 2 tiendas")

    def test_cambia_el_nombre_la_categoria_y_la_descripcion(self):
        respuesta = self.guardar(
            name="  Leche semidescremada 1L ",
            category=self.salsas.pk,
            description="Nueva.",
        )
        self.assertRedirects(respuesta, self.url())
        self.leche.refresh_from_db()
        self.assertEqual(
            (self.leche.name, self.leche.category, self.leche.description),
            ("Leche semidescremada 1L", self.salsas, "Nueva."),
        )
        mensaje = [str(m) for m in respuesta.wsgi_request._messages]
        self.assertEqual(
            mensaje,
            [
                "Se guardaron los cambios del producto (el nombre, la categoría, la descripción). "
                "Se ven igual en las 2 tiendas que lo ofrecen."
            ],
        )

    def test_la_descripcion_vacia_queda_sin_descripcion(self):
        self.guardar(description="   ")
        self.leche.refresh_from_db()
        self.assertIsNone(self.leche.description)
        self.assertContains(
            self.client.get(reverse("detalle_producto", args=[self.leche.pk])),
            "Sin descripción.",
        )

    def test_usa_la_marca_existente_aunque_se_escriba_distinto(self):
        self.guardar(brand="KRAFT-HEINZ")
        self.leche.refresh_from_db()
        self.assertEqual(self.leche.brand, self.heinz)
        self.assertEqual(Brands.objects.count(), 2)

    def test_crea_la_marca_si_no_existe(self):
        respuesta = self.guardar(brand="Sabemás")
        self.leche.refresh_from_db()
        self.assertEqual(
            (self.leche.brand.name, self.leche.brand.slug),
            ("Sabemás", "sabemas"),
        )
        self.assertEqual(Brands.objects.count(), 3)
        self.assertIn(
            "Se creó la marca «Sabemás» en el catálogo.",
            [str(m) for m in respuesta.wsgi_request._messages],
        )

    def test_una_marca_con_el_mismo_slug_es_la_misma(self):
        sabemas = Brands.objects.create(
            name="SABEMAS S.A.", slug="sabemas", **fechas()
        )
        self.guardar(brand="Sabemás")
        self.leche.refresh_from_db()
        self.assertEqual(self.leche.brand, sabemas)

    def test_sin_cambios_no_toca_el_producto(self):
        antes = Products.objects.get(pk=self.leche.pk).updated_at
        respuesta = self.guardar()
        self.assertEqual(
            Products.objects.get(pk=self.leche.pk).updated_at, antes
        )
        self.assertEqual(
            [str(m) for m in respuesta.wsgi_request._messages],
            ["No había cambios que guardar."],
        )

    def test_el_nombre_y_la_marca_son_obligatorios(self):
        respuesta = self.guardar(name=" ", brand="")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            set(respuesta.context["form"].errors), {"name", "brand"}
        )
        self.leche.refresh_from_db()
        self.assertEqual(self.leche.name, "Leche entera 1L")

    def test_todas_las_tiendas_muestran_los_datos_nuevos(self):
        self.guardar(name="Leche Dos Pinos deslactosada", brand="Kraft Heinz")
        detalle = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )
        self.assertContains(detalle, "Leche Dos Pinos deslactosada")
        self.assertContains(detalle, "Kraft Heinz")
        # Cada tienda tiene su precio, pero todas apuntan al mismo producto: no hay una copia por tienda.
        self.assertEqual(
            set(
                Prices.objects.values_list(
                    "id_store__name",
                    "gtin__product__name",
                    "gtin__product__brand__name",
                )
            ),
            {
                ("Walmart", "Leche Dos Pinos deslactosada", "Kraft Heinz"),
                ("Gollo", "Leche Dos Pinos deslactosada", "Kraft Heinz"),
            },
        )

    def test_vuelve_a_la_lista_de_donde_vino(self):
        lista = reverse("catalogo_de_productos") + "?q=leche&pagina=1"
        respuesta = self.client.post(
            self.url(), {**self.datos(name="Otra leche"), "volver": lista}
        )
        self.assertRedirects(
            respuesta, self.url() + "?" + urlencode({"volver": lista})
        )
        self.assertContains(
            self.client.get(respuesta.url),
            f'href="{lista.replace("&", "&amp;")}"',
        )

    def test_no_vuelve_a_otro_sitio(self):
        respuesta = self.client.post(
            self.url(),
            {**self.datos(), "volver": "https://otro.test/catalogo/"},
        )
        self.assertRedirects(respuesta, self.url())

    def test_solo_el_administrador_puede_editar(self):
        self.client.force_login(self.empresa)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(
            self.guardar(name="Cambiado por la empresa").status_code, 403
        )
        self.client.force_login(self.cliente)
        self.assertNotEqual(self.client.get(self.url()).status_code, 200)
        self.guardar(name="Cambiado por el cliente")
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.url()),
            reverse("login") + "?next=" + self.url(),
        )
        self.leche.refresh_from_db()
        self.assertEqual(self.leche.name, "Leche entera 1L")

    def test_el_detalle_tiene_el_boton_de_editar_solo_para_el_administrador(
        self,
    ):
        detalle = reverse("detalle_producto", args=[self.leche.pk])
        self.assertContains(self.client.get(detalle), self.url())
        self.client.logout()
        self.assertNotContains(self.client.get(detalle), self.url())


class EditarImagenTests(EdicionBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Dos presentaciones: la principal de una se reemplaza y a la otra (sin imagen) se le crea.
        cls.leche_2l = cls.variante(cls.leche, "7441001234574")

    def test_con_un_enlace_queda_en_todas_las_presentaciones(self):
        self.guardar(image_url="https://img.test/nueva.jpg")
        self.assertEqual(
            self.imagenes_principales(), ["https://img.test/nueva.jpg"] * 2
        )
        nueva = ProductImages.objects.get(variant=self.leche_2l)
        self.assertEqual((nueva.number_image, nueva.is_main), (1, True))
        detalle = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )
        self.assertContains(detalle, "https://img.test/nueva.jpg")

    def test_el_mismo_enlace_no_es_un_cambio(self):
        ProductImages.objects.create(
            variant=self.leche_2l,
            image_url="https://img.test/leche.png",
            is_main=True,
            number_image=1,
            **fechas(),
        )
        respuesta = self.guardar(image_url="https://img.test/leche.png")
        self.assertEqual(
            [str(m) for m in respuesta.wsgi_request._messages],
            ["No había cambios que guardar."],
        )

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_sube_una_imagen_y_queda_con_un_enlace_que_no_vence(self):
        respuesta = self.client.post(
            self.url(), {**self.datos(), "image": imagen("leche.webp", "WEBP")}
        )
        self.assertRedirects(respuesta, self.url())
        url, otra = self.imagenes_principales()
        self.assertEqual(url, otra)
        nombre = nombre_de_imagen_subida(url)
        self.assertRegex(
            nombre,
            rf"^{CARPETA_DE_IMAGENES}{self.leche.pk}/[0-9a-f]{{32}}\.webp$",
        )
        self.assertTrue(default_storage.exists(nombre))
        # El enlace es de este sitio y redirige al archivo en el almacenamiento.
        redireccion = self.client.get(url)
        self.assertEqual(redireccion.status_code, 302)
        self.assertEqual(redireccion["Location"], default_storage.url(nombre))
        self.assertIn("max-age=1800", redireccion["Cache-Control"])

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_al_reemplazar_una_imagen_subida_se_borra_el_archivo_viejo(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url(), {**self.datos(), "image": imagen()})
        vieja = nombre_de_imagen_subida(self.imagenes_principales()[0])
        with self.captureOnCommitCallbacks(execute=True):
            self.guardar(image_url="https://img.test/otra.png")
        self.assertFalse(default_storage.exists(vieja))
        self.assertEqual(
            self.imagenes_principales(), ["https://img.test/otra.png"] * 2
        )

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_rechaza_lo_que_no_es_una_imagen(self):
        falsa = SimpleUploadedFile(
            "foto.png", b"no soy una imagen", content_type="image/png"
        )
        respuesta = self.client.post(
            self.url(), {**self.datos(), "image": falsa}
        )
        self.assertEqual(
            respuesta.context["form"].errors["image"],
            ["El archivo no es una imagen o está dañado."],
        )
        self.assertEqual(
            self.imagenes_principales(), ["https://img.test/leche.png"]
        )

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_rechaza_otros_formatos_de_imagen(self):
        respuesta = self.client.post(
            self.url(), {**self.datos(), "image": imagen("foto.bmp", "BMP")}
        )
        self.assertEqual(
            respuesta.context["form"].errors["image"],
            ["La imagen tiene que ser JPG, PNG, WEBP o GIF."],
        )

    @override_settings(STORAGES=ALMACENAMIENTO_EN_MEMORIA)
    def test_no_acepta_archivo_y_enlace_a_la_vez(self):
        respuesta = self.client.post(
            self.url(),
            {
                **self.datos(),
                "image": imagen(),
                "image_url": "https://img.test/nueva.jpg",
            },
        )
        self.assertEqual(
            respuesta.context["form"].non_field_errors(),
            ["Suba una imagen o pegue un enlace, no los dos."],
        )
        self.assertEqual(
            self.imagenes_principales(), ["https://img.test/leche.png"]
        )

    def test_sin_presentaciones_no_se_puede_poner_imagen(self):
        suelto = self.producto(
            "Producto sin código", self.dos_pinos, self.lacteos
        )
        respuesta = self.guardar(
            suelto,
            image_url="https://img.test/nueva.jpg",
            name="Producto sin código",
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].non_field_errors())

    def test_la_vista_de_imagenes_solo_sirve_imagenes_de_productos(self):
        self.assertEqual(
            self.client.get(
                url_de_imagen_subida("../reviews/foto.png")
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(url_de_imagen_subida("1/foto.png")).status_code,
            404,
        )


class CatalogoDeProductosTests(EdicionBase):
    def setUp(self):
        super().setUp()
        self.lista = reverse("catalogo_de_productos")

    def test_lista_los_productos_con_sus_datos(self):
        respuesta = self.client.get(self.lista)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Leche entera 1L")
        self.assertContains(respuesta, "Salsa de tomate")
        self.assertContains(respuesta, "7441001234567")
        tiendas = {
            p.name: p.tiendas for p in respuesta.context["pagina"].object_list
        }
        self.assertEqual(tiendas, {"Leche entera 1L": 2, "Salsa de tomate": 0})
        self.assertContains(respuesta, self.url())
        self.assertContains(respuesta, "Mostrando")

    def test_busca_por_nombre_marca_o_codigo(self):
        for busqueda in ("salsa", "heinz", "0013000000765"):
            with self.subTest(busqueda=busqueda):
                productos = list(
                    self.client.get(self.lista, {"q": busqueda})
                    .context["pagina"]
                    .object_list
                )
                self.assertEqual(productos, [self.ketchup])

    def test_filtra_lo_que_falta_completar(self):
        filtros = {
            "sin-imagen": [self.ketchup],
            "sin-descripcion": [self.ketchup],
            "sin-precios": [self.ketchup],
        }
        for estado, esperados in filtros.items():
            with self.subTest(estado=estado):
                productos = list(
                    self.client.get(self.lista, {"estado": estado})
                    .context["pagina"]
                    .object_list
                )
                self.assertEqual(productos, esperados)

    def test_filtra_por_categoria(self):
        productos = list(
            self.client.get(self.lista, {"categoria": self.salsas.pk})
            .context["pagina"]
            .object_list
        )
        self.assertEqual(productos, [self.ketchup])

    def test_el_enlace_de_editar_recuerda_la_lista(self):
        respuesta = self.client.get(self.lista, {"q": "leche"})
        self.assertContains(
            respuesta,
            self.url() + "?" + urlencode({"volver": self.lista + "?q=leche"}),
        )

    def test_esta_en_la_barra_lateral_del_panel(self):
        self.assertContains(
            self.client.get(reverse("inicio_administrador")), self.lista
        )

    def test_solo_el_administrador_la_ve(self):
        self.client.force_login(self.empresa)
        self.assertEqual(self.client.get(self.lista).status_code, 403)


class TraduccionTests(EdicionBase):
    def test_las_pantallas_se_traducen_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        lista = self.client.get(reverse("catalogo_de_productos"))
        for texto in (
            "Products in the catalog",
            "No image",
            "No price in any store",
            "Name, brand or barcode",
        ):
            self.assertContains(lista, texto)
        edicion = self.client.get(self.url())
        for texto in (
            "Edit product",
            "Main product details",
            "Sold by 2 stores",
            "Product image",
            "Change image",
        ):
            self.assertContains(edicion, texto)
        self.assertNotContains(edicion, "Datos principales del producto")
        respuesta = self.guardar(name="Leche descremada 1L")
        self.assertEqual(
            [str(m) for m in respuesta.wsgi_request._messages],
            [
                "The product changes were saved (the name). They show the same in all 2 stores that sell it."
            ],
        )
