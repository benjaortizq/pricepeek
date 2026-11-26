"""Migración de base de datos 0004_remove_anonymous_product_views para la aplicación products."""

from django.db import migrations


def borrar_visitas_anonimas(apps, schema_editor):
    ProductView = apps.get_model("products", "ProductView")
    ProductView.objects.using(schema_editor.connection.alias).filter(
        user__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_productview"),
    ]

    operations = [
        migrations.RunPython(
            borrar_visitas_anonimas, migrations.RunPython.noop
        ),
    ]
