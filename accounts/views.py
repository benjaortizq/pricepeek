import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import (
    CambioContrasenaForm,
    CodigoCambioContrasenaForm,
    ConfirmarCorreoForm,
    EditarNombreForm,
    EliminarCuentaForm,
    NuevoCorreoForm,
    RegistroClienteForm,
    correo_en_uso,
)
from .models import User

CAMBIO_PENDIENTE = "cambio_contrasena_pendiente"
CORREO_PENDIENTE = "cambio_correo_pendiente"


def registro(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Su cuenta fue creada. Ya puede iniciar sesión.")
            return redirect("login")
    else:
        form = RegistroClienteForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def panel(request):
    if request.user.role == User.Role.ENTERPRISE:
        return redirect("inicio_empresa")
    if request.user.role == User.Role.ADMIN:
        return redirect("inicio_administrador")
    return redirect("inicio_cliente")


@role_required(User.Role.CLIENT)
def inicio_cliente(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Inicio del cliente"})


@role_required(User.Role.ENTERPRISE)
def inicio_empresa(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Panel de empresa"})


@role_required(User.Role.ADMIN)
def inicio_administrador(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Panel de administración"})


@role_required(User.Role.CLIENT)
def eliminar_cuenta(request):
    if request.method == "POST":
        form = EliminarCuentaForm(request.user, request.POST)
        if form.is_valid():
            usuario = request.user
            logout(request)
            usuario.delete()
            messages.success(request, "Su cuenta y sus datos fueron eliminados.")
            return redirect("login")
    else:
        form = EliminarCuentaForm(request.user)
    return render(request, "accounts/eliminar_cuenta.html", {"form": form})


def enviar_codigo_cambio_contrasena(user, codigo):
    contexto = {"user": user, "codigo": codigo, "minutos": settings.PASSWORD_CHANGE_CODE_TIMEOUT // 60}
    asunto = render_to_string("registration/password_change_code_subject.txt", contexto)
    cuerpo = render_to_string("registration/password_change_code_email.html", contexto)
    send_mail("".join(asunto.splitlines()), cuerpo, None, [user.email])


@login_required
def cambiar_contrasena(request):
    if request.method == "POST":
        form = CambioContrasenaForm(request.user, request.POST)
        if form.is_valid():
            codigo = f"{secrets.randbelow(10**6):06d}"
            # La nueva contraseña se guarda ya hasheada hasta que se confirme el código.
            request.session[CAMBIO_PENDIENTE] = {
                "password": make_password(form.cleaned_data["new_password1"]),
                "codigo": make_password(codigo),
                "expira": timezone.now().timestamp() + settings.PASSWORD_CHANGE_CODE_TIMEOUT,
                "intentos": 0,
            }
            enviar_codigo_cambio_contrasena(request.user, codigo)
            return redirect("password_change_confirm")
    else:
        form = CambioContrasenaForm(request.user)
    return render(request, "accounts/cambiar_contrasena.html", {"form": form})


@login_required
def confirmar_cambio_contrasena(request):
    pendiente = request.session.get(CAMBIO_PENDIENTE)
    if pendiente is None:
        return redirect("password_change")

    if request.method == "POST":
        form = CodigoCambioContrasenaForm(request.POST)
        if form.is_valid():
            if timezone.now().timestamp() > pendiente["expira"]:
                del request.session[CAMBIO_PENDIENTE]
                messages.error(request, "El código venció. Vuelva a solicitar el cambio de contraseña.")
                return redirect("password_change")
            if not check_password(form.cleaned_data["codigo"], pendiente["codigo"]):
                pendiente["intentos"] += 1
                if pendiente["intentos"] >= settings.PASSWORD_CHANGE_CODE_MAX_ATTEMPTS:
                    del request.session[CAMBIO_PENDIENTE]
                    messages.error(
                        request, "Demasiados intentos fallidos. Vuelva a solicitar el cambio de contraseña."
                    )
                    return redirect("password_change")
                request.session[CAMBIO_PENDIENTE] = pendiente
                form.add_error("codigo", "El código ingresado no es correcto.")
            else:
                usuario = request.user
                usuario.password = pendiente["password"]
                usuario.last_password_change = timezone.now()
                usuario.save(update_fields=["password", "last_password_change"])
                update_session_auth_hash(request, usuario)
                del request.session[CAMBIO_PENDIENTE]
                messages.success(request, "Su contraseña fue cambiada.")
                return redirect("panel")
    else:
        form = CodigoCambioContrasenaForm()
    return render(
        request,
        "accounts/confirmar_cambio_contrasena.html",
        {"form": form, "minutos": settings.PASSWORD_CHANGE_CODE_TIMEOUT // 60},
    )


def mostrar_perfil(request, form_nombre=None, form_correo=None, form_confirmar=None):
    correo_pendiente = request.session.get(CORREO_PENDIENTE)
    if correo_pendiente:
        form_confirmar = form_confirmar or ConfirmarCorreoForm(request.user, prefix="confirmar")
    return render(
        request,
        "accounts/editar_perfil.html",
        {
            "form_nombre": form_nombre or EditarNombreForm(instance=request.user, prefix="nombre"),
            "form_correo": form_correo or NuevoCorreoForm(request.user, prefix="correo"),
            "form_confirmar": form_confirmar,
            "correo_pendiente": correo_pendiente,
        },
    )


@login_required
def editar_perfil(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "nombre":
            form_nombre = EditarNombreForm(request.POST, instance=request.user, prefix="nombre")
            if form_nombre.is_valid():
                form_nombre.save()
                messages.success(request, "Su nombre fue actualizado.")
                return redirect("editar_perfil")
            return mostrar_perfil(request, form_nombre=form_nombre)
        if accion == "cancelar_correo":
            request.session.pop(CORREO_PENDIENTE, None)
            return redirect("editar_perfil")
        if accion == "confirmar_correo" and request.session.get(CORREO_PENDIENTE):
            form_confirmar = ConfirmarCorreoForm(request.user, request.POST, prefix="confirmar")
            if not form_confirmar.is_valid():
                return mostrar_perfil(request, form_confirmar=form_confirmar)
            email = request.session.pop(CORREO_PENDIENTE)
            # Se vuelve a revisar: otra cuenta pudo tomar el correo entre el paso 1 y el 2.
            if correo_en_uso(email, request.user):
                messages.error(request, "Ese correo ya pertenece a otra cuenta. Intente con otro.")
                return redirect("editar_perfil")
            request.user.email = email
            request.user.save(update_fields=["email"])
            messages.success(request, "Su correo electrónico fue actualizado.")
            return redirect("editar_perfil")
    return mostrar_perfil(request)


@require_POST
@login_required
def verificar_correo(request):
    """Paso 1: si el correo nuevo no pertenece a otra cuenta, pasa a pedir la contraseña."""
    form_correo = NuevoCorreoForm(request.user, request.POST, prefix="correo")
    if not form_correo.is_valid():
        request.session.pop(CORREO_PENDIENTE, None)
        return mostrar_perfil(request, form_correo=form_correo)
    request.session[CORREO_PENDIENTE] = form_correo.cleaned_data["email"]
    return redirect("editar_perfil")
