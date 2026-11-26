"""Vistas HTTP de la aplicación accounts."""

import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from auditoria.registro import Accion, registrar
from core.panel import indicador, inicio_de_hoy, pestanas, plural
from ingestion.models import Incident
from ingestion.resolucion import EXTRACCION_FALLIDA
from ingestion.views import ICONOS
from products.busqueda import buscar_productos
from products.models import ProductView, Products
from products.ofertas import (
    categorias_del_inicio,
    mejores_ofertas,
    ultima_verificacion,
)
from products.popularidad import mas_populares
from reviews.indicadores import resumen_de_moderacion
from reviews.models import ReviewDeletion, ReviewReport, Reviews
from reviews.models import ReviewPhoto

from .decorators import role_required
from .forms import (
    AlertasPrecioForm,
    CambioContrasenaForm,
    CodigoCambioContrasenaForm,
    ConsentimientoPrivacidadForm,
    ConfirmarCorreoForm,
    EditarNombreForm,
    EliminarCuentaForm,
    NuevoCorreoForm,
    RegistroClienteForm,
    SuspenderClienteForm,
    correo_en_uso,
)
from .models import PrivacyConsent, User
from .privacy import PRIVACY_POLICY_VERSION

CAMBIO_PENDIENTE = "cambio_contrasena_pendiente"
CORREO_PENDIENTE = "cambio_correo_pendiente"


