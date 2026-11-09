from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import RestablecerContrasenaForm

urlpatterns = [
    path("register/", views.registro, name="register"),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            form_class=RestablecerContrasenaForm,
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    # Reemplaza la vista de Django para exigir el código enviado por correo.
    path("password_change/", views.cambiar_contrasena, name="password_change"),
    path(
        "password_change/confirmar/",
        views.confirmar_cambio_contrasena,
        name="password_change_confirm",
    ),
    path("eliminar-cuenta/", views.eliminar_cuenta, name="eliminar_cuenta"),
    path("panel/", views.panel, name="panel"),
    path("cliente/", views.inicio_cliente, name="inicio_cliente"),
    path("empresa/", views.inicio_empresa, name="inicio_empresa"),
    path("administrador/", views.inicio_administrador, name="inicio_administrador"),
]