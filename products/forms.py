"""Formularios del catálogo de productos."""

from django import forms

from core.translations import translate_text_lazy

from .edicion import EXTENSION_POR_FORMATO
from .models import Categories

TAMANO_MAXIMO_DE_IMAGEN = 5 * 1024 * 1024  # 5 MB

# Las clases de los campos de frontend/html/business-producto-formulario.html.
CLASE_CAMPO = (
    "w-full bg-surface-container-low text-body-md font-body-md text-on-surface px-4 py-2.5 rounded-full "
    "border border-outline-variant focus:outline-none focus:ring-0 focus:border-on-surface "
    "focus:bg-surface-container-lowest transition-all"
)


class EditarProductoForm(forms.Form):
    """Los datos generales de un producto, que comparten todas las tiendas que lo ofrecen."""

    name = forms.CharField(
        label=translate_text_lazy("Nombre del producto"),
        max_length=255,
        widget=forms.TextInput(attrs={"class": CLASE_CAMPO}),
    )
    category = forms.ModelChoiceField(
        label=translate_text_lazy("Categoría"),
        queryset=Categories.objects.order_by("name"),
        empty_label=None,
        error_messages={"invalid_choice": translate_text_lazy("Seleccione una opción válida.")},
        widget=forms.Select(attrs={"class": f"{CLASE_CAMPO} appearance-none cursor-pointer pr-10"}),
    )
    brand = forms.CharField(
        label=translate_text_lazy("Marca"),
        max_length=255,
        help_text=translate_text_lazy("Escriba una de las marcas del catálogo; si no existe, se crea."),
        widget=forms.TextInput(attrs={"class": CLASE_CAMPO, "list": "marcas-del-catalogo", "autocomplete": "off"}),
    )
    description = forms.CharField(
        label=translate_text_lazy("Descripción"),
        required=False,
        widget=forms.Textarea(
            attrs={"class": CLASE_CAMPO.replace("rounded-full", "rounded-2xl").replace("py-2.5", "py-3"), "rows": 6}
        ),
    )
    image = forms.ImageField(
        label=translate_text_lazy("Subir una imagen"),
        required=False,
        error_messages={
            "invalid_image": translate_text_lazy("El archivo no es una imagen o está dañado."),
        },
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp,image/gif"}),
    )
    image_url = forms.URLField(
        label=translate_text_lazy("O pegue el enlace de la imagen"),
        required=False,
        max_length=1000,
        assume_scheme="https",
        error_messages={"invalid": translate_text_lazy("Escriba un enlace válido, como https://…")},
        widget=forms.URLInput(attrs={"class": CLASE_CAMPO, "placeholder": "https://"}),
    )

    def __init__(self, *args, producto, tiene_presentaciones=True, **kwargs):
        kwargs.setdefault(
            "initial",
            {
                "name": producto.name,
                "category": producto.category_id,
                "brand": producto.brand.name,
                "description": producto.description or "",
            },
        )
        super().__init__(*args, **kwargs)
        self.tiene_presentaciones = tiene_presentaciones

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_brand(self):
        return self.cleaned_data["brand"].strip()

    def clean_image(self):
        imagen = self.cleaned_data.get("image")
        if not imagen:
            return None
        if imagen.size > TAMANO_MAXIMO_DE_IMAGEN:
            raise forms.ValidationError(translate_text_lazy("La imagen pesa más de 5 MB."))
        if imagen.image.format not in EXTENSION_POR_FORMATO:
            raise forms.ValidationError(translate_text_lazy("La imagen tiene que ser JPG, PNG, WEBP o GIF."))
        return imagen

    def clean(self):
        datos = super().clean()
        if datos.get("image") and datos.get("image_url"):
            raise forms.ValidationError(translate_text_lazy("Suba una imagen o pegue un enlace, no los dos."))
        if (datos.get("image") or datos.get("image_url")) and not self.tiene_presentaciones:
            raise forms.ValidationError(
                translate_text_lazy(
                    "Este producto no tiene presentaciones con código de barras: la imagen se guarda en cada presentación."
                )
            )
        return datos
