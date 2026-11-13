from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm, UserCreationForm
from django.utils import timezone

from .models import User


class RegistroClienteForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre", max_length=150)
    email = forms.EmailField(label="Correo electrónico")

    class Meta:
        model = User
        fields = ("first_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CLIENT
        if commit:
            user.save()
        return user


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
        label="Contraseña actual",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("La contraseña ingresada no es correcta.")
        return password


class CambioContrasenaForm(PasswordChangeForm):
    """Contraseña actual + nueva contraseña; el cambio se aplica al confirmar el código."""


class CodigoCambioContrasenaForm(forms.Form):
    codigo = forms.CharField(
        label="Código de verificación",
        max_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )


class EditarNombreForm(forms.ModelForm):
    first_name = forms.CharField(label="Nombre", max_length=150)

    class Meta:
        model = User
        fields = ("first_name",)


def correo_en_uso(email, user):
    """True si el correo ya pertenece a otra cuenta (sin importar mayúsculas)."""
    return User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists()


class NuevoCorreoForm(forms.Form):
    """Paso 1 del cambio de correo: verificar que el correo nuevo esté libre."""

    email = forms.EmailField(label="Correo electrónico nuevo")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if email == self.user.email.lower():
            raise forms.ValidationError("Ese ya es el correo de su cuenta.")
        if correo_en_uso(email, self.user):
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email


class ConfirmarCorreoForm(forms.Form):
    """Paso 2 del cambio de correo: confirmar con la contraseña actual."""

    password = forms.CharField(
        label="Contraseña actual",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("La contraseña ingresada no es correcta.")
        return password
