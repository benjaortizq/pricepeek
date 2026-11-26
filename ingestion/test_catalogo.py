"""Pruebas de pasar productos de tiendas al catálogo (crear_productos y la acción del admin)."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User
from products.models import (
    Brands,
    Categories,
    Prices,
    ProductImages,
    Products,
    ProductVariants,
)
from products.tests import fechas

from .catalogo import (
    CREADO,
    EMPATE,
    MOTIVO_CREADO,
    OMITIDO,
    OTRA_SE_PARECE_MAS,
    OTRO_CODIGO,
    VINCULADO,
    Catalogo,
    crear_en_catalogo,
    gtin_del_catalogo,
)
from .categorias import ELECTRODOMESTICOS, HOGAR, categoria_para
from .models import StoreProduct
from .test_productos_tienda import (
    GTIN_IPHONE as GTIN_IPHONE_CATALOGO,
    ProductosDeTiendaTestCase,
)

Status = StoreProduct.Status
GTIN_ADAPTADOR = "7410063015775"


class CategoriasTests(SimpleTestCase):
    def test_tipos_de_producto_de_gollo(self):
        casos = {
            "Audífonos inalámbricos": ELECTRODOMESTICOS,
            "Freidora de aire": ELECTRODOMESTICOS,
            "Cámara de seguridad": ELECTRODOMESTICOS,
            "Mouse inalámbrico": ELECTRODOMESTICOS,
            "Cama": HOGAR,
            "Set De Sabana": HOGAR,
            "Set de Sábanas": HOGAR,
            "Zapatera": HOGAR,
            "Llanta": None,
            "Batería": None,  # pueden ser de carro o de reloj
            "Mouse Pad": None,
        }
        for tipo, categoria in casos.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(categoria_para(tipo), categoria)

    def test_gana_la_regla_mas_larga(self):
        self.assertEqual(categoria_para("Olla arrocera"), ELECTRODOMESTICOS)
        self.assertEqual(categoria_para("Olla de presión"), HOGAR)
        self.assertEqual(categoria_para("Batería de cocina"), HOGAR)
        self.assertEqual(categoria_para("Sartén eléctrico"), ELECTRODOMESTICOS)

    def test_si_el_tipo_no_dice_nada_prueba_con_el_nombre(self):
        self.assertEqual(
            categoria_para("", "Licuadora Oster 600 W"), ELECTRODOMESTICOS
        )
        self.assertIsNone(categoria_para("Llanta", "Llanta Duro 130/70 R17"))

    def test_ruta_de_categorias_desde_lo_mas_especifico(self):
        self.assertEqual(
            categoria_para("Hogar > Cocina > Licuadoras"), ELECTRODOMESTICOS
        )

    def test_gtin_con_13_digitos_como_el_catalogo(self):
        self.assertEqual(
            gtin_del_catalogo("047362659408"), "0047362659408"
        )  # UPC-A
        self.assertEqual(gtin_del_catalogo("7410063015775"), "7410063015775")
        self.assertEqual(
            gtin_del_catalogo("17410063015772"), "17410063015772"
        )  # GTIN-14 de verdad


class PasarAlCatalogoTestCase(ProductosDeTiendaTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hogar = Categories.objects.create(
            name="Artículos para el hogar", **fechas()
        )

    def de_gollo(self, **cambios):
        datos = {
            "store_name": "Gollo",
            "url": "https://www.gollo.com/adaptador-de-audio-radioshack-1202253/p",
            "name": "Adaptador de audio RadioShack 1202253",
            "brand": "RadioShack",
            "category": "Adaptador de audio",
            "color": "Gris",
            "image_url": "https://www.gollo.com/media/catalog/product/1/2/1202253.jpg",
            "list_price": 9900,
            "final_price": 7900,
            "barcodes": [GTIN_ADAPTADOR],
        }
        return StoreProduct.objects.create(**{**datos, **cambios})

    def crear(self, producto, catalogo=None, guardar=True):
        return crear_en_catalogo(
            producto, catalogo or Catalogo(), guardar=guardar
        )


class CrearEnCatalogoTests(PasarAlCatalogoTestCase):
    def test_crea_marca_producto_variante_imagen_y_precio(self):
        producto = self.de_gollo()
        resultado = self.crear(producto)

        self.assertEqual(
            (resultado.tipo, resultado.motivo, resultado.marca_nueva),
            (CREADO, ELECTRODOMESTICOS, True),
        )
        variante = ProductVariants.objects.select_related(
            "product__brand", "product__category"
        ).get(gtin=GTIN_ADAPTADOR)
        self.assertEqual(
            variante.name, "Adaptador de audio RadioShack 1202253"
        )
        self.assertEqual(variante.attributes, {"color": "Gris"})
        self.assertEqual(variante.product.category.name, ELECTRODOMESTICOS)
        self.assertEqual(
            (variante.product.brand.name, variante.product.brand.slug),
            ("RadioShack", "radioshack"),
        )
        imagen = ProductImages.objects.get(variant=variante)
        self.assertEqual(
            (imagen.image_url, imagen.is_main, imagen.number_image),
            (producto.image_url, True, 1),
        )
        precio = Prices.objects.select_related("id_store").get(gtin=variante)
        self.assertEqual(
            (precio.id_store.name, precio.price, str(precio.discount)),
            ("Gollo", 9900, "0.20"),
        )
        self.assertEqual(precio.product_web_url, producto.url)
        producto.refresh_from_db()
        self.assertEqual(
            (producto.status, producto.suggested_gtin, producto.match_reason),
            (Status.CONFIRMED, GTIN_ADAPTADOR, MOTIVO_CREADO),
        )

    def test_upc_a_se_guarda_con_13_digitos(self):
        self.crear(
            self.de_gollo(
                barcodes=["047362659408"],
                name="Accesorio parrilla Char-Broil",
                category="Accesorio parrilla",
                brand="Char-Broil",
            )
        )
        self.assertTrue(
            ProductVariants.objects.filter(gtin="0047362659408").exists()
        )

    def test_usa_la_marca_que_ya_existe_aunque_se_escriba_distinto(self):
        marcas = Brands.objects.count()
        self.crear(self.de_gollo(brand="KRAFT HEINZ"))
        self.assertEqual(Brands.objects.count(), marcas)
        self.assertEqual(
            ProductVariants.objects.get(gtin=GTIN_ADAPTADOR).product.brand,
            self.heinz,
        )

    def test_la_marca_nueva_se_crea_una_sola_vez(self):
        catalogo = Catalogo()
        primero = self.crear(self.de_gollo(brand="Black + Decker"), catalogo)
        segundo = self.crear(
            self.de_gollo(
                url="https://www.gollo.com/licuadora/p",
                name="Licuadora Black+Decker",
                category="Licuadora",
                brand="BLACK+DECKER",
                barcodes=["7410063035124"],
            ),
            catalogo,
        )
        self.assertEqual(
            (primero.marca_nueva, segundo.marca_nueva), (True, False)
        )
        self.assertEqual(
            list(
                Brands.objects.filter(slug__startswith="black").values_list(
                    "name", "slug"
                )
            ),
            [("Black + Decker", "black-decker")],
        )

    def test_dry_run_no_guarda_nada(self):
        productos, marcas = Products.objects.count(), Brands.objects.count()
        resultado = self.crear(self.de_gollo(), guardar=False)
        self.assertEqual(
            (resultado.tipo, resultado.marca_nueva), (CREADO, True)
        )
        self.assertEqual(
            (Products.objects.count(), Brands.objects.count()),
            (productos, marcas),
        )
        self.assertEqual(StoreProduct.objects.get().status, Status.NO_MATCH)

    def test_si_el_codigo_ya_esta_en_el_catalogo_solo_agrega_el_precio(self):
        productos = Products.objects.count()
        producto = self.de_gollo(
            name="Salsa de tomate Heinz", barcodes=["013000000765"]
        )  # el catálogo lo tiene con 13 dígitos
        resultado = self.crear(producto)

        self.assertEqual(
            (resultado.tipo, resultado.motivo), (VINCULADO, "0013000000765")
        )
        self.assertEqual(Products.objects.count(), productos)
        self.assertTrue(
            Prices.objects.filter(
                gtin=self.variante_ketchup, id_store__name="Gollo"
            ).exists()
        )
        producto.refresh_from_db()
        self.assertEqual(producto.status, Status.CONFIRMED)

    def test_el_mismo_codigo_en_otra_pagina_de_la_tienda_se_omite(self):
        catalogo = Catalogo()
        self.crear(self.de_gollo(), catalogo)
        repetido = self.crear(
            self.de_gollo(url="https://www.gollo.com/adaptador-otra-vez/p"),
            catalogo,
        )
        self.assertEqual(
            (repetido.tipo, repetido.grupo),
            (OMITIDO, "código repetido en la tienda"),
        )
        self.assertEqual(
            Prices.objects.filter(gtin_id=GTIN_ADAPTADOR).count(), 1
        )

    def test_lo_que_no_se_crea(self):
        casos = {
            "sin código de barras": {"barcodes": []},
            "sin marca": {"brand": "Commodity"},
            "sin precio": {"final_price": None, "list_price": None},
            "sin categoría": {
                "category": "Llanta",
                "name": "Llanta Duro 130/70 R17",
            },
            "ya revisado o con sugerencia": {
                "status": Status.SUGGESTED,
                "suggested_gtin": GTIN_ADAPTADOR,
            },
        }
        for numero, (grupo, cambios) in enumerate(casos.items()):
            with self.subTest(grupo=grupo):
                resultado = self.crear(
                    self.de_gollo(
                        url=f"https://www.gollo.com/producto-{numero}/p",
                        **cambios,
                    )
                )
                self.assertEqual(
                    (resultado.tipo, resultado.grupo), (OMITIDO, grupo)
                )
        self.assertFalse(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )

    def test_sin_categoria_dice_cual_es_el_tipo_de_la_tienda(self):
        resultado = self.crear(
            self.de_gollo(category="Llanta", name="Llanta Duro")
        )
        self.assertEqual(resultado.tipo_en_tienda, "Llanta")

    def test_no_vincula_una_variante_que_alguien_rechazo(self):
        producto = self.de_gollo(
            barcodes=["013000000765"],
            status=Status.REJECTED,
            suggested_gtin="0013000000765",
        )
        resultado = self.crear(producto)
        self.assertEqual(
            (resultado.tipo, resultado.grupo), (OMITIDO, "rechazado a mano")
        )
        self.assertFalse(
            Prices.objects.filter(
                gtin=self.variante_ketchup, id_store__name="Gollo"
            ).exists()
        )


class CrearProductosCommandTests(PasarAlCatalogoTestCase):
    def correr(self, *argumentos):
        salida = StringIO()
        call_command("crear_productos", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_crea_los_que_puede_y_resume_los_demas(self):
        self.de_gollo()
        self.de_gollo(
            url="https://www.gollo.com/llanta/p",
            name="Llanta Duro",
            category="Llanta",
            barcodes=["7410063035124"],
        )
        StoreProduct.objects.create(
            store_name="Monge",
            url="https://www.tiendamonge.com/licuadora",
            name="Licuadora Oster",
            brand="Oster",
            final_price=29900,
        )

        salida = self.correr()

        self.assertIn(
            "creado: Adaptador de audio RadioShack 1202253 (Electrodomésticos) · marca nueva: RadioShack",
            salida,
        )
        self.assertIn(
            "3 revisados · 1 creados en el catálogo (1 marcas nuevas) · 0 vinculados",
            salida,
        )
        self.assertIn("sin categoría (1)", salida)
        self.assertIn("sin código de barras (1)", salida)
        self.assertIn(
            "Tipos de producto sin categoría (se agregan en ingestion/categorias.py): Llanta (1)",
            salida,
        )
        self.assertTrue(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )

    def test_dry_run(self):
        self.de_gollo()
        salida = self.correr("--dry-run")
        self.assertIn("1 creados en el catálogo", salida)
        self.assertFalse(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )

    def test_por_tienda_y_filtro(self):
        self.de_gollo()
        self.de_gollo(
            url="https://www.gollo.com/licuadora/p",
            name="Licuadora Oster",
            category="Licuadora",
            brand="Oster",
            barcodes=["7410063035124"],
        )
        self.assertIn(
            "Se van a revisar 0 productos", self.correr("--tienda", "monge")
        )
        salida = self.correr("--tienda", "gollo", "--filtro", "licuadora")
        self.assertIn("1 revisados · 1 creados", salida)
        self.assertFalse(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )


class AdminCrearEnCatalogoTests(PasarAlCatalogoTestCase):
    def test_accion_del_admin(self):
        self.client.force_login(
            User.objects.create_superuser(
                email="admin@pricepeek.test", password="Clave2026segura"
            )
        )
        creable = self.de_gollo()
        sin_codigo = self.de_gollo(
            url="https://www.gollo.com/sin-codigo/p", barcodes=[]
        )

        respuesta = self.client.post(
            reverse("admin:ingestion_storeproduct_changelist"),
            {
                "action": "crear_en_el_catalogo",
                "_selected_action": [creable.pk, sin_codigo.pk],
            },
            follow=True,
        )

        mensajes = [str(m) for m in respuesta.context["messages"]]
        self.assertIn(
            "1 productos creados en el catálogo y 0 vinculados a variantes que ya existían.",
            mensajes,
        )
        self.assertIn(
            "Adaptador de audio RadioShack 1202253: no tiene un código de barras válido",
            mensajes,
        )
        self.assertTrue(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )


class SecuenciasAtrasadasTests(PasarAlCatalogoTestCase):
    ATRASADA = [("product_images", 'public."ProductImages_id_seq"', 35)]
    COMANDO = "ingestion.management.commands.crear_productos"

    def correr(self, *argumentos):
        salida = StringIO()
        call_command("crear_productos", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_no_crea_nada_si_un_contador_de_ids_esta_atrasado(self):
        self.de_gollo()
        with mock.patch(
            f"{self.COMANDO}.secuencias_atrasadas", return_value=self.ATRASADA
        ):
            with self.assertRaisesMessage(
                CommandError, "product_images (el id más alto es 35)"
            ):
                self.correr()
        self.assertFalse(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )

    def test_arreglar_secuencias(self):
        self.de_gollo()
        with (
            mock.patch(
                f"{self.COMANDO}.secuencias_atrasadas",
                return_value=self.ATRASADA,
            ),
            mock.patch(f"{self.COMANDO}.arreglar_secuencias") as arreglar,
        ):
            salida = self.correr("--arreglar-secuencias")
        arreglar.assert_called_once_with(self.ATRASADA)
        self.assertIn("Contador de ids corregido en: product_images", salida)
        self.assertIn("1 creados en el catálogo", salida)

    def test_en_dry_run_solo_avisa(self):
        self.de_gollo()
        with mock.patch(
            f"{self.COMANDO}.secuencias_atrasadas", return_value=self.ATRASADA
        ):
            salida = self.correr("--dry-run")
        self.assertIn(
            "El contador de ids está atrasado en: product_images", salida
        )
        self.assertIn("1 creados en el catálogo", salida)

    def test_en_sqlite_no_hay_secuencias_que_revisar(self):
        from .catalogo import secuencias_atrasadas

        self.assertEqual(secuencias_atrasadas(), [])

    def test_un_error_de_la_base_detiene_el_comando_con_un_mensaje_claro(self):
        self.de_gollo()
        error = IntegrityError(
            'duplicate key value violates unique constraint "ProductImages_pkey"'
        )
        with mock.patch(
            f"{self.COMANDO}.crear_en_catalogo", side_effect=error
        ):
            with self.assertRaisesMessage(
                CommandError, "Ese producto no quedó a medias"
            ):
                self.correr()


class SugeridosPorCodigoTests(PasarAlCatalogoTestCase):
    def test_vincula_solo_los_sugeridos_por_codigo_de_barras(self):
        por_codigo = self.de_gollo(
            name="Salsa de tomate Heinz",
            barcodes=["013000000765"],
            status=Status.SUGGESTED,
            suggested_gtin="0013000000765",
            score=100,
            match_reason="mismo código de barras",
        )
        por_nombre = self.de_gollo(
            url="https://www.gollo.com/por-nombre/p",
            status=Status.SUGGESTED,
            suggested_gtin=GTIN_IPHONE_CATALOGO,
            score=80,
            match_reason="marca Apple · iphone 17",
        )
        salida = StringIO()
        call_command("crear_productos", stdout=salida)

        self.assertIn(
            "1 revisados · 0 creados en el catálogo (0 marcas nuevas) · 1 vinculados",
            salida.getvalue(),
        )  # el sugerido por nombre ni se revisa
        por_codigo.refresh_from_db()
        por_nombre.refresh_from_db()
        self.assertEqual(
            (por_codigo.status, por_nombre.status),
            (Status.CONFIRMED, Status.SUGGESTED),
        )
        self.assertTrue(
            Prices.objects.filter(
                gtin=self.variante_ketchup, id_store__name="Gollo"
            ).exists()
        )


class VariosFiltrosTests(PasarAlCatalogoTestCase):
    def test_crear_productos_con_varios_filtros(self):
        self.de_gollo()
        self.de_gollo(
            url="https://www.gollo.com/licuadora/p",
            name="Licuadora Oster",
            category="Licuadora",
            brand="Oster",
            barcodes=["7410063035124"],
        )
        self.de_gollo(
            url="https://www.gollo.com/cafetera/p",
            name="Cafetera Oster",
            category="Cafetera",
            brand="Oster",
            barcodes=["047362659408"],
        )
        salida = StringIO()
        call_command(
            "crear_productos",
            "--filtro",
            "licuadora",
            "ADAPTADOR",
            "--dry-run",
            stdout=salida,
        )
        self.assertIn("2 revisados · 2 creados", salida.getvalue())


class ConfirmarPorNombreTests(PasarAlCatalogoTestCase):
    def de_monge(self, url, gtin, puntaje, **cambios):
        datos = {
            "store_name": "Monge",
            "url": url,
            "name": "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB",
            "brand": "Apple",
            "barcodes": [],
            "status": Status.SUGGESTED,
            "suggested_gtin": gtin,
            "score": puntaje,
            "match_reason": "marca Apple · 17 iphone · 256GB · negro",
        }
        return self.de_gollo(**{**datos, **cambios})

    def correr(self, *argumentos):
        salida = StringIO()
        call_command("crear_productos", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_vincula_los_sugeridos_por_nombre_desde_ese_puntaje(self):
        iphone = self.de_monge(
            "https://tiendamonge.com/iphone-17", GTIN_IPHONE_CATALOGO, 85
        )
        bajo = self.de_monge(
            "https://tiendamonge.com/salsa",
            "0013000000765",
            72,
            name="Salsa Heinz",
        )

        salida = self.correr("--confirmar-desde", "80")

        self.assertIn(
            "vinculado por nombre: Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB →",
            salida,
        )
        self.assertIn("(puntaje 85)", salida)
        self.assertIn(
            "1 revisados · 0 creados en el catálogo (0 marcas nuevas) · 1 vinculados a variantes que ya existían (1 por nombre)",
            salida,
        )
        iphone.refresh_from_db()
        bajo.refresh_from_db()
        self.assertEqual(
            (iphone.status, iphone.score, iphone.match_reason),
            (Status.CONFIRMED, 85, "marca Apple · 17 iphone · 256GB · negro"),
        )
        self.assertEqual(bajo.status, Status.SUGGESTED)
        self.assertTrue(
            Prices.objects.filter(
                gtin_id=GTIN_IPHONE_CATALOGO, id_store__name="Monge"
            ).exists()
        )

    def test_sin_la_opcion_no_vincula_por_nombre(self):
        self.de_monge(
            "https://tiendamonge.com/iphone-17", GTIN_IPHONE_CATALOGO, 100
        )
        self.assertIn("Se van a revisar 0 productos", self.correr())

    def test_dry_run(self):
        self.de_monge(
            "https://tiendamonge.com/iphone-17", GTIN_IPHONE_CATALOGO, 85
        )
        self.assertIn(
            "(1 por nombre)",
            self.correr("--confirmar-desde", "70", "--dry-run"),
        )
        self.assertFalse(
            Prices.objects.filter(id_store__name="Monge").exists()
        )

    def test_no_vincula_si_la_tienda_trae_otro_codigo_de_barras(self):
        self.de_monge(
            "https://www.walmart.co.cr/batidora-roja/p",
            GTIN_IPHONE_CATALOGO,
            80,
            store_name="Walmart",
            barcodes=["7441001601064"],
            match_reason="código distinto: la tienda dice 7441001601064 y el catálogo …",
        )
        salida = self.correr("--confirmar-desde", "70")
        self.assertIn(
            "la tienda publica otro código de barras (7441001601064)", salida
        )
        self.assertIn(f"Omitidos: {OTRO_CODIGO} (1)", salida)
        self.assertFalse(
            Prices.objects.filter(id_store__name="Walmart").exists()
        )

    def test_si_dos_paginas_de_la_tienda_empatan_no_vincula_ninguna(self):
        roja = self.de_monge(
            "https://tiendamonge.com/roja", GTIN_IPHONE_CATALOGO, 100
        )
        blanca = self.de_monge(
            "https://tiendamonge.com/blanca", GTIN_IPHONE_CATALOGO, 100
        )
        mejor = self.de_monge(
            "https://tiendamonge.com/salsa-1", "0013000000765", 90
        )
        peor = self.de_monge(
            "https://tiendamonge.com/salsa-2", "0013000000765", 80
        )
        productos = [peor, roja, blanca, mejor]

        catalogo = Catalogo()
        catalogo.anotar_sugerencias(productos, 70)
        resultados = [
            crear_en_catalogo(p, catalogo, confirmar_desde=70)
            for p in productos
        ]

        self.assertEqual(
            [(r.tipo, r.grupo) for r in resultados],
            [
                (OMITIDO, OTRA_SE_PARECE_MAS),
                (OMITIDO, EMPATE),
                (OMITIDO, EMPATE),
                (VINCULADO, ""),
            ],
        )
        self.assertEqual(
            list(
                Prices.objects.filter(id_store__name="Monge").values_list(
                    "product_web_url", flat=True
                )
            ),
            [mejor.url],
        )

    def test_si_otra_pagina_coincide_por_codigo_gana_esa(self):
        por_codigo = self.de_gollo(
            store_name="Monge",
            url="https://tiendamonge.com/salsa-con-codigo",
            name="Salsa de tomate Heinz",
            barcodes=["013000000765"],
        )
        por_nombre = self.de_monge(
            "https://tiendamonge.com/salsa", "0013000000765", 90
        )
        salida = self.correr("--confirmar-desde", "70")
        self.assertIn(
            "1 vinculados a variantes que ya existían (0 por nombre)", salida
        )
        self.assertIn("ya quedó vinculada a esa variante", salida)
        precio = Prices.objects.get(
            gtin_id="0013000000765", id_store__name="Monge"
        )
        self.assertEqual(precio.product_web_url, por_codigo.url)
        por_nombre.refresh_from_db()
        self.assertEqual(por_nombre.status, Status.SUGGESTED)


class MinTiendasTests(PasarAlCatalogoTestCase):
    def correr(self, *argumentos):
        salida = StringIO()
        call_command("crear_productos", "-v", "2", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_solo_crea_los_que_estan_en_varias_tiendas(self):
        self.de_gollo()
        self.de_gollo(
            url="https://www.gollo.com/licuadora/p",
            name="Licuadora Oster",
            category="Licuadora",
            brand="Oster",
            barcodes=["7410063035124"],
        )
        # El mismo adaptador en Walmart, con el código escrito con 14 dígitos.
        self.de_gollo(
            store_name="Walmart",
            url="https://www.walmart.co.cr/adaptador/p",
            barcodes=["0" + GTIN_ADAPTADOR],
        )

        salida = self.correr("--min-tiendas", "2")

        self.assertIn("1 creados en el catálogo", salida)
        self.assertIn("1 vinculados a variantes que ya existían", salida)
        self.assertIn(
            "omitido: Licuadora Oster: solo está en 1 tienda(s) (Gollo): se piden 2",
            salida,
        )
        self.assertIn("en pocas tiendas (1)", salida)
        self.assertTrue(
            ProductVariants.objects.filter(gtin=GTIN_ADAPTADOR).exists()
        )
        self.assertFalse(
            ProductVariants.objects.filter(gtin="7410063035124").exists()
        )

    def test_cuenta_las_otras_tiendas_aunque_se_filtre_por_una(self):
        self.de_gollo()
        self.de_gollo(
            store_name="Walmart", url="https://www.walmart.co.cr/adaptador/p"
        )
        self.assertIn(
            "1 revisados · 0 creados",
            self.correr("--tienda", "gollo", "--min-tiendas", "3"),
        )
        self.assertIn(
            "1 revisados · 1 creados",
            self.correr("--tienda", "gollo", "--min-tiendas", "2"),
        )

    def test_los_que_ya_estan_en_el_catalogo_se_vinculan_igual(self):
        producto = self.de_gollo(barcodes=[GTIN_IPHONE_CATALOGO])
        self.assertIn("1 vinculados", self.correr("--min-tiendas", "5"))
        producto.refresh_from_db()
        self.assertEqual(producto.status, Status.CONFIRMED)

    def test_min_tiendas_invalido(self):
        with self.assertRaises(CommandError):
            self.correr("--min-tiendas", "0")