def registro(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                usuario = form.save()
                PrivacyConsent.objects.create(
                    user=usuario,
                    policy_version=PRIVACY_POLICY_VERSION,
                    accepted_at=timezone.now(),
                )
            messages.success(
                request, "Su cuenta fue creada. Ya puede iniciar sesión."
            )
            return redirect("login")
    else:
        form = RegistroClienteForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
@role_required(User.Role.CLIENT)
def consentimiento_privacidad(request):
    if PrivacyConsent.objects.filter(
        user=request.user,
        policy_version=PRIVACY_POLICY_VERSION,
        revoked_at__isnull=True,
    ).exists():
        return redirect("panel")

    if request.method == "POST":
        form = ConsentimientoPrivacidadForm(request.POST)
        if form.is_valid():
            PrivacyConsent.objects.create(
                user=request.user,
                policy_version=PRIVACY_POLICY_VERSION,
                accepted_at=timezone.now(),
            )
            return redirect("panel")
    else:
        form = ConsentimientoPrivacidadForm()
    return render(
        request, "accounts/consentimiento_privacidad.html", {"form": form}
    )


@login_required
def panel(request):
    if request.user.role == User.Role.ENTERPRISE:
        return redirect("inicio_empresa")
    if request.user.role == User.Role.ADMIN:
        return redirect("inicio_administrador")
    return redirect("inicio_cliente")


PRODUCTOS_EN_INICIO = (
    5  # las búsquedas rápidas debajo del buscador, como en el diseño
)


def mostrar_inicio(request, titulo):
    """El inicio según frontend/html/index.html: búsqueda, categorías y mejores ofertas del día."""
    # Las búsquedas rápidas del buscador: los más vistos de la semana primero; si nadie ha visto
    # nada todavía, quedan por nombre.
    productos = list(mas_populares(buscar_productos(""))[:PRODUCTOS_EN_INICIO])
    hay_populares = bool(productos) and productos[0].popularidad > 0
    ofertas = mejores_ofertas()
    return render(
        request,
        "accounts/mainpage.html",
        {
            "titulo": titulo,
            "productos": productos,
            "hay_populares": hay_populares,
            "categorias": categorias_del_inicio(),
            "total_productos": Products.objects.count(),
            "ofertas": ofertas,
            "ultima_verificacion": ultima_verificacion(ofertas),
            "hoy": timezone.localdate(),
            # El buscador grande del inicio reemplaza al del encabezado.
            "sin_busqueda_en_encabezado": True,
        },
    )


@role_required(User.Role.CLIENT)
def inicio_cliente(request):
    return mostrar_inicio(request, "Inicio del cliente")


@role_required(User.Role.ENTERPRISE)
def inicio_empresa(request):
    return redirect("enterprise:panel")


ELEMENTOS_EN_LA_COLA = 10


def resenas_en_la_cola(limite):
    """Las reseñas con reportes pendientes, la de reporte más reciente primero."""
    pendientes = (
        ReviewReport.objects.filter(status=ReviewReport.Status.PENDING)
        .values("review_id")
        .annotate(reportes=Count("id"), fecha=Max("created_at"))
        .order_by("-fecha")[:limite]
    )
    grupos = {grupo["review_id"]: grupo for grupo in pendientes}
    resenas = Reviews.objects.select_related(
        "variant__product", "user"
    ).filter(pk__in=list(grupos))
    motivos = {}
    for review_id, motivo in (
        ReviewReport.objects.filter(
            status=ReviewReport.Status.PENDING, review_id__in=list(grupos)
        )
        .order_by("created_at")
        .values_list("review_id", "reason")
    ):
        motivos.setdefault(review_id, motivo)
    return [
        {
            "tipo": "resena",
            "resena": resena,
            "reportes": grupos[resena.pk]["reportes"],
            "fecha": grupos[resena.pk]["fecha"],
            "motivo": motivos.get(resena.pk, ""),
        }
        for resena in resenas
    ]


def incidencias_en_la_cola(limite):
    pendientes = Incident.objects.filter(
        kind__in=EXTRACCION_FALLIDA, status=Incident.Status.PENDING
    )
    return [
        {
            "tipo": "incidencia",
            "incidencia": incidencia,
            "fecha": incidencia.created_at,
            "icono": ICONOS.get(incidencia.kind, "report"),
        }
        for incidencia in pendientes.order_by("-created_at")[:limite]
    ]


@role_required(User.Role.ADMIN)
def inicio_administrador(request):
    """Resumen del panel de moderación (frontend/html/admin-panel-moderacion.html): lo que espera
    revisión, de las reseñas reportadas y de la obtención de datos, en una sola cola."""
    moderacion = resumen_de_moderacion()
    incidencias_pendientes = Incident.objects.filter(
        kind__in=EXTRACCION_FALLIDA, status=Incident.Status.PENDING
    )
    total_incidencias = incidencias_pendientes.count()
    total_resenas = moderacion["en_cola"]

    cola = request.GET.get("cola", "")
    if cola not in ("", "resenas", "datos"):
        cola = ""
    elementos = []
    if cola in ("", "resenas"):
        elementos += resenas_en_la_cola(ELEMENTOS_EN_LA_COLA)
    if cola in ("", "datos"):
        elementos += incidencias_en_la_cola(ELEMENTOS_EN_LA_COLA)
    elementos = sorted(
        elementos, key=lambda elemento: elemento["fecha"], reverse=True
    )[:ELEMENTOS_EN_LA_COLA]
    en_la_cola = {
        "": total_resenas + total_incidencias,
        "resenas": total_resenas,
        "datos": total_incidencias,
    }[cola]

    hoy = (
        moderacion["reportes_hoy"]
        + incidencias_pendientes.filter(
            created_at__gte=inicio_de_hoy()
        ).count()
    )
    tiempo = moderacion["tiempo_promedio"] or ("—", "")
    tasa = moderacion["tasa_eliminacion"]
    clientes = User.objects.filter(role=User.Role.CLIENT)
    suspendidas = clientes.filter(is_active=False).count()
    return render(
        request,
        "accounts/panel_administrador.html",
        {
            "elementos": elementos,
            "cola": cola,
            "en_la_cola": en_la_cola,
            "kpis": [
                indicador(
                    "Pendientes de revisión",
                    total_resenas + total_incidencias,
                    unidad="casos",
                    insignia=f"+{hoy} hoy",
                    tono="alerta" if hoy else "",
                    icono="arrow_upward" if hoy else "",
                    pie_izq=plural(
                        total_resenas, "reseña reportada", "reseñas reportadas"
                    ),
                    pie_der=plural(
                        total_incidencias,
                        "extracción fallida",
                        "extracciones fallidas",
                    ),
                    destacada=True,
                ),
                indicador(
                    "Tiempo prom. resolución",
                    tiempo[0],
                    unidad=tiempo[1],
                    insignia="Reseñas",
                    pie_izq="Últimos 30 días"
                    if moderacion["tiempo_promedio"]
                    else "Sin datos",
                ),
                indicador(
                    "Tasa de eliminación",
                    "—" if tasa is None else tasa,
                    unidad="" if tasa is None else "%",
                    insignia="Últimos 30 días",
                    pie_izq=plural(
                        moderacion["eliminadas_30"],
                        "reseña eliminada",
                        "reseñas eliminadas",
                    ),
                    pie_der=plural(
                        moderacion["mantenidas_30"],
                        "reseña mantenida",
                        "reseñas mantenidas",
                    ),
                ),
                indicador(
                    "Cuentas suspendidas",
                    suspendidas,
                    insignia="Clientes",
                    tono="marca",
                    pie_izq=plural(
                        clientes.count(),
                        "cliente registrado",
                        "clientes registrados",
                    ),
                ),
            ],
            "pestanas": pestanas(
                reverse("inicio_administrador"),
                "cola",
                [
                    (
                        "",
                        "Todos los pendientes",
                        total_resenas + total_incidencias,
                    ),
                    ("resenas", "Reseñas reportadas", total_resenas),
                    ("datos", "Extracciones fallidas", total_incidencias),
                ],
                cola,
            ),
        },
    )


# --- Suspensión de cuentas de clientes (RF-42) ---

CLIENTES_POR_PAGINA = 20
INFRACCIONES_REITERADAS = (
    2  # desde cuántas reseñas eliminadas se resalta al cliente
)


def clientes_con_infracciones():
    """Clientes con la cantidad de reseñas suyas que el administrador eliminó por incumplir políticas."""
    # Cada eliminación queda en ReviewDeletion, venga o no de un reporte.
    return User.objects.filter(role=User.Role.CLIENT).annotate(
        infracciones=Count("resenas_eliminadas", distinct=True)
    )


@role_required(User.Role.ADMIN)
def clientes(request):
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    lista = clientes_con_infracciones()
    if busqueda:
        lista = lista.filter(
            Q(email__icontains=busqueda)
            | Q(first_name__icontains=busqueda)
            | Q(last_name__icontains=busqueda)
        )
    if estado == "activas":
        lista = lista.filter(is_active=True)
    elif estado == "suspendidas":
        lista = lista.filter(is_active=False)
    else:
        estado = ""
    # Los clientes con más infracciones aparecen primero.
    pagina = Paginator(
        lista.order_by("-infracciones", "email"), CLIENTES_POR_PAGINA
    ).get_page(request.GET.get("pagina"))
    todos = clientes_con_infracciones()
    total = todos.count()
    activas = todos.filter(is_active=True).count()
    reiterados = todos.filter(
        infracciones__gte=INFRACCIONES_REITERADAS
    ).count()
    return render(
        request,
        "accounts/clientes.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "estado": estado,
            "reiteradas": INFRACCIONES_REITERADAS,
            "kpis": [
                indicador(
                    "Clientes registrados",
                    total,
                    pie_izq="Cuentas de cliente",
                    destacada=True,
                ),
                indicador(
                    "Cuentas activas",
                    activas,
                    insignia="Pueden usar el sitio",
                    tono="bien",
                    icono="check_circle",
                ),
                indicador(
                    "Cuentas suspendidas",
                    total - activas,
                    insignia="Sin acceso" if total - activas else "",
                    tono="alerta",
                    icono="block",
                    pie_izq="Hasta que un administrador las reactive",
                ),
                indicador(
                    "Incumplen de forma reiterada",
                    reiterados,
                    pie_izq=f"Desde {INFRACCIONES_REITERADAS} reseñas eliminadas",
                ),
            ],
            "pestanas": pestanas(
                reverse("clientes"),
                "estado",
                [
                    ("", "Todas las cuentas", total),
                    ("activas", "Activas", activas),
                    ("suspendidas", "Suspendidas", total - activas),
                ],
                estado,
                conservar={"q": busqueda},
            ),
            "total_texto": plural(
                pagina.paginator.count, "cliente", "clientes"
            ),
        },
    )


