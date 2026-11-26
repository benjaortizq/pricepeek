"""Modelos de datos de la aplicación ingestion."""

from django.conf import settings
from django.db import models


class Incident(models.Model):
    """Registro de incidencias de la obtención de datos (RF-38, RF-43)."""

    GTIN_MAX_LENGTH = 64
    NAME_MAX_LENGTH = 255
    RESOLUTION_MAX_LENGTH = 255

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        RESOLVED = "resolved", "Resuelta"

    class Kind(models.TextChoices):
        INVALID_BARCODE = "invalid_barcode", "Código de barras inválido"
        # Actualización de precios desde las tiendas (SCRUM-56)
        DOWNLOAD_FAILED = "download_failed", "No se pudo descargar la página"
        PRODUCT_NOT_FOUND = (
            "product_not_found",
            "Producto no encontrado en la tienda",
        )
        PRICE_NOT_FOUND = (
            "price_not_found",
            "Precio no encontrado en la página",
        )
        BARCODE_MISMATCH = (
            "barcode_mismatch",
            "El código de barras no coincide",
        )
        SUSPICIOUS_PRICE = "suspicious_price", "Cambio de precio sospechoso"

    kind = models.CharField(
        "tipo",
        max_length=30,
        choices=Kind.choices,
        default=Kind.INVALID_BARCODE,
    )
    store_name = models.CharField(
        "comercio", max_length=NAME_MAX_LENGTH, blank=True
    )
    product_name = models.CharField(
        "producto", max_length=NAME_MAX_LENGTH, blank=True
    )
    # Tal como llegó de la fuente: puede estar vacío o ser basura, por eso no es una FK.
    gtin = models.CharField(
        "código de barras recibido", max_length=GTIN_MAX_LENGTH, blank=True
    )
    reason = models.TextField("motivo")
    # Los campos nuevos llevan db_default para que el código que ya está corriendo (el
    # actualizar_precios de cada hora) pueda seguir guardando incidencias antes de actualizarse.

    # Lo que se leyó de la tienda, para resolverla sin volver a descargar la página: el precio
    # nuevo de un cambio sospechoso o los códigos de barras que publica la tienda.
    details = models.JSONField(
        "datos leídos de la tienda", default=dict, db_default={}, blank=True
    )
    created_at = models.DateTimeField("fecha", auto_now_add=True)
    status = models.CharField(
        "estado",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_default=Status.PENDING,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="resuelta por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField("resuelta el", null=True, blank=True)
    resolution = models.CharField(
        "qué se hizo",
        max_length=RESOLUTION_MAX_LENGTH,
        blank=True,
        db_default="",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"

    def __str__(self):
        return f"{self.get_kind_display()}: {self.product_name or self.gtin or 'sin datos'}"

    def _partes_del_motivo(self):
        # La obtención y la actualización de precios anotan la página de la tienda en la última línea.
        texto, _, ultima = self.reason.strip().rpartition("\n")
        ultima = ultima.strip()
        if texto and ultima.startswith(("http://", "https://")):
            return texto.strip(), ultima
        return self.reason.strip(), ""

    @property
    def motivo(self):
        """El motivo sin la dirección de la página de la tienda."""
        return self._partes_del_motivo()[0]

    @property
    def enlace(self):
        """La página de la tienda donde ocurrió la incidencia, si quedó anotada en el motivo."""
        return self._partes_del_motivo()[1]


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
    category = models.CharField(
        "categoría en la tienda", max_length=255, blank=True
    )
    image_url = models.URLField("imagen", max_length=1000, blank=True)
    list_price = models.PositiveIntegerField(
        "precio de lista", null=True, blank=True
    )
    final_price = models.PositiveIntegerField(
        "precio final", null=True, blank=True
    )
    is_available = models.BooleanField("disponible", default=True)
    barcodes = models.JSONField("códigos de barras", default=list, blank=True)
    status = models.CharField(
        "estado",
        max_length=20,
        choices=Status.choices,
        default=Status.NO_MATCH,
    )
    # El gtin de la variante sugerida (product_variants.gtin, la misma llave que usa prices).
    # No es una llave foránea para no depender de las migraciones de products.
    suggested_gtin = models.CharField(
        "variante del catálogo (código de barras)", max_length=14, blank=True
    )
    score = models.PositiveSmallIntegerField("puntaje", null=True, blank=True)
    match_reason = models.CharField(
        "por qué coincide", max_length=255, blank=True
    )
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
        return (
            ProductVariants.objects.select_related("product__brand")
            .filter(gtin=self.suggested_gtin)
            .first()
        )


class ManualRun(models.Model):
    """Una obtención de datos que el administrador pidió a mano para un comercio
    (issue «Ejecución manual de la obtención de datos»).

    Corre actualizar_precios --tienda <comercio> en el servidor de PricePeek o en GitHub Actions
    (el mismo workflow de cada hora), sin esperar a la próxima actualización programada.
    """

    class Runner(models.TextChoices):
        SERVER = "server", "Servidor de PricePeek"
        GITHUB = "github", "GitHub Actions"

    class Status(models.TextChoices):
        PENDING = "pending", "En cola"
        RUNNING = "running", "En curso"
        FINISHED = "finished", "Terminada"
        FAILED = "failed", "Falló"
        INTERRUPTED = "interrupted", "Interrumpida"

    ACTIVE = (Status.PENDING, Status.RUNNING)
    SUMMARY_MAX_LENGTH = 255

    store_name = models.CharField("comercio", max_length=100)
    # La fila de stores (tabla de Supabase): no es una llave foránea, como en StoreProduct.
    store_id = models.BigIntegerField("id del comercio", null=True, blank=True)
    runner = models.CharField(
        "dónde corre", max_length=20, choices=Runner.choices
    )
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    minutes = models.PositiveSmallIntegerField(
        "minutos como máximo", default=20
    )
    all_prices = models.BooleanField("revisar todos los precios", default=True)
    dry_run = models.BooleanField("modo de prueba", default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="pedida por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField("pedida el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada el", auto_now=True)
    started_at = models.DateTimeField("empezó", null=True, blank=True)
    finished_at = models.DateTimeField("terminó", null=True, blank=True)
    summary = models.CharField(
        "resultado", max_length=SUMMARY_MAX_LENGTH, blank=True
    )
    output = models.TextField("salida del comando", blank=True)
    github_run_id = models.BigIntegerField(
        "corrida de GitHub", null=True, blank=True
    )
    github_url = models.URLField("enlace a GitHub", max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ejecución manual"
        verbose_name_plural = "ejecuciones manuales"

    def __str__(self):
        return f"{self.store_name} en {self.get_runner_display()} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE
