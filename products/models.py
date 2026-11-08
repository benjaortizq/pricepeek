# This is an auto-generated Django model module.
from django.db import models


class Brands(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    website_url = models.TextField(blank=True, null=True)
    slug = models.CharField(unique=True, max_length=255)
    logo_url = models.TextField()
    brand_color = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'brands'


class Categories(models.Model):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'categories'


class ProductImages(models.Model):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey('Products', models.DO_NOTHING)
    variant = models.ForeignKey('ProductVariants', models.DO_NOTHING)
    image_url = models.TextField()
    is_main = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'product_images'


class ProductVariants(models.Model):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey('Products', models.DO_NOTHING)
    gtin = models.CharField(unique=True, max_length=255)
    attributes = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'product_variants'


class Products(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    id = models.BigIntegerField(primary_key=True)
    brand = models.ForeignKey(Brands, models.DO_NOTHING, db_column='brand')
    category = models.ForeignKey(Categories, models.DO_NOTHING, db_column='category')
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'products'
        db_table_comment = 'Product'


# =========== Tablas para los precios de las empresas ===========
class PricesWalmart(models.Model):
    id = models.BigAutoField(primary_key=True)
    gtin = models.OneToOneField('ProductVariants', models.DO_NOTHING, db_column='gtin')
    price = models.SmallIntegerField()
    is_available = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'prices_walmart'