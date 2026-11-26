"""Modelos de datos de la aplicación wishlist."""

from django.conf import settings
from django.db import models


class WishlistItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist_items",
    )
    variant = models.ForeignKey(
        "products.ProductVariants",
        on_delete=models.CASCADE,
        related_name="wishlisted_by",
    )
    alert_enabled = models.BooleanField(default=True)
    target_price = models.IntegerField(null=True, blank=True)
    currency = models.ForeignKey(
        "products.Currencies",
        on_delete=models.PROTECT,
        default=1,  # type: ignore[arg-type]  # Django permite usar el ID de la FK como default.
    )
    store = models.ForeignKey(
        "products.Stores",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    baseline_price = models.IntegerField(null=True, blank=True)
    last_notified_price = models.IntegerField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wishlist_items"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "variant"],
                name="wishlist_user_variant_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["variant", "currency"],
                name="idx_wishlist_active_alerts",
                condition=models.Q(alert_enabled=True),
            )
        ]
