"""Crea price_history (issue «Historial de precios») y guarda el precio
vigente de cada tienda como su primer registro.

Antes de esta tabla no se guardaba ningún precio anterior, así que el
historial empieza con lo que había en prices: cada fila queda con la fecha de
su última actualización (updated_at), la última vez que se confirmó ese
precio.
"""

from datetime import timezone as zona
from decimal import ROUND_HALF_UP, Decimal

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone
from django.utils.dateparse import parse_datetime

LOTE = 500


def guardar_precios_vigentes(apps, schema_editor):
    conexion = schema_editor.connection
    # prices es una tabla de Supabase: en la base de las pruebas no existe.
    if "prices" not in conexion.introspection.table_names():
        return
    PriceHistory = apps.get_model("products", "PriceHistory")
    if PriceHistory.objects.exists():
        return
    # En el historial de migraciones Prices no tiene sus llaves foráneas
    # (Django no sigue los campos de los modelos managed = False), así que
    # se lee prices con SQL.
    with conexion.cursor() as cursor:
        cursor.execute(
            "SELECT id_store, gtin, currency, price, discount, is_available,"
            " updated_at FROM prices ORDER BY id"
        )
        filas = cursor.fetchall()
    registros = []
    for tienda, gtin, moneda, precio, descuento, disponible, fecha in filas:
        descuento = Decimal(str(descuento or 0))
        if isinstance(fecha, str):  # SQLite devuelve texto, en UTC
            fecha = parse_datetime(fecha)
        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, zona.utc)
        final = None
        if precio is not None:
            final = int(
                (Decimal(precio) * (1 - descuento)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        registros.append(
            PriceHistory(
                store_id=tienda,
                gtin_id=gtin,
                currency_id=moneda,
                price=precio,
                discount=descuento,
                final_price=final,
                is_available=bool(disponible),
                source="inicial",
                recorded_at=fecha,
            )
        )
    PriceHistory.objects.bulk_create(registros, batch_size=LOTE)


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0006_merge_20261125_0056"),
    ]

    operations = [
        migrations.CreateModel(
            name="PriceHistory",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "price",
                    models.IntegerField(
                        blank=True, null=True, verbose_name="precio de lista"
                    ),
                ),
                (
                    "discount",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=3,
                        verbose_name="descuento",
                    ),
                ),
                (
                    "final_price",
                    models.IntegerField(
                        blank=True, null=True, verbose_name="precio final"
                    ),
                ),
                (
                    "is_available",
                    models.BooleanField(verbose_name="disponible"),
                ),
                (
                    "previous_final_price",
                    models.IntegerField(blank=True, null=True),
                ),
                (
                    "was_available",
                    models.BooleanField(blank=True, null=True),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("inicial", "Precio al empezar el historial"),
                            ("scraping", "Obtención de datos"),
                            ("empresa", "Portal de empresas"),
                            ("vinculacion", "Vinculación de productos"),
                        ],
                        max_length=20,
                        verbose_name="origen",
                    ),
                ),
                ("recorded_at", models.DateTimeField(verbose_name="fecha")),
                (
                    "currency",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="products.currencies",
                    ),
                ),
                (
                    "gtin",
                    models.ForeignKey(
                        db_column="gtin",
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="products.productvariants",
                        to_field="gtin",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="products.stores",
                    ),
                ),
            ],
            options={
                "db_table": "price_history",
                "indexes": [
                    models.Index(
                        fields=["gtin", "recorded_at"],
                        name="historial_por_presentacion",
                    ),
                    models.Index(
                        fields=["store", "gtin", "recorded_at"],
                        name="historial_por_tienda",
                    ),
                    models.Index(
                        fields=["recorded_at"], name="historial_por_fecha"
                    ),
                ],
            },
        ),
        migrations.RunPython(
            guardar_precios_vigentes, migrations.RunPython.noop
        ),
    ]
