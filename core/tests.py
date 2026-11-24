from django.templatetags.static import static
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from .translations import translate_text


class SiteTranslationTests(SimpleTestCase):
    def test_translates_interface_text_to_english(self):
        with translation.override("en"):
            self.assertEqual(translate_text("Activar modo oscuro"), "Enable dark mode")

    def test_keeps_spanish_when_no_translation_exists(self):
        with translation.override("en"):
            self.assertEqual(translate_text("Texto sin traducir"), "Texto sin traducir")

    def test_formats_dynamic_values(self):
        with translation.override("en"):
            self.assertEqual(
                translate_text("Hola, {usuario}", usuario="Alex"),
                "Hello, Alex",
            )

    def test_translates_a_dynamic_message_after_its_values_were_formatted(self):
        mensaje = "La cuenta de ana@example.com fue suspendida."
        with translation.override("en"):
            self.assertEqual(
                translate_text(mensaje),
                "The account for ana@example.com was suspended.",
            )
        with translation.override("es"):
            self.assertEqual(translate_text(mensaje), mensaje)

    def test_translates_english_model_labels_to_spanish(self):
        with translation.override("es"):
            self.assertEqual(translate_text("Client"), "Cliente")
            self.assertEqual(translate_text("Enterprise"), "Empresa")
            self.assertEqual(translate_text("Admin"), "Administrador")


class LanguageSelectorTests(SimpleTestCase):
    def test_set_language_persists_english_in_cookie(self):
        response = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": reverse("login")},
        )

        self.assertRedirects(response, reverse("login"))
        self.assertEqual(response.cookies["django_language"].value, "en")

    def test_login_page_contains_language_and_theme_controls(self):
        response = self.client.get(reverse("login"))
        html = response.content.decode()

        self.assertContains(response, 'name="language" value="en"')
        self.assertContains(response, "data-theme-toggle")
        self.assertIn("pricepeek-theme", html)

    def test_theme_assets_use_cache_busting_urls(self):
        response = self.client.get(reverse("login"))

        for asset in ("js/main.js", "js/tailwind.config.js", "css/base.css"):
            self.assertContains(
                response,
                f'{static(asset)}?v=20261123-theme',
            )

    def test_page_language_follows_language_cookie(self):
        self.client.cookies["django_language"] = "en"
        response = self.client.get(reverse("login"))

        self.assertContains(response, '<html class="h-full" lang="en">')
        self.assertContains(response, "Log in")
        self.assertNotContains(response, "Iniciar sesión")
