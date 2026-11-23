from django.conf import settings
from django.db import models
from accounts.models import AccountsUser
from products.models import ProductVariants


class Reviews(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AccountsUser, models.DO_NOTHING, db_column='user')
    content = models.TextField()
    variant = models.ForeignKey(ProductVariants, models.DO_NOTHING)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    score = models.SmallIntegerField()

    class Meta:
        managed = False
        db_table = 'reviews'
        unique_together = (('user', 'variant'),)


class ReviewPhoto(models.Model):
    review_id = models.PositiveBigIntegerField(unique=True)
    image = models.ImageField(upload_to="reviews/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_photos"


class ReviewReport(models.Model):
    """Denuncia de una reseña inapropiada (RF-28) y la decisión del administrador (RF-41)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        KEPT = "kept", "Reseña mantenida"
        DELETED = "deleted", "Reseña eliminada"

    # Reviews es una tabla de Supabase (managed = False), por eso no es una llave foránea.
    review_id = models.PositiveBigIntegerField()
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_reports"
    )
    # Autor de la reseña, guardado aparte porque la reseña puede borrarse: así el administrador
    # sigue viendo cuántas reseñas de un cliente se eliminaron por incumplir las políticas (RF-42).
    review_author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reportes_recibidos",
    )
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        db_table = "review_reports"
        ordering = ["created_at"]
        constraints = [
            # Un cliente solo puede reportar una vez la misma reseña.
            models.UniqueConstraint(
                fields=["review_id", "reporter"], name="un_reporte_por_cliente_y_resena"
            ),
        ]

    def __str__(self):
        return f"Reporte de la reseña {self.review_id} ({self.get_status_display()})"
