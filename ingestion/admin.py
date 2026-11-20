from django import forms
from django.contrib import admin, messages
from django.db.models import OuterRef, Subquery
from django.utils.html import format_html

from products.models import ProductVariants
from products.templatetags.precios import miles

from .models import Incident, StoreProduct
from .productos_tienda import NoSePuedeVincular, candidatas_del_catalogo, confirmar, rechazar, sugerir


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "store_name", "product_name", "gtin")
    list_filter = ("kind", "store_name")
    search_fields = ("product_name", "gtin", "store_name")


class VarianteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, variante):
        return f"{variante.name} · {variante.product.brand.name} · {variante.gtin}"


class StoreProductForm(forms.ModelForm):
    variante = VarianteChoiceField(
        label="Variante del catálogo",
        queryset=ProductVariants.objects.select_related("product__brand").order_by("name"),
        to_field_name="gtin",
        required=False,
        help_text="Si la sugerencia no es correcta, elija aquí la variante y guarde; después use «Confirmar».",
    )

    class Meta:
        model = StoreProduct
        fields = ["variante"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.suggested_gtin:
            self.fields["variante"].initial = self.instance.suggested_gtin


@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    form = StoreProductForm
    list_display = ("name", "store_name", "precio", "is_available", "status", "variante_sugerida", "score")
    list_filter = ("store_name", "status", "is_available")
    search_fields = ("name", "sku", "product_model", "brand", "suggested_gtin")
    actions = ["confirmar_seleccionados", "rechazar_seleccionados", "volver_a_sugerir"]
    readonly_fields = (
        "enlace", "store_name", "sku", "name", "brand", "product_model", "color", "category", "imagen",
        "list_price", "final_price", "is_available", "barcodes", "status", "suggested_gtin", "score",
        "match_reason", "created_at", "updated_at",
    )
    fieldsets = (
        ("Coincidencia", {"fields": ("status", "variante", "suggested_gtin", "score", "match_reason")}),
        (
            "Como lo publica la tienda",
            {
                "fields": (
                    "enlace", "store_name", "sku", "name", "brand", "product_model", "color", "category", "imagen",
                    "list_price", "final_price", "is_available", "barcodes", "created_at", "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False  # los crea obtener_productos

    def get_queryset(self, request):
        nombre = ProductVariants.objects.filter(gtin=OuterRef("suggested_gtin")).values("name")[:1]
        return super().get_queryset(request).annotate(nombre_variante=Subquery(nombre))

    @admin.display(description="precio final", ordering="final_price")
    def precio(self, producto):
        return f"₡{miles(producto.final_price)}" if producto.final_price is not None else "—"

    @admin.display(description="variante del catálogo")
    def variante_sugerida(self, producto):
        return getattr(producto, "nombre_variante", None) or "—"

    @admin.display(description="enlace")
    def enlace(self, producto):
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', producto.url, producto.url)

    @admin.display(description="imagen")
    def imagen(self, producto):
        if not producto.image_url:
            return "—"
        return format_html('<img src="{}" alt="" style="max-height:160px">', producto.image_url)

    def save_model(self, request, producto, form, change):
        variante = form.cleaned_data.get("variante")
        gtin = variante.gtin if variante else ""
        if gtin != producto.suggested_gtin:
            producto.suggested_gtin = gtin
            producto.score = None
            producto.match_reason = "elegida a mano" if gtin else ""
            if producto.status != StoreProduct.Status.CONFIRMED:
                producto.status = StoreProduct.Status.SUGGESTED if gtin else StoreProduct.Status.NO_MATCH
        super().save_model(request, producto, form, change)

    @admin.action(description="Confirmar: crear su precio en el catálogo")
    def confirmar_seleccionados(self, request, queryset):
        confirmados = 0
        for producto in queryset:
            try:
                confirmar(producto)
                confirmados += 1
            except NoSePuedeVincular as error:
                self.message_user(request, f"{producto.name}: {error}", messages.WARNING)
        if confirmados:
            self.message_user(request, f"{confirmados} productos vinculados al catálogo.", messages.SUCCESS)

    @admin.action(description="Rechazar la coincidencia")
    def rechazar_seleccionados(self, request, queryset):
        for producto in queryset:
            rechazar(producto)
        self.message_user(request, f"{queryset.count()} coincidencias rechazadas.", messages.SUCCESS)

    @admin.action(description="Volver a buscar coincidencia")
    def volver_a_sugerir(self, request, queryset):
        candidatas = candidatas_del_catalogo()
        sugeridos = 0
        for producto in queryset.exclude(status=StoreProduct.Status.CONFIRMED):
            sugerir(producto, candidatas)
            producto.save()
            sugeridos += producto.status == StoreProduct.Status.SUGGESTED
        self.message_user(request, f"{sugeridos} productos con coincidencia sugerida.", messages.SUCCESS)
