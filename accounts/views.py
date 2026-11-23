import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from products.busqueda import buscar_productos, con_imagen
from products.popularidad import mas_populares
from reviews.models import ReviewReport

from .decorators import role_required
from .forms import (
    AlertasPrecioForm,
    CambioContrasenaForm,
    CodigoCambioContrasenaForm,
    ConfirmarCorreoForm,
    EditarNombreForm,
    EliminarCuentaForm,
    NuevoCorreoForm,
    RegistroClienteForm,
    SuspenderClienteForm,
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


PRODUCTOS_EN_INICIO = 12


def mostrar_inicio(request, titulo):
    # Los más vistos de la semana primero; si nadie ha visto nada todavía, quedan por nombre.
    productos = con_imagen(mas_populares(buscar_productos(""))[:PRODUCTOS_EN_INICIO])
    hay_populares = bool(productos) and productos[0].popularidad > 0
    return render(
        request,
        "accounts/mainpage.html",
        {"titulo": titulo, "productos": productos, "hay_populares": hay_populares},
    )


@role_required(User.Role.CLIENT)
def inicio_cliente(request):
    return mostrar_inicio(request, "Inicio del cliente")


@role_required(User.Role.ENTERPRISE)
def inicio_empresa(request):
    return mostrar_inicio(request, "Panel de empresa")


@role_required(User.Role.ADMIN)
def inicio_administrador(request):
    return mostrar_inicio(request, "Panel de administración")


# --- Suspensión de cuentas de clientes (RF-42) ---

CLIENTES_POR_PAGINA = 20
INFRACCIONES_REITERADAS = 2  # desde cuántas reseñas eliminadas se resalta al cliente


def clientes_con_infracciones():
    """Clientes con la cantidad de reseñas suyas que el administrador eliminó por incumplir políticas."""
    return User.objects.filter(role=User.Role.CLIENT).annotate(
        infracciones=Count(
            "reportes_recibidos__review_id",
            filter=Q(reportes_recibidos__status=ReviewReport.Status.DELETED),
            distinct=True,
        )
    )


@role_required(User.Role.ADMIN)
def clientes(request):
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    lista = clientes_con_infracciones()
    if busqueda:
        lista = lista.filter(
            Q(email__icontains=busqueda) | Q(first_name__icontains=busqueda) | Q(last_name__icontains=busqueda)
        )
    if estado == "activas":
        lista = lista.filter(is_active=True)
    elif estado == "suspendidas":
        lista = lista.filter(is_active=False)
    else:
        estado = ""
    # Los clientes con más infracciones aparecen primero.
    pagina = Paginator(lista.order_by("-infracciones", "email"), CLIENTES_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    return render(
        request,
        "accounts/clientes.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "estado": estado,
            "reiteradas": INFRACCIONES_REITERADAS,
        },
    )


def mostrar_detalle_cliente(request, cliente, form=None):
    infracciones = list(
        ReviewReport.objects.filter(review_author=cliente, status=ReviewReport.Status.DELETED)
        .values("review_id")
        .annotate(reportes=Count("id"), fecha=Max("resolved_at"), motivo=Max("resolution_note"))
        .order_by("-fecha")
    )
    return render(
        request,
        "accounts/detalle_cliente.html",
        {
            "cliente": cliente,
            "infracciones": infracciones,
            "reiteradas": len(infracciones) >= INFRACCIONES_REITERADAS,
            "form": form or SuspenderClienteForm(),
        },
    )


def obtener_cliente(pk):
    return get_object_or_404(User.objects.select_related("suspended_by"), pk=pk, role=User.Role.CLIENT)


@role_required(User.Role.ADMIN)
def detalle_cliente(request, pk):
    return mostrar_detalle_cliente(request, obtener_cliente(pk))


@role_required(User.Role.ADMIN)
@require_POST
def suspender_cliente(request, pk):
    cliente = obtener_cliente(pk)
    form = SuspenderClienteForm(request.POST)
    if not form.is_valid():
        return mostrar_detalle_cliente(request, cliente, form)
    if User.objects.suspender_cliente(cliente.pk, request.user, form.cleaned_data["motivo"]):
        messages.success(request, f"La cuenta de {cliente.email} fue suspendida.")
    else:
        messages.error(request, "Esa cuenta ya estaba suspendida.")
    return redirect("detalle_cliente", pk=cliente.pk)


@role_required(User.Role.ADMIN)
@require_POST
def reactivar_cliente(request, pk):
    cliente = obtener_cliente(pk)
    if User.objects.reactivar_cliente(cliente.pk):
        messages.success(request, f"La cuenta de {cliente.email} fue reactivada.")
    else:
        messages.error(request, "Esa cuenta no estaba suspendida.")
    return redirect("detalle_cliente", pk=cliente.pk)


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


def mostrar_perfil(request, form_nombre=None, form_correo=None, form_confirmar=None, form_alertas=None):
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
            "form_alertas": form_alertas or AlertasPrecioForm(instance=request.user, prefix="alertas"),
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
        if accion == "alertas" and request.user.role == User.Role.CLIENT:
            form_alertas = AlertasPrecioForm(request.POST, instance=request.user, prefix="alertas")
            if form_alertas.is_valid():
                form_alertas.save()
                estado = "activadas" if request.user.active_alerts else "desactivadas"
                messages.success(request, f"Las alertas de baja de precio quedaron {estado}.")
            return redirect("editar_perfil")
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
