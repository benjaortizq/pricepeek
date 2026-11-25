from django.conf import settings
from django.db import models
from django.utils import timezone
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


class ReviewDeletion(models.Model):
    """Registro de cada reseña que un administrador eliminó por incumplir las políticas de uso.

    Guarda qué política incumplió, la razón y lo que decía la reseña, para que la eliminación
    tenga trazabilidad aunque la reseña ya no exista. Es también de donde se cuentan las
    infracciones de cada cliente (RF-42), venga o no la eliminación de un reporte.
    """

    class Policy(models.TextChoices):
        # Categorías de incumplimiento que pueden justificar eliminar una reseña.
        NOT_RELEVANT = "no_pertinente", "No es pertinente al producto"
        DISRESPECTFUL = "irrespetuoso", "Irrespetuoso, ofensivo o discriminatorio"
        NOT_LEGITIMATE = "no_legitima", "No se basa en una experiencia legítima"
        MISLEADING = "enganoso", "Engañoso"
        DEFAMATORY = "difamatorio", "Difamatorio"
        PRIVACY = "privacidad", "Invade la privacidad de otras personas"
        PROMOTIONAL = "promocional", "Promocional no solicitado"
        ILLEGAL = "ilegal", "Ilegal o infringe derechos de terceros"
        # Solo para las eliminaciones anteriores a este registro (migración 0004).
        UNCLASSIFIED = "sin_clasificar", "Sin clasificar"

    SELECTABLE = Policy.choices[:-1]  # todas menos «Sin clasificar», que es la última

    # Reviews es una tabla de Supabase (managed = False), por eso no es una llave foránea.
    review_id = models.PositiveBigIntegerField("reseña", db_index=True)
    # Como ReviewReport.review_author: si el cliente borra su cuenta, se va con sus datos.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="autor",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="resenas_eliminadas",
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="eliminada por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    deleted_at = models.DateTimeField("eliminada el", default=timezone.now)
    policy = models.CharField("política incumplida", max_length=20, choices=Policy.choices)
    reason = models.TextField("razón de la eliminación")
    product_name = models.CharField("producto", max_length=255, blank=True)
    variant_name = models.CharField("presentación", max_length=255, blank=True)
    content = models.TextField("texto de la reseña", blank=True)
    score = models.SmallIntegerField("calificación", null=True, blank=True)
    reports = models.PositiveIntegerField("reportes pendientes que tenía", default=0)
    author_suspended = models.BooleanField("se suspendió al autor", default=False)

    class Meta:
        db_table = "review_deletions"
        ordering = ["-deleted_at"]
        verbose_name = "reseña eliminada"
        verbose_name_plural = "reseñas eliminadas"

    def __str__(self):
        return f"Reseña {self.review_id} eliminada ({self.get_policy_display()})"
