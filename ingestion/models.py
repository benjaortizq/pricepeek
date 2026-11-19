from django.db import models


class Incident(models.Model):
    """Registro de incidencias de la obtención de datos (RF-38, RF-43)."""

    GTIN_MAX_LENGTH = 64
    NAME_MAX_LENGTH = 255

    class Kind(models.TextChoices):
        INVALID_BARCODE = "invalid_barcode", "Código de barras inválido"
        # Actualización de precios desde las tiendas (SCRUM-56)
        DOWNLOAD_FAILED = "download_failed", "No se pudo descargar la página"
        PRODUCT_NOT_FOUND = "product_not_found", "Producto no encontrado en la tienda"
        PRICE_NOT_FOUND = "price_not_found", "Precio no encontrado en la página"
        BARCODE_MISMATCH = "barcode_mismatch", "El código de barras no coincide"
        SUSPICIOUS_PRICE = "suspicious_price", "Cambio de precio sospechoso"

    kind = models.CharField("tipo", max_length=30, choices=Kind.choices, default=Kind.INVALID_BARCODE)
    store_name = models.CharField("comercio", max_length=NAME_MAX_LENGTH, blank=True)
    product_name = models.CharField("producto", max_length=NAME_MAX_LENGTH, blank=True)
    # Tal como llegó de la fuente: puede estar vacío o ser basura, por eso no es una FK.
    gtin = models.CharField("código de barras recibido", max_length=GTIN_MAX_LENGTH, blank=True)
    reason = models.TextField("motivo")
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.product_name or self.gtin or 'sin datos'}"
