import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def completar_autores(apps, schema_editor):
    """Llena el autor de los reportes cuya reseña todavía existe en la tabla reviews de Supabase."""
    conexion = schema_editor.connection
    if "reviews" not in conexion.introspection.table_names():
        return  # base de pruebas: la tabla de Supabase no existe
    with conexion.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_reports
            SET review_author_id = (
                SELECT r."user" FROM reviews r WHERE r.id = review_reports.review_id
            )
            WHERE review_author_id IS NULL
              AND EXISTS (
                SELECT 1 FROM reviews r JOIN accounts_user u ON u.id = r."user"
                WHERE r.id = review_reports.review_id
              )
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0002_reviewreport"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewreport",
            name="review_author",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reportes_recibidos",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(completar_autores, migrations.RunPython.noop),
    ]
