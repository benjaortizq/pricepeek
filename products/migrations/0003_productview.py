"""Visitas al detalle de los productos, para saber cuáles son populares (ver products/popularidad.py).

Solo crea la tabla product_views; no toca las tablas de Supabase (products, prices…).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_extensiones_busqueda"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductView",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("product_id", models.PositiveBigIntegerField()),
                ("visitor", models.CharField(max_length=64)),
                ("hour", models.DateTimeField()),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_views",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "product_views",
                "indexes": [models.Index(fields=["product_id", "hour"], name="product_views_por_producto")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("product_id", "visitor", "hour"),
                        name="una_visita_por_visitante_y_hora",
                    )
                ],
            },
        ),
    ]
