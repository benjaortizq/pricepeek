from django.db import models

# Las tablas ya existen en Supabase, por eso los modelos son managed = False.


class Brand(models.Model):
    name = models.CharField(max_length=255)
    website_url = models.TextField(blank=True, null=True)
    slug = models.CharField(max_length=255, unique=True)
    logo_url = models.TextField()
    brand_color = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "brands"

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    brand = models.ForeignKey(Brand, models.DO_NOTHING, db_column="brand", related_name="products")
    category = models.ForeignKey(
        Category, models.DO_NOTHING, db_column="category", related_name="products"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "products"

    def __str__(self):
        return self.name

    def main_image(self):
        # La imagen marcada como principal; si no hay, la primera que exista.
        return self.images.order_by("-is_main", "id").first()


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, models.DO_NOTHING, related_name="variants")
    gtin = models.CharField("código de barras", max_length=14, unique=True)
    attributes = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "product_variants"

    def __str__(self):
        return self.gtin


class ProductImage(models.Model):
    product = models.ForeignKey(Product, models.DO_NOTHING, related_name="images")
    variant = models.ForeignKey(ProductVariant, models.DO_NOTHING, related_name="images")
    image_url = models.TextField()
    is_main = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "product_images"
