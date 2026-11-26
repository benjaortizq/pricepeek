"""Pruebas automatizadas de tests para la aplicación reviews."""

from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import ReviewForm
from .models import ReviewPhoto, Reviews
from products.models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    ProductVariants,
    Products,
    Stores,
)


class ReviewFormTests(TestCase):
    def test_acepta_calificacion_y_comentario_validos(self):
        form = ReviewForm(
            data={"rating": "5", "content": "Muy buen producto."}
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["rating"], 5)

    def test_rechaza_calificaciones_fuera_del_rango_de_una_a_cinco(self):
        for rating in ("0", "6"):
            with self.subTest(rating=rating):
                form = ReviewForm(
                    data={"rating": rating, "content": "Comentario."}
                )
                self.assertFalse(form.is_valid())
                self.assertIn("rating", form.errors)

    def test_requiere_un_comentario(self):
        form = ReviewForm(data={"rating": "4", "content": ""})

        self.assertFalse(form.is_valid())
        self.assertIn("content", form.errors)

    def test_la_foto_es_opcional(self):
        form = ReviewForm(data={"rating": "4", "content": "Comentario."})

        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data["photo"])


class ReviewSubmissionTests(TestCase):
    modelos_sin_migracion = [
        Brands,
        Categories,
        Currencies,
        Stores,
        Products,
        ProductVariants,
        ProductImages,
        Prices,  # la página del producto también muestra los precios
        Reviews,
    ]

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for modelo in cls.modelos_sin_migracion:
                editor.create_model(modelo)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.modelos_sin_migracion):
                editor.delete_model(modelo)

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.brand = Brands.objects.create(
            name="Marca",
            slug="marca",
            created_at=now,
            updated_at=now,
        )
        cls.category = Categories.objects.create(
            name="Categoría",
            created_at=now,
            updated_at=now,
        )
        cls.product = Products.objects.create(
            name="Producto",
            brand=cls.brand,
            category=cls.category,
            created_at=now,
            updated_at=now,
        )
        cls.variant = ProductVariants.objects.create(
            product=cls.product,
            gtin="1234567890123",
            name="Variante 1",
            created_at=now,
            updated_at=now,
        )
        cls.other_variant = ProductVariants.objects.create(
            product=cls.product,
            gtin="1234567890124",
            name="Variante 2",
            created_at=now,
            updated_at=now,
        )
        cls.user = get_user_model().objects.create_user(
            email="cliente@example.com",
            password="test-password",
        )

    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.override_media = override_settings(
            MEDIA_ROOT=self.media_directory.name
        )
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.addCleanup(self.media_directory.cleanup)
        self.client.force_login(self.user)
        self.url = reverse("detalle_producto", kwargs={"pk": self.product.pk})

    def test_cliente_publica_resena_con_calificacion_y_comentario(self):
        response = self.client.post(
            self.url,
            {"rating": "5", "content": "Excelente producto."},
        )

        self.assertRedirects(response, self.url)
        resena = Reviews.objects.get(user_id=self.user.pk)
        self.assertEqual(resena.score, 5)
        self.assertEqual(resena.content, "Excelente producto.")

    def test_no_permite_publicar_otra_resena_para_el_producto_en_otra_variante(
        self,
    ):
        now = timezone.now()
        Reviews.objects.create(
            user_id=self.user.pk,
            variant=self.other_variant,
            content="Ya reseñado.",
            score=4,
            created_at=now,
            updated_at=now,
        )

        response = self.client.post(
            self.url,
            {"rating": "3", "content": "Intento duplicado."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Ya publicaste una reseña para este producto."
        )
        self.assertEqual(
            Reviews.objects.filter(user_id=self.user.pk).count(), 1
        )

    def test_cliente_puede_adjuntar_una_foto(self):
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1)).save(image_buffer, format="PNG")
        image_buffer.seek(0)

        response = self.client.post(
            self.url,
            {
                "rating": "4",
                "content": "Con foto.",
                "photo": SimpleUploadedFile(
                    "resena.png",
                    image_buffer.getvalue(),
                    content_type="image/png",
                ),
            },
        )

        self.assertRedirects(response, self.url)
        foto = ReviewPhoto.objects.get()
        self.assertTrue(foto.image.name.startswith("reviews/"))

    def test_error_al_guardar_foto_revierte_la_resena_y_elimina_el_archivo(
        self,
    ):
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1)).save(image_buffer, format="PNG")
        image_buffer.seek(0)
        self.client.raise_request_exception = False

        with patch(
            "reviews.models.ReviewPhoto.save", side_effect=DatabaseError
        ):
            response = self.client.post(
                self.url,
                {
                    "rating": "4",
                    "content": "Con foto.",
                    "photo": SimpleUploadedFile(
                        "resena.png",
                        image_buffer.getvalue(),
                        content_type="image/png",
                    ),
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(Reviews.objects.filter(user_id=self.user.pk).exists())
        self.assertFalse(ReviewPhoto.objects.exists())
        self.assertEqual(
            list(Path(self.media_directory.name).rglob("*.png")), []
        )
