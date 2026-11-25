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

    class Meta:
        managed = False
        db_table = 'brands'


class Categories(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'categories'


class Currencies(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    symbol = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'currencies'


class Prices(models.Model):
    id = models.BigAutoField(primary_key=True)
    id_store = models.ForeignKey('Stores', models.DO_NOTHING, db_column='id_store')
    gtin = models.ForeignKey('ProductVariants', models.DO_NOTHING, db_column='gtin', to_field='gtin')
    price = models.IntegerField(blank=True, null=True)
    is_available = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    currency = models.ForeignKey(Currencies, models.DO_NOTHING, db_column='currency')
    product_web_url = models.TextField()
    discount = models.DecimalField(max_digits=3, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'prices'
        unique_together = (('id_store', 'gtin'),)


class ProductImages(models.Model):
    id = models.BigAutoField(primary_key=True)
    variant = models.ForeignKey('ProductVariants', models.DO_NOTHING)
    image_url = models.TextField()
    is_main = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    number_image = models.SmallIntegerField()

    class Meta:
        managed = False
        db_table = 'product_images'


class ProductVariants(models.Model):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey('Products', models.DO_NOTHING)
    gtin = models.CharField(unique=True)
    attributes = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    name = models.CharField()

    class Meta:
        managed = False
        db_table = 'product_variants'


class Products(models.Model):
    name = models.CharField()
    description = models.TextField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    brand = models.ForeignKey(Brands, models.DO_NOTHING, db_column='brand')
    category = models.ForeignKey(Categories, models.DO_NOTHING, db_column='category')
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'products'
        db_table_comment = 'Product'

class Stores(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    description = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'stores'


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
    hour = models.DateTimeField()  # la hora de la visita, sin minutos ni segundos

    class Meta:
        db_table = "product_views"
        constraints = [
            models.UniqueConstraint(
                fields=["product_id", "visitor", "hour"], name="una_visita_por_visitante_y_hora"
            ),
        ]
        indexes = [models.Index(fields=["product_id", "hour"], name="product_views_por_producto")]
