"""Migración de base de datos 0002_currency_store_state para la aplicación products."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0001_initial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Currencies",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                primary_key=True, serialize=False
                            ),
                        ),
                        ("name", models.CharField()),
                        ("symbol", models.CharField()),
                        ("created_at", models.DateTimeField()),
                        ("updated_at", models.DateTimeField()),
                    ],
                    options={"db_table": "currencies", "managed": False},
                ),
                migrations.CreateModel(
                    name="Stores",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                primary_key=True, serialize=False
                            ),
                        ),
                        ("name", models.CharField()),
                        ("created_at", models.DateTimeField()),
                        ("updated_at", models.DateTimeField()),
                    ],
                    options={"db_table": "stores", "managed": False},
                ),
            ],
        ),
    ]
