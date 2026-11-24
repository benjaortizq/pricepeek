"""Formularios del portal de empresas."""

import json
from decimal import Decimal
from urllib.parse import urlparse

from django import forms

from core.translations import translate_text_lazy
from products.barcodes import validar_codigo_barras
from products.models import Brands, Categories, ProductVariants

PRECIO_ENTEROS_MINIMO = -(2**31)
PRECIO_ENTEROS_MAXIMO = 2**31 - 1


def _rechazar_constante_json(valor):
    raise ValueError(f"Constante JSON no finita: {valor}")


def analizar_atributos_json(texto):
    """Analiza un objeto JSON y rechaza constantes no finitas."""
    if not texto:
        return None
    try:
        atributos = json.loads(texto, parse_constant=_rechazar_constante_json)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("El JSON no es válido.") from error
    if not isinstance(atributos, dict):
        raise ValueError("El JSON debe contener un objeto.")
    return atributos


def normalizar_gtin(codigo):
    """Usa la misma convención del catálogo: 13 dígitos si empieza con cero."""
    gtin = str(codigo).strip().zfill(14)
    return gtin[1:] if gtin.startswith("0") else gtin


def _url_http_valida(url):
    if not url:
        return True
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    return partes.scheme in {"http", "https"} and bool(partes.netloc)


class IdentificadorModelChoiceField(forms.ModelChoiceField):
    """Evita consultar la base con identificadores fuera del rango bigint."""

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            if isinstance(value, self.queryset.model):
                valor_identificador = value.pk
            else:
                valor_identificador = value
            identificador = int(valor_identificador)
        except (TypeError, ValueError) as error:
            raise forms.ValidationError(
                translate_text_lazy("Seleccione una opción válida.")
            ) from error
        if identificador <= 0 or identificador > 2**63 - 1:
            raise forms.ValidationError(
                translate_text_lazy("Seleccione una opción válida.")
            )
        return super().to_python(value)


class PrecioEmpresaForm(forms.Form):
    """Edición de la fila de precio que pertenece a la tienda."""

    price = forms.IntegerField(
        required=False,
        min_value=PRECIO_ENTEROS_MINIMO,
        max_value=PRECIO_ENTEROS_MAXIMO,
        label=translate_text_lazy("Precio base"),
        help_text=translate_text_lazy(
            "Deje el precio vacío para quitarlo y marcar el producto como no disponible."
        ),
    )
    discount = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        decimal_places=2,
        label=translate_text_lazy("Descuento"),
        help_text=translate_text_lazy(
            "Use un decimal entre 0 y 1. Por ejemplo, 0.15 representa un 15 %. Si queda vacío, se guardará 0."
        ),
    )
    is_available = forms.BooleanField(
        required=False,
        initial=True,
        label=translate_text_lazy("Disponible"),
    )
    product_web_url = forms.CharField(
        required=False,
        max_length=2000,
        label=translate_text_lazy("Enlace del producto"),
        help_text=translate_text_lazy("Use un enlace que comience con http:// o https://."),
    )

    def clean_discount(self):
        descuento = self.cleaned_data.get("discount")
        return Decimal("0.00") if descuento in (None, "") else descuento

    def clean_product_web_url(self):
        url = self.cleaned_data.get("product_web_url", "").strip()
        if url and not _url_http_valida(url):
            raise forms.ValidationError(
                translate_text_lazy("El enlace debe comenzar con http:// o https://.")
            )
        return url

    def clean(self):
        datos = super().clean()
        if self._errors:
            return datos

        precio = datos.get("price")
        if precio is not None and precio < 0:
            datos["price"] = None
            datos["precio_invalido"] = True
            self.precio_invalido = True
            datos["is_available"] = False
        elif precio is None:
            datos["precio_invalido"] = True
            self.precio_invalido = True
            datos["is_available"] = False
        return datos


