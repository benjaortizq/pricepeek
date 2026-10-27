from django import forms
from django.contrib.auth.forms import UserCreationForm

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