"""Mantiene ``accounts_user.from_store`` disponible en el esquema de pruebas.

En PostgreSQL la columna y su FK ya existen en Supabase y esta migración no
altera ese esquema. El modelo User que Django administra para las pruebas no
incluye esa columna adicional, por lo que SQLite debe crearla antes de ejecutar
las consultas que unen AccountsUser.
"""

from django.db import migrations


def asegurar_columna(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "sqlite":
        return

    tablas = connection.introspection.table_names()
    if "accounts_user" not in tablas:
        return
    with connection.cursor() as cursor:
        columnas = {
            columna.name
            for columna in connection.introspection.get_table_description(
                cursor,
                "accounts_user",
            )
        }
    if "from_store" not in columnas:
        schema_editor.execute(
            'ALTER TABLE "accounts_user" ADD COLUMN "from_store" bigint NULL'
        )


def noop(apps, schema_editor):
    """La columna física nunca se elimina al revertir esta migración."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_accountsuser_accountsusergroups_and_more"),
    ]

    operations = [
        migrations.RunPython(asegurar_columna, noop),
    ]
