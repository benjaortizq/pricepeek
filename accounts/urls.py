from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import IniciarSesionForm, RestablecerContrasenaForm

urlpatterns = [
    # Reemplaza el login de Django para avisar cuando la cuenta está suspendida.
    path("login/", auth_views.LoginView.as_view(authentication_form=IniciarSesionForm), name="login"),
    path("register/", views.registro, name="register"),
    path(
        "consentimiento-privacidad/",
        views.consentimiento_privacidad,
        name="consentimiento_privacidad",
    ),
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
    path("perfil/", views.editar_perfil, name="editar_perfil"),
    path("mis-datos/", views.descargar_datos_personales, name="descargar_datos_personales"),
    path("perfil/verificar-correo/", views.verificar_correo, name="verificar_correo"),
    path("eliminar-cuenta/", views.eliminar_cuenta, name="eliminar_cuenta"),
    path("panel/", views.panel, name="panel"),
    path("cliente/", views.inicio_cliente, name="inicio_cliente"),
    path("empresa/", views.inicio_empresa, name="inicio_empresa"),
    path("administrador/", views.inicio_administrador, name="inicio_administrador"),
    path("administrador/clientes/", views.clientes, name="clientes"),
    path("administrador/clientes/<int:pk>/", views.detalle_cliente, name="detalle_cliente"),
    path("administrador/clientes/<int:pk>/suspender/", views.suspender_cliente, name="suspender_cliente"),
    path("administrador/clientes/<int:pk>/reactivar/", views.reactivar_cliente, name="reactivar_cliente"),
]
