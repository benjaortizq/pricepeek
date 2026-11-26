"""Migración de base de datos 0001_initial para la aplicación wishlist."""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("products", "0002_currency_store_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WishlistItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("alert_enabled", models.BooleanField(default=True)),
                ("target_price", models.IntegerField(blank=True, null=True)),
                ("baseline_price", models.IntegerField(blank=True, null=True)),
                (
                    "last_notified_price",
                    models.IntegerField(blank=True, null=True),
                ),
                (
                    "last_notified_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "currency",
                    models.ForeignKey(
                        default=1,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="products.currencies",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="products.stores",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wishlist_items",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "variant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wishlisted_by",
                        to="products.productvariant",
                    ),
                ),
            ],
            options={
                "db_table": "wishlist_items",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "variant"),
                        name="wishlist_user_variant_uniq",
                    )
                ],
                "indexes": [
                    models.Index(
                        fields=["variant", "currency"],
                        name="idx_wishlist_active_alerts",
                        condition=models.Q(alert_enabled=True),
                    )
                ],
            },
        ),
    ]
