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
    review_photo = None


class ReviewPhoto(models.Model):
    review_id = models.PositiveBigIntegerField(unique=True)
    image = models.ImageField(upload_to="reviews/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_photos"