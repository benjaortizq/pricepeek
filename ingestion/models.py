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


class StoreProduct(models.Model):
    """Un producto tal como lo publica una tienda, antes de vincularlo al catálogo (SCRUM-56).

    python manage.py obtener_productos los guarda y sugiere con qué variante del catálogo
    coincide cada uno. Una persona confirma la sugerencia en el admin; al confirmarla se
    crea el precio de esa tienda (tabla prices) y desde ahí actualizar_precios lo mantiene.
    """

    class Status(models.TextChoices):
        NO_MATCH = "no_match", "Sin coincidencia"
        SUGGESTED = "suggested", "Coincidencia sugerida"
        CONFIRMED = "confirmed", "Vinculado al catálogo"
        REJECTED = "rejected", "Coincidencia rechazada"

    store_name = models.CharField("tienda", max_length=100)
    url = models.URLField("enlace", max_length=500, unique=True)
    sku = models.CharField("código de la tienda", max_length=64, blank=True)
    name = models.CharField("nombre", max_length=255)
    brand = models.CharField("marca", max_length=100, blank=True)
    product_model = models.CharField("modelo", max_length=100, blank=True)
    color = models.CharField("color", max_length=60, blank=True)
    category = models.CharField("categoría en la tienda", max_length=255, blank=True)
    image_url = models.URLField("imagen", max_length=1000, blank=True)
    list_price = models.PositiveIntegerField("precio de lista", null=True, blank=True)
    final_price = models.PositiveIntegerField("precio final", null=True, blank=True)
    is_available = models.BooleanField("disponible", default=True)
    barcodes = models.JSONField("códigos de barras", default=list, blank=True)
    status = models.CharField("estado", max_length=20, choices=Status.choices, default=Status.NO_MATCH)
    # El gtin de la variante sugerida (product_variants.gtin, la misma llave que usa prices).
    # No es una llave foránea para no depender de las migraciones de products.
    suggested_gtin = models.CharField("variante del catálogo (código de barras)", max_length=14, blank=True)
    score = models.PositiveSmallIntegerField("puntaje", null=True, blank=True)
    match_reason = models.CharField("por qué coincide", max_length=255, blank=True)
    created_at = models.DateTimeField("obtenido", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["store_name", "name"]
        verbose_name = "producto de tienda"
        verbose_name_plural = "productos de tiendas"

    def __str__(self):
        return f"{self.store_name}: {self.name}"

    @property
    def suggested_variant(self):
        from products.models import ProductVariants

        if not self.suggested_gtin:
            return None
        return ProductVariants.objects.select_related("product__brand").filter(gtin=self.suggested_gtin).first()
