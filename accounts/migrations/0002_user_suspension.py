"""Migración de base de datos 0002_user_suspension para la aplicación accounts."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="suspended_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="suspended at"
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="suspended_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="suspension_reason",
            field=models.TextField(
                blank=True, verbose_name="suspension reason"
            ),
        ),
    ]
