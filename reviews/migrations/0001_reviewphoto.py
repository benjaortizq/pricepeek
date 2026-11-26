"""Migración de base de datos 0001_reviewphoto para la aplicación reviews."""

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ReviewPhoto",
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
                ("review_id", models.PositiveBigIntegerField(unique=True)),
                ("image", models.ImageField(upload_to="reviews/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "review_photos"},
        ),
    ]
