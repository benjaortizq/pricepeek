"""Configuración de la aplicación Django de la aplicación wishlist."""

from django.apps import AppConfig


class WishlistConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wishlist"
