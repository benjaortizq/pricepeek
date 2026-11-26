"""Migración de base de datos 0003_privacy_consent para la aplicación accounts."""

import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0002_user_suspension"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrivacyConsent",
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
                ("policy_version", models.CharField(max_length=20)),
                (
                    "accepted_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="privacy_consents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "accounts_privacy_consent",
                "ordering": ["-accepted_at"],
            },
        ),
    ]
