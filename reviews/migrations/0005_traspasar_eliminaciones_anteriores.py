"""Las reseñas que se eliminaron antes de existir el registro (por reportes) pasan a él.

Hasta ahora la eliminación solo quedaba en los reportes (status «deleted»); desde aquí las
infracciones se cuentan con ReviewDeletion. La política no se conocía: queda «sin clasificar».
"""

from django.db import migrations


def traspasar(apps, schema_editor):
    ReviewReport = apps.get_model("reviews", "ReviewReport")
    ReviewDeletion = apps.get_model("reviews", "ReviewDeletion")
    ya_registradas = set(
        ReviewDeletion.objects.values_list("review_id", flat=True)
    )
    grupos = {}
    for reporte in ReviewReport.objects.filter(status="deleted").order_by(
        "resolved_at", "id"
    ):
        grupos.setdefault(reporte.review_id, []).append(reporte)
    ReviewDeletion.objects.bulk_create(
        [
            ReviewDeletion(
                review_id=review_id,
                author_id=reportes[0].review_author_id,
                deleted_by_id=reportes[0].resolved_by_id,
                deleted_at=reportes[0].resolved_at or reportes[0].created_at,
                policy="sin_clasificar",
                reason=reportes[0].resolution_note
                or "Eliminada por reportes, antes de registrar la razón.",
                reports=len(reportes),
            )
            for review_id, reportes in grupos.items()
            if review_id not in ya_registradas
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0004_eliminaciones_de_resenas"),
    ]

    operations = [
        migrations.RunPython(traspasar, migrations.RunPython.noop),
    ]