class ProductoEmpresaForm(forms.Form):
    """Alta de un precio para un GTIN existente o completamente nuevo."""

    gtin = forms.CharField(
        max_length=14,
        label=translate_text_lazy("Código de barras (GTIN)"),
        help_text=translate_text_lazy(
            "Puede ingresar un UPC/EAN de 8, 12, 13 o 14 dígitos."
        ),
    )
    product_name = forms.CharField(
        required=False,
        max_length=255,
        label=translate_text_lazy("Nombre del producto"),
        help_text=translate_text_lazy("Obligatorio cuando el GTIN es nuevo."),
    )
    variant_name = forms.CharField(
        required=False,
        max_length=255,
        label=translate_text_lazy("Nombre de la variante"),
        help_text=translate_text_lazy("Obligatorio cuando el GTIN es nuevo."),
    )
    brand = IdentificadorModelChoiceField(
        required=False,
        queryset=Brands.objects.order_by("name"),
        error_messages={
            "invalid_choice": translate_text_lazy("Seleccione una opción válida.")
        },
        label=translate_text_lazy("Marca"),
        help_text=translate_text_lazy("Obligatoria cuando el GTIN es nuevo."),
    )
    category = IdentificadorModelChoiceField(
        required=False,
        queryset=Categories.objects.order_by("name"),
        error_messages={
            "invalid_choice": translate_text_lazy("Seleccione una opción válida.")
        },
        label=translate_text_lazy("Categoría"),
        help_text=translate_text_lazy("Obligatoria cuando el GTIN es nuevo."),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=translate_text_lazy("Descripción"),
        help_text=translate_text_lazy("Se usa únicamente cuando el GTIN es nuevo."),
    )
    attributes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=translate_text_lazy("Características (JSON)"),
        help_text=translate_text_lazy(
            "Debe ser un objeto JSON. Se usa únicamente cuando el GTIN es nuevo."
        ),
    )
    price = forms.IntegerField(
        required=False,
        min_value=PRECIO_ENTEROS_MINIMO,
        max_value=PRECIO_ENTEROS_MAXIMO,
        label=translate_text_lazy("Precio base"),
    )
    discount = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("1"),
        decimal_places=2,
        label=translate_text_lazy("Descuento"),
        help_text=translate_text_lazy(
            "Use un decimal entre 0 y 1. Si queda vacío, se guardará 0."
        ),
    )
    is_available = forms.BooleanField(
        required=False,
        initial=True,
        label=translate_text_lazy("Disponible"),
    )
    product_web_url = forms.CharField(
        required=False,
        max_length=2000,
        label=translate_text_lazy("Enlace del producto"),
    )

    def clean_gtin(self):
        codigo = self.cleaned_data.get("gtin", "").strip()
        if codigo:
            # Algunos GTIN heredados ya existen en el catálogo aunque no
            # superen la validación actual del dígito verificador. Para ellos
            # se respeta el registro existente y solo se crea el precio.
            candidatos = dict.fromkeys((codigo, normalizar_gtin(codigo)))
            for candidato in candidatos:
                if ProductVariants.objects.filter(gtin=candidato).exists():
                    return candidato

        resultado = validar_codigo_barras(codigo)
        if not resultado:
            self.add_error("gtin", translate_text_lazy(resultado.motivo))
            return codigo
        return normalizar_gtin(resultado.codigo)

    def clean_discount(self):
        descuento = self.cleaned_data.get("discount")
        return Decimal("0.00") if descuento in (None, "") else descuento

    def clean_attributes(self):
        texto = self.cleaned_data.get("attributes", "").strip()
        try:
            return analizar_atributos_json(texto)
        except ValueError as error:
            raise forms.ValidationError(
                translate_text_lazy("Las características deben ser un objeto JSON válido.")
            ) from error

    def clean_product_web_url(self):
        url = self.cleaned_data.get("product_web_url", "").strip()
        if url and not _url_http_valida(url):
            raise forms.ValidationError(
                translate_text_lazy("El enlace debe comenzar con http:// o https://.")
            )
        return url

    def clean(self):
        datos = super().clean()
        gtin = datos.get("gtin")
        variante = None
        if gtin:
            variante = ProductVariants.objects.filter(gtin=gtin).first()
        datos["variante_existente"] = variante

        if variante is None:
            for campo in ("product_name", "variant_name", "brand", "category"):
                if not datos.get(campo):
                    self.add_error(
                        campo,
                        translate_text_lazy(
                            "Este campo es obligatorio cuando el GTIN no existe en el catálogo."
                        ),
                    )

        precio = datos.get("price")
        if precio is not None and precio < 0:
            datos["price"] = None
            datos["precio_invalido"] = True
            self.precio_invalido = True
            datos["is_available"] = False
        elif precio is None:
            datos["precio_invalido"] = True
            self.precio_invalido = True
            datos["is_available"] = False
        return datos


class CargarCSVForm(forms.Form):
    archivo = forms.FileField(
        label=translate_text_lazy("Archivo CSV"),
        help_text=translate_text_lazy(
            "El archivo no se guarda; cada fila se valida e importa por separado."
        ),
    )
