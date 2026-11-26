"""Formularios y validaciones de entrada de la aplicación accounts."""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.utils import timezone

from core.translations import translate_text_lazy
from products.models import PartnerStore, Stores

from .models import User


class IniciarSesionForm(AuthenticationForm):
    """Inicio de sesión que avisa al cliente cuando su cuenta fue suspendida (RF-42)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "inactive": (
            "Su cuenta está suspendida por incumplir las políticas de uso de PricePeek. "
            "Si cree que se trata de un error, comuníquese con el equipo de PricePeek."
        ),
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError as error:
            # Django rechaza las cuentas inactivas como si la contraseña fuera incorrecta.
            if error.code == "invalid_login" and self.es_cuenta_suspendida():
                raise forms.ValidationError(
                    self.error_messages["inactive"], code="inactive"
                ) from None
            raise

    def es_cuenta_suspendida(self):
        # Solo se revela la suspensión a quien conoce la contraseña de la cuenta.
        usuario = User.objects.filter(
            email=self.cleaned_data.get("username"), is_active=False
        ).first()
        return usuario is not None and usuario.check_password(
            self.cleaned_data.get("password")
        )


class SuspenderClienteForm(forms.Form):
    motivo = forms.CharField(
        label=translate_text_lazy("Motivo de la suspensión"),
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Indique el motivo de la suspensión."},
    )


class RegistroClienteForm(UserCreationForm):
    first_name = forms.CharField(
        label=translate_text_lazy("Nombre"), max_length=150
    )
    email = forms.EmailField(label=translate_text_lazy("Correo electrónico"))
    accept_privacy = forms.BooleanField(
        required=True,
        label="",
        error_messages={
            "required": "Debe autorizar el tratamiento de sus datos para crear una cuenta."
        },
    )

    class Meta:
        model = User
        fields = ("first_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Ya existe una cuenta con este correo electrónico."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CLIENT
        if commit:
            user.save()
        return user


class ConsentimientoPrivacidadForm(forms.Form):
    accept_privacy = forms.BooleanField(
        required=True,
        label="",
        error_messages={
            "required": "Debe autorizar el tratamiento de sus datos para continuar."
        },
    )


class RestablecerContrasenaForm(SetPasswordForm):
    """Nueva contraseña tras el enlace de recuperación (RF-04)."""

    def save(self, commit=True):
        user = super().save(commit=False)
        user.last_password_change = timezone.now()
        if commit:
            user.save()
        return user


class EliminarCuentaForm(forms.Form):
    """Confirmación con la contraseña actual antes de eliminar la cuenta (RF-05)."""

    password = forms.CharField(
        label=translate_text_lazy("Contraseña actual"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(
                "La contraseña ingresada no es correcta."
            )
        return password


class CambioContrasenaForm(PasswordChangeForm):
    """Contraseña actual + nueva contraseña; el cambio se aplica al confirmar el código."""


class CodigoCambioContrasenaForm(forms.Form):
    codigo = forms.CharField(
        label=translate_text_lazy("Código de verificación"),
        max_length=6,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}
        ),
    )


class EditarNombreForm(forms.ModelForm):
    first_name = forms.CharField(
        label=translate_text_lazy("Nombre"), max_length=150
    )

    class Meta:
        model = User
        fields = ("first_name",)


class AlertasPrecioForm(forms.ModelForm):
    """Interruptor de las alertas de baja de precio (RF-24)."""

    active_alerts = forms.BooleanField(
        label=translate_text_lazy(
            "Recibir alertas de baja de precio por correo"
        ),
        required=False,
    )

    class Meta:
        model = User
        fields = ("active_alerts",)


def correo_en_uso(email, user):
    """True si el correo ya pertenece a otra cuenta (sin importar mayúsculas)."""
    return (
        User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists()
    )


class NuevoCorreoForm(forms.Form):
    """Paso 1 del cambio de correo: verificar que el correo nuevo esté libre."""

    email = forms.EmailField(
        label=translate_text_lazy("Correo electrónico nuevo")
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if email == self.user.email.lower():
            raise forms.ValidationError("Ese ya es el correo de su cuenta.")
        if correo_en_uso(email, self.user):
            raise forms.ValidationError(
                "Ya existe una cuenta con este correo electrónico."
            )
        return email


class ConfirmarCorreoForm(forms.Form):
    """Paso 2 del cambio de correo: confirmar con la contraseña actual."""

    password = forms.CharField(
        label=translate_text_lazy("Contraseña actual"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(
                "La contraseña ingresada no es correcta."
            )
        return password


# --- Comercios asociados (panel de administración, accounts/vistas_comercios.py) ---

# Las clases de los campos de frontend/html/business-producto-formulario.html.
CLASE_CAMPO = (
    "w-full bg-surface-container-low text-body-md font-body-md text-on-surface px-4 py-2.5 rounded-full "
    "border border-outline-variant focus:outline-none focus:ring-0 focus:border-on-surface "
    "focus:bg-surface-container-lowest transition-all"
)


class DatosDelComercioForm(forms.Form):
    """El nombre, la descripción y cómo se obtienen los datos de un comercio asociado."""

    name = forms.CharField(
        label=translate_text_lazy("Nombre del comercio"),
        max_length=255,
        widget=forms.TextInput(attrs={"class": CLASE_CAMPO}),
    )
    description = forms.CharField(
        label=translate_text_lazy("Descripción"),
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"class": CLASE_CAMPO.replace("rounded-full", "rounded-2xl").replace("py-2.5", "py-3"), "rows": 3}),
    )
    data_source = forms.ChoiceField(
        label=translate_text_lazy("¿Cómo se obtienen sus datos?"),
        choices=PartnerStore.DataSource.choices,
        widget=forms.RadioSelect,
        error_messages={
            "required": translate_text_lazy("Elija cómo se obtienen los datos del comercio."),
            "invalid_choice": translate_text_lazy("Elija cómo se obtienen los datos del comercio."),
        },
    )

    def __init__(self, *args, tienda=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tienda = tienda

    def clean_name(self):
        nombre = " ".join(self.cleaned_data["name"].split())
        otras = Stores.objects.exclude(pk=self.tienda.pk) if self.tienda else Stores.objects.all()
        if any(" ".join(otra.name.split()).casefold() == nombre.casefold() for otra in otras.only("name")):
            raise forms.ValidationError(translate_text_lazy("Ya hay un comercio con ese nombre."))
        return nombre

    def clean_description(self):
        return self.cleaned_data["description"].strip()


class CuentaDeEmpresaForm(forms.Form):
    """La cuenta con la que el comercio entra al portal de empresas."""

    email = forms.EmailField(
        label=translate_text_lazy("Correo de la cuenta"),
        widget=forms.EmailInput(attrs={"class": CLASE_CAMPO, "autocomplete": "off"}),
    )
    first_name = forms.CharField(
        label=translate_text_lazy("Nombre de la persona encargada"),
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={"class": CLASE_CAMPO}),
    )
    last_name = forms.CharField(
        label=translate_text_lazy("Apellidos"),
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={"class": CLASE_CAMPO}),
    )

    def clean_email(self):
        correo = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=correo).exists():
            raise forms.ValidationError(translate_text_lazy("Ya existe una cuenta con este correo electrónico."))
        return correo

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()


class RegistrarComercioForm(DatosDelComercioForm, CuentaDeEmpresaForm):
    """El registro de un comercio asociado: sus datos, su cuenta de empresa y si queda activo."""

    is_active = forms.BooleanField(
        label=translate_text_lazy("Activarlo de una vez"),
        required=False,
        initial=True,
    )