def mostrar_detalle_cliente(request, cliente, form=None):
    infracciones = list(
        ReviewDeletion.objects.filter(author=cliente).select_related(
            "deleted_by"
        )
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
    return get_object_or_404(
        User.objects.select_related("suspended_by"),
        pk=pk,
        role=User.Role.CLIENT,
    )


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
    motivo = form.cleaned_data["motivo"]
    with transaction.atomic():
        suspendida = User.objects.suspender_cliente(
            cliente.pk, request.user, motivo
        )
        if suspendida:
            registrar(
                request.user,
                Accion.CLIENT_SUSPEND,
                cliente.pk,
                cliente.email,
                {"Motivo": motivo},
            )
    if suspendida:
        messages.success(
            request, f"La cuenta de {cliente.email} fue suspendida."
        )
    else:
        messages.error(request, "Esa cuenta ya estaba suspendida.")
    return redirect("detalle_cliente", pk=cliente.pk)


@role_required(User.Role.ADMIN)
@require_POST
def reactivar_cliente(request, pk):
    cliente = obtener_cliente(pk)
    with transaction.atomic():
        reactivada = User.objects.reactivar_cliente(cliente.pk)
        if reactivada:
            registrar(
                request.user,
                Accion.CLIENT_REACTIVATE,
                cliente.pk,
                cliente.email,
            )
    if reactivada:
        messages.success(
            request, f"La cuenta de {cliente.email} fue reactivada."
        )
    else:
        messages.error(request, "Esa cuenta no estaba suspendida.")
    return redirect("detalle_cliente", pk=cliente.pk)


@role_required(User.Role.CLIENT)
def eliminar_cuenta(request):
    if request.method == "POST":
        form = EliminarCuentaForm(request.user, request.POST)
        if form.is_valid():
            usuario = request.user
            resenas_ids = list(
                Reviews.objects.filter(user_id=usuario.pk).values_list(
                    "pk", flat=True
                )
            )
            fotos = list(ReviewPhoto.objects.filter(review_id__in=resenas_ids))
            with transaction.atomic():
                ReviewReport.objects.filter(
                    Q(reporter=usuario) | Q(review_id__in=resenas_ids)
                ).delete()
                ReviewPhoto.objects.filter(review_id__in=resenas_ids).delete()
                Reviews.objects.filter(user_id=usuario.pk).delete()
                PrivacyConsent.objects.filter(
                    user=usuario, revoked_at__isnull=True
                ).update(revoked_at=timezone.now())
                logout(request)
                usuario.delete()
            for foto in fotos:
                if foto.image.name:
                    foto.image.storage.delete(foto.image.name)
            messages.success(
                request, "Su cuenta y sus datos fueron eliminados."
            )
            return redirect("login")
    else:
        form = EliminarCuentaForm(request.user)
    return render(request, "accounts/eliminar_cuenta.html", {"form": form})


@login_required
@role_required(User.Role.CLIENT)
def descargar_datos_personales(request):
    """Entrega al cliente una copia legible de los datos personales de su cuenta."""
    usuario = request.user
    lista_deseos = [
        {
            "producto": articulo.variant.product.name,
            "variante": articulo.variant.name,
            "precio_objetivo": articulo.target_price,
            "moneda": articulo.currency.name,
            "alerta_activa": articulo.alert_enabled,
            "comercio": articulo.store.name if articulo.store_id else None,
        }
        for articulo in usuario.wishlist_items.select_related(
            "variant__product", "currency", "store"
        )
    ]
    resenas_query = Reviews.objects.filter(user_id=usuario.pk).select_related(
        "variant__product"
    )
    fotos_resenas = {
        foto.review_id: foto
        for foto in ReviewPhoto.objects.filter(
            review_id__in=resenas_query.values_list("pk", flat=True)
        )
    }
    resenas = [
        {
            "producto": resena.variant.product.name,
            "contenido": resena.content,
            "calificacion": resena.score,
            "creada": resena.created_at.isoformat(),
            "actualizada": resena.updated_at.isoformat(),
            "foto": fotos_resenas[resena.pk].image.url
            if resena.pk in fotos_resenas
            else None,
        }
        for resena in resenas_query
    ]
    datos = {
        "cuenta": {
            "nombre": usuario.first_name,
            "apellido": usuario.last_name,
            "correo": usuario.email,
            "tipo": usuario.get_role_display(),
            "creada": usuario.date_joined.isoformat(),
            "ultimo_acceso": usuario.last_login.isoformat()
            if usuario.last_login
            else None,
            "ultimo_cambio_de_contrasena": usuario.last_password_change.isoformat(),
            "alertas_por_correo": usuario.active_alerts,
            "suspendida_desde": usuario.suspended_at.isoformat()
            if usuario.suspended_at
            else None,
            "motivo_de_suspension": usuario.suspension_reason,
        },
        "lista_de_deseos": lista_deseos,
        "resenas": resenas,
        "reportes_de_resenas": [
            {
                "id_resena": reporte.review_id,
                "motivo": reporte.reason,
                "estado": reporte.get_status_display(),
                "creado": reporte.created_at.isoformat(),
            }
            for reporte in ReviewReport.objects.filter(reporter=usuario)
        ],
        "reportes_recibidos": [
            {
                "id_resena": reporte.review_id,
                "motivo": reporte.reason,
                "estado": reporte.get_status_display(),
                "nota_de_resolucion": reporte.resolution_note,
                "creado": reporte.created_at.isoformat(),
            }
            for reporte in ReviewReport.objects.filter(review_author=usuario)
        ],
        "visitas_a_productos": [
            {"id_producto": visita.product_id, "hora": visita.hour.isoformat()}
            for visita in ProductView.objects.filter(user=usuario).order_by(
                "-hour"
            )
        ],
        "consentimientos_de_privacidad": [
            {
                "version": consentimiento.policy_version,
                "aceptado": consentimiento.accepted_at.isoformat(),
                "revocado": consentimiento.revoked_at.isoformat()
                if consentimiento.revoked_at
                else None,
            }
            for consentimiento in PrivacyConsent.objects.filter(user=usuario)
        ],
    }
    respuesta = JsonResponse(
        datos, json_dumps_params={"ensure_ascii": False, "indent": 2}
    )
    respuesta["Content-Disposition"] = (
        'attachment; filename="mis-datos-pricepeek.json"'
    )
    return respuesta


def enviar_codigo_cambio_contrasena(user, codigo):
    contexto = {
        "user": user,
        "codigo": codigo,
        "minutos": settings.PASSWORD_CHANGE_CODE_TIMEOUT // 60,
    }
    asunto = render_to_string(
        "registration/password_change_code_subject.txt", contexto
    )
    cuerpo = render_to_string(
        "registration/password_change_code_email.html", contexto
    )
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
                "expira": timezone.now().timestamp()
                + settings.PASSWORD_CHANGE_CODE_TIMEOUT,
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
                messages.error(
                    request,
                    "El código venció. Vuelva a solicitar el cambio de contraseña.",
                )
                return redirect("password_change")
            if not check_password(
                form.cleaned_data["codigo"], pendiente["codigo"]
            ):
                pendiente["intentos"] += 1
                if (
                    pendiente["intentos"]
                    >= settings.PASSWORD_CHANGE_CODE_MAX_ATTEMPTS
                ):
                    del request.session[CAMBIO_PENDIENTE]
                    messages.error(
                        request,
                        "Demasiados intentos fallidos. Vuelva a solicitar el cambio de contraseña.",
                    )
                    return redirect("password_change")
                request.session[CAMBIO_PENDIENTE] = pendiente
                restantes = (
                    settings.PASSWORD_CHANGE_CODE_MAX_ATTEMPTS
                    - pendiente["intentos"]
                )
                form.add_error(
                    "codigo",
                    f"El código no coincide. Revise el mensaje de correo e inténtelo de nuevo; le quedan {restantes} intento{'s' if restantes != 1 else ''}.",
                )
            else:
                usuario = request.user
                usuario.password = pendiente["password"]
                usuario.last_password_change = timezone.now()
                usuario.save(
                    update_fields=["password", "last_password_change"]
                )
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


def mostrar_perfil(
    request,
    form_nombre=None,
    form_correo=None,
    form_confirmar=None,
    form_alertas=None,
):
    correo_pendiente = request.session.get(CORREO_PENDIENTE)
    if correo_pendiente:
        form_confirmar = form_confirmar or ConfirmarCorreoForm(
            request.user, prefix="confirmar"
        )
    return render(
        request,
        "accounts/editar_perfil.html",
        {
            "form_nombre": form_nombre
            or EditarNombreForm(instance=request.user, prefix="nombre"),
            "form_correo": form_correo
            or NuevoCorreoForm(request.user, prefix="correo"),
            "form_confirmar": form_confirmar,
            "form_alertas": form_alertas
            or AlertasPrecioForm(instance=request.user, prefix="alertas"),
            "correo_pendiente": correo_pendiente,
        },
    )


@login_required
def editar_perfil(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "nombre":
            form_nombre = EditarNombreForm(
                request.POST, instance=request.user, prefix="nombre"
            )
            if form_nombre.is_valid():
                form_nombre.save()
                messages.success(request, "Su nombre fue actualizado.")
                return redirect("editar_perfil")
            return mostrar_perfil(request, form_nombre=form_nombre)
        if accion == "alertas" and request.user.role == User.Role.CLIENT:
            form_alertas = AlertasPrecioForm(
                request.POST, instance=request.user, prefix="alertas"
            )
            if form_alertas.is_valid():
                form_alertas.save()
                estado = (
                    "activadas"
                    if request.user.active_alerts
                    else "desactivadas"
                )
                messages.success(
                    request,
                    f"Las alertas de baja de precio quedaron {estado}.",
                )
            return redirect("editar_perfil")
        if accion == "cancelar_correo":
            request.session.pop(CORREO_PENDIENTE, None)
            return redirect("editar_perfil")
        if accion == "confirmar_correo" and request.session.get(
            CORREO_PENDIENTE
        ):
            form_confirmar = ConfirmarCorreoForm(
                request.user, request.POST, prefix="confirmar"
            )
            if not form_confirmar.is_valid():
                return mostrar_perfil(request, form_confirmar=form_confirmar)
            email = request.session.pop(CORREO_PENDIENTE)
            # Se vuelve a revisar: otra cuenta pudo tomar el correo entre el paso 1 y el 2.
            if correo_en_uso(email, request.user):
                messages.error(
                    request,
                    "Ese correo ya pertenece a otra cuenta. Intente con otro.",
                )
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
