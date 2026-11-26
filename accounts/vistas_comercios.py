"""Comercios asociados en el panel de administración (issue «Gestión de comercios asociados»).

El administrador registra cada comercio con su cuenta de empresa, define cómo se obtienen sus
datos (web scraping o datos provistos por el comercio) y lo activa o desactiva. Lo que eso
cambia en el resto del sitio está en products/comercios.py.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.panel import indicador, pestanas, plural
from core.translations import translate_text
from products.comercios import comercios_con_lector, mecanismo_de, nombre_del_comercio
from products.models import PartnerStore, Prices, Stores

from .comercios import (
    cambiar_estado,
    crear_cuenta_de_empresa,
    cuentas_de_empresa,
    enviar_acceso,
    guardar_datos_del_comercio,
    perfil_de,
    registrar_comercio as guardar_comercio_nuevo,
)
from .decorators import role_required
from .forms import CuentaDeEmpresaForm, DatosDelComercioForm, RegistrarComercioForm
from .models import AccountsUser, User

COMERCIOS_POR_PAGINA = 20
FILTROS = {
    "activos": lambda fila: fila["activo"],
    "desactivados": lambda fila: not fila["activo"],
    "sin-cuenta": lambda fila: not fila["cuentas"],
}


def filas_de_comercios():
    """Cada comercio con lo que muestra la lista, en pocas consultas (con Supabase cada una tarda ~80 ms)."""
    perfiles = {perfil.store_id: perfil for perfil in PartnerStore.objects.all()}
    con_lector = comercios_con_lector()
    precios = {
        fila["id_store_id"]: fila
        for fila in Prices.objects.order_by()
        .values("id_store_id")
        .annotate(total=Count("pk"), ultima=Max("updated_at"))
    }
    cuentas = dict(
        AccountsUser.objects.filter(role=User.Role.ENTERPRISE, from_store__isnull=False)
        .order_by()
        .values("from_store_id")
        .annotate(total=Count("pk"))
        .values_list("from_store_id", "total")
    )
    filas = []
    for tienda in Stores.objects.all():
        perfil = perfiles.get(tienda.pk)
        filas.append(
            {
                "tienda": tienda,
                "nombre": nombre_del_comercio(tienda),
                "activo": perfil.is_active if perfil else True,
                "mecanismo": mecanismo_de(tienda, perfil, con_lector),
                "con_lector": tienda.pk in con_lector,
                "precios": precios.get(tienda.pk, {}).get("total", 0),
                "ultima_revision": precios.get(tienda.pk, {}).get("ultima"),
                "cuentas": cuentas.get(tienda.pk, 0),
            }
        )
    return sorted(filas, key=lambda fila: fila["nombre"].casefold())


@role_required(User.Role.ADMIN)
def comercios(request):
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    if estado not in FILTROS:
        estado = ""
    todas = filas_de_comercios()
    cantidad = {clave: sum(map(filtro, todas)) for clave, filtro in FILTROS.items()}
    lista = [
        fila
        for fila in todas
        if busqueda.casefold() in fila["nombre"].casefold() and (not estado or FILTROS[estado](fila))
    ]
    pagina = Paginator(lista, COMERCIOS_POR_PAGINA).get_page(request.GET.get("pagina"))
    por_scraping = sum(fila["mecanismo"] == PartnerStore.DataSource.SCRAPING for fila in todas)
    return render(
        request,
        "accounts/comercios.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "estado": estado,
            "mecanismos": PartnerStore.DataSource,
            "kpis": [
                indicador(
                    "Comercios asociados",
                    len(todas),
                    pie_izq=f"{por_scraping} con web scraping · {len(todas) - por_scraping} con datos del comercio",
                    destacada=True,
                ),
                indicador("Activos", cantidad["activos"], insignia="Sus precios se muestran", tono="bien", icono="check_circle"),
                indicador(
                    "Desactivados",
                    cantidad["desactivados"],
                    insignia="Precios ocultos" if cantidad["desactivados"] else "",
                    tono="alerta",
                    icono="visibility_off",
                    pie_izq="No se muestran ni se actualizan",
                ),
                indicador("Sin cuenta de empresa", cantidad["sin-cuenta"], pie_izq="Cada comercio necesita una"),
            ],
            "pestanas": pestanas(
                reverse("comercios"),
                "estado",
                [
                    ("", "Todos los comercios", len(todas)),
                    ("activos", "Activos", cantidad["activos"]),
                    ("desactivados", "Desactivados", cantidad["desactivados"]),
                    ("sin-cuenta", "Sin cuenta de empresa", cantidad["sin-cuenta"]),
                ],
                estado,
                conservar={"q": busqueda},
            ),
            "total_texto": plural(pagina.paginator.count, "comercio", "comercios"),
        },
    )


def _avisar_acceso(request, cuenta, tienda):
    if enviar_acceso(cuenta, tienda, request):
        messages.info(
            request,
            translate_text("Se envió a {correo} el enlace para elegir su contraseña.", correo=cuenta.email),
        )
    else:
        messages.error(
            request,
            translate_text(
                "No se pudo enviar el correo a {correo}. La cuenta quedó creada: use «Reenviar acceso» más tarde.",
                correo=cuenta.email,
            ),
        )


@role_required(User.Role.ADMIN)
def registrar_comercio(request):
    if request.method == "POST":
        form = RegistrarComercioForm(request.POST)
        if form.is_valid():
            datos = form.cleaned_data
            with transaction.atomic():
                tienda = guardar_comercio_nuevo(
                    nombre=datos["name"],
                    descripcion=datos["description"],
                    mecanismo=datos["data_source"],
                    activo=datos["is_active"],
                    administrador=request.user,
                )
                cuenta = crear_cuenta_de_empresa(
                    tienda, correo=datos["email"], nombre=datos["first_name"], apellidos=datos["last_name"]
                )
            messages.success(
                request,
                translate_text("Se registró el comercio «{comercio}» con su cuenta de empresa.", comercio=tienda.name),
            )
            _avisar_acceso(request, cuenta, tienda)
            return redirect("detalle_comercio", pk=tienda.pk)
    else:
        form = RegistrarComercioForm(initial={"is_active": True})
    return render(request, "accounts/registrar_comercio.html", {"form": form, "mecanismos": PartnerStore.DataSource})


def _mostrar_detalle(request, tienda, form_datos=None, form_cuenta=None):
    perfil = perfil_de(tienda)
    con_lector = comercios_con_lector()
    mecanismo = mecanismo_de(tienda, perfil, con_lector)
    if form_datos is None:
        form_datos = DatosDelComercioForm(
            tienda=tienda,
            initial={"name": nombre_del_comercio(tienda), "description": tienda.description or "", "data_source": mecanismo},
        )
    precios = Prices.objects.filter(id_store_id=tienda.pk).aggregate(
        total=Count("pk"), disponibles=Count("pk", filter=Q(is_available=True)), ultima=Max("updated_at")
    )
    return render(
        request,
        "accounts/detalle_comercio.html",
        {
            "tienda": tienda,
            "nombre": nombre_del_comercio(tienda),
            "perfil": perfil,
            "activo": perfil.is_active if perfil else True,
            "mecanismo": mecanismo,
            "mecanismos": PartnerStore.DataSource,
            "con_lector": tienda.pk in con_lector,
            "sin_lector": tienda.pk not in con_lector,
            "cuentas": cuentas_de_empresa(tienda),
            "form_datos": form_datos,
            "form_cuenta": form_cuenta or CuentaDeEmpresaForm(),
            "precios": precios,
        },
    )


@role_required(User.Role.ADMIN)
def detalle_comercio(request, pk):
    tienda = get_object_or_404(Stores, pk=pk)
    if request.method == "POST":
        form = DatosDelComercioForm(request.POST, tienda=tienda)
        if form.is_valid():
            datos = form.cleaned_data
            if guardar_datos_del_comercio(
                tienda, nombre=datos["name"], descripcion=datos["description"], mecanismo=datos["data_source"]
            ):
                messages.success(request, translate_text("Se guardaron los datos del comercio."))
            else:
                messages.info(request, translate_text("No había cambios que guardar."))
            return redirect("detalle_comercio", pk=tienda.pk)
        return _mostrar_detalle(request, tienda, form_datos=form)
    return _mostrar_detalle(request, tienda)


@role_required(User.Role.ADMIN)
@require_POST
def estado_comercio(request, pk):
    tienda = get_object_or_404(Stores, pk=pk)
    activo = request.POST.get("activo") == "1"
    nombre = nombre_del_comercio(tienda)
    if not cambiar_estado(tienda, activo=activo, administrador=request.user):
        texto = "El comercio «{comercio}» ya estaba activo." if activo else "El comercio «{comercio}» ya estaba desactivado."
        messages.info(request, translate_text(texto, comercio=nombre))
    elif activo:
        messages.success(
            request,
            translate_text("Se activó el comercio «{comercio}». Sus precios vuelven a mostrarse.", comercio=nombre),
        )
    else:
        messages.success(
            request,
            translate_text(
                "Se desactivó el comercio «{comercio}». Sus precios ya no se muestran y la obtención de datos deja de revisarlos.",
                comercio=nombre,
            ),
        )
    return redirect("detalle_comercio", pk=tienda.pk)


@role_required(User.Role.ADMIN)
@require_POST
def crear_cuenta_comercio(request, pk):
    tienda = get_object_or_404(Stores, pk=pk)
    form = CuentaDeEmpresaForm(request.POST)
    if not form.is_valid():
        return _mostrar_detalle(request, tienda, form_cuenta=form)
    datos = form.cleaned_data
    cuenta = crear_cuenta_de_empresa(
        tienda, correo=datos["email"], nombre=datos["first_name"], apellidos=datos["last_name"]
    )
    messages.success(request, translate_text("Se creó la cuenta de empresa {correo}.", correo=cuenta.email))
    _avisar_acceso(request, cuenta, tienda)
    return redirect("detalle_comercio", pk=tienda.pk)


@role_required(User.Role.ADMIN)
@require_POST
def reenviar_acceso(request, pk, cuenta_pk):
    tienda = get_object_or_404(Stores, pk=pk)
    cuenta = get_object_or_404(cuentas_de_empresa(tienda), pk=cuenta_pk)
    _avisar_acceso(request, cuenta, tienda)
    return redirect("detalle_comercio", pk=tienda.pk)
