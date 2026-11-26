"""Modelos de datos de la aplicación products."""

# This is an auto-generated Django model module.
from django.conf import settings
from django.db import models


class Brands(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    website_url = models.TextField(blank=True, null=True)
    slug = models.CharField(unique=True)
    logo_url = models.TextField(blank=True, null=True)
    brand_color = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = "brands"


class Categories(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return self.name

    class Meta:
        managed = False
        db_table = "categories"


class Currencies(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    symbol = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "currencies"


class PreciosVisibles(models.Manager):
    """Los precios que se le muestran al usuario final: sin los de comercios desactivados.

    Lo usan las pantallas y la API del sitio (Prices.visibles). Prices.objects los trae todos:
    lo siguen usando el portal de empresas (cada tienda ve los suyos aunque esté desactivada),
    la obtención de datos y el panel de administración.
    """

    def get_queryset(self):
        desactivados = PartnerStore.objects.filter(is_active=False).values(
            "store_id"
        )
        return super().get_queryset().exclude(id_store_id__in=desactivados)


class Prices(models.Model):
    objects = models.Manager()  # el primero es el de siempre: Django lo usa en las relaciones y el admin
    visibles = PreciosVisibles()

    id = models.BigAutoField(primary_key=True)
    id_store = models.ForeignKey(
        "Stores", models.DO_NOTHING, db_column="id_store"
    )
    gtin = models.ForeignKey(
        "ProductVariants", models.DO_NOTHING, db_column="gtin", to_field="gtin"
    )
    price = models.IntegerField(blank=True, null=True)
    is_available = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    currency = models.ForeignKey(
        Currencies, models.DO_NOTHING, db_column="currency"
    )
    product_web_url = models.TextField()
    discount = models.DecimalField(max_digits=3, decimal_places=2)

    class Meta:
        managed = False
        db_table = "prices"
        unique_together = (("id_store", "gtin"),)


class ProductImages(models.Model):
    id = models.BigAutoField(primary_key=True)
    variant = models.ForeignKey("ProductVariants", models.DO_NOTHING)
    image_url = models.TextField()
    is_main = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    number_image = models.SmallIntegerField()

    class Meta:
        managed = False
        db_table = "product_images"


class ProductVariants(models.Model):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey("Products", models.DO_NOTHING)
    gtin = models.CharField(unique=True)
    attributes = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    name = models.CharField()

    class Meta:
        managed = False
        db_table = "product_variants"


class Products(models.Model):
    name = models.CharField()
    description = models.TextField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(Brands, models.DO_NOTHING, db_column="brand")
    category = models.ForeignKey(
        Categories, models.DO_NOTHING, db_column="category"
    )
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "products"
        db_table_comment = "Product"


class Stores(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    description = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "stores"


class PartnerStore(models.Model):
    """Un comercio asociado, como lo administra PricePeek: cómo se obtienen sus datos y si está activo.

    stores es una tabla de Supabase (managed = False): lo que agrega PricePeek va en esta tabla
    aparte, una fila por comercio. Un comercio sin fila (los que ya existían) está activo y su
    mecanismo se deduce de si PricePeek sabe leer su página (ver products/comercios.py).
    """

    class DataSource(models.TextChoices):
        SCRAPING = "scraping", "Web scraping"
        PROVIDED = "comercio", "Datos provistos por el comercio"

    # Sin restricción en la base: stores no la maneja Django (como ProductView.product_id).
    store = models.OneToOneField(
        Stores,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        primary_key=True,
        related_name="asociado",
    )
    data_source = models.CharField(
        "obtención de datos", max_length=20, choices=DataSource.choices
    )
    is_active = models.BooleanField("activo", default=True)
    # Quién lo activó o desactivó por última vez, y cuándo.
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "partner_stores"

    def __str__(self):
        return self.store.name.strip()


class ProductView(models.Model):
    """Una visita al detalle de un producto, para saber cuáles son populares (products/popularidad.py).

    Se guarda una sola fila por visitante, producto y hora: recargar la página no suma.
    """

    id = models.BigAutoField(primary_key=True)
    # Products es una tabla de Supabase (managed = False), por eso no es una llave foránea.
    product_id = models.PositiveBigIntegerField()
    # «u<id>» si es un cliente con sesión iniciada o «s<clave de la sesión>» si es anónimo.
    visitor = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # si el cliente borra su cuenta, se borra lo que vio
        null=True,
        blank=True,
        related_name="product_views",
    )
    hour = (
        models.DateTimeField()
    )  # la hora de la visita, sin minutos ni segundos

    class Meta:
        db_table = "product_views"
        constraints = [
            models.UniqueConstraint(
                fields=["product_id", "visitor", "hour"],
                name="una_visita_por_visitante_y_hora",
            ),
        ]
        indexes = [
            models.Index(
                fields=["product_id", "hour"],
                name="product_views_por_producto",
            )
        ]
