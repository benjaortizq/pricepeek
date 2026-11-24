from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User

from .models import Incident
from .resolucion import EXTRACCION_FALLIDA, NoSePuedeResolver, Resolucion, acciones_para, codigos_de_la_tienda

INCIDENCIAS_POR_PAGINA = 25

# Los dos registros que consulta el administrador (RF-43): lo que falló al extraer los datos
# de las tiendas y los productos que quedaron fuera de la comparación por no traer un código válido.
FALLIDAS = "fallidas"
EXCLUIDOS = "excluidos"
REGISTROS = {
    FALLIDAS: EXTRACCION_FALLIDA,
    EXCLUIDOS: [Incident.Kind.INVALID_BARCODE],
}

# Las extracciones fallidas se resuelven desde aquí; por defecto se ven las pendientes.
PENDIENTES = ""
ESTADOS = {
    PENDIENTES: [Incident.Status.PENDING],
    "resueltas": [Incident.Status.RESOLVED],
    "todas": list(Incident.Status),
}

PERIODOS = {
    "24h": ("Últimas 24 horas", timedelta(hours=24)),
    "7d": ("Últimos 7 días", timedelta(days=7)),
    "30d": ("Últimos 30 días", timedelta(days=30)),
}

ICONOS = {
    Incident.Kind.INVALID_BARCODE: "barcode",
    Incident.Kind.DOWNLOAD_FAILED: "cloud_off",
    Incident.Kind.PRODUCT_NOT_FOUND: "search_off",
    Incident.Kind.PRICE_NOT_FOUND: "money_off",
    Incident.Kind.BARCODE_MISMATCH: "compare_arrows",
    Incident.Kind.SUSPICIOUS_PRICE: "warning",
}


def comercios_del_registro(incidencias):
    """Cada comercio con los nombres con que quedó guardado (algunos traen espacios o saltos de línea)."""
    comercios = {}
    nombres = incidencias.exclude(store_name="").order_by().values_list("store_name", flat=True).distinct()
    for nombre in nombres:
        comercios.setdefault(nombre.strip(), []).append(nombre)
    return dict(sorted(comercios.items(), key=lambda comercio: comercio[0].casefold()))


@role_required(User.Role.ADMIN)
def incidencias(request):
    """Registro de extracciones de datos fallidas y de productos excluidos por no tener un código válido."""
    registro = request.GET.get("registro")
    if registro not in REGISTROS:
        registro = FALLIDAS
    del_registro = Incident.objects.filter(kind__in=REGISTROS[registro])

    estado = request.GET.get("estado", PENDIENTES)
    if registro != FALLIDAS or estado not in ESTADOS:
        estado = PENDIENTES
    if registro == FALLIDAS:
        del_registro = del_registro.filter(status__in=ESTADOS[estado])

    totales = Incident.objects.aggregate(
        fallidas=Count("pk", filter=Q(kind__in=REGISTROS[FALLIDAS], status=Incident.Status.PENDING)),
        excluidos=Count("pk", filter=Q(kind__in=REGISTROS[EXCLUIDOS])),
    )
    por_tipo = dict(del_registro.order_by().values_list("kind").annotate(total=Count("pk")))
    comercios = comercios_del_registro(del_registro)

    busqueda = request.GET.get("q", "").strip()
    comercio = request.GET.get("comercio", "")
    tipo = request.GET.get("tipo", "")
    periodo = request.GET.get("periodo", "")

    lista = del_registro.select_related("resolved_by")
    if busqueda:
        lista = lista.filter(
            Q(product_name__icontains=busqueda) | Q(gtin__icontains=busqueda) | Q(reason__icontains=busqueda)
        )
    if comercio in comercios:
        lista = lista.filter(store_name__in=comercios[comercio])
    else:
        comercio = ""
    if registro == FALLIDAS and tipo in REGISTROS[FALLIDAS]:
        lista = lista.filter(kind=tipo)
    else:
        tipo = ""
    if periodo in PERIODOS:
        lista = lista.filter(created_at__gte=timezone.now() - PERIODOS[periodo][1])
    else:
        periodo = ""

    pagina = Paginator(lista.order_by("-created_at", "-pk"), INCIDENCIAS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    for incidencia in pagina.object_list:
        incidencia.icono = ICONOS.get(incidencia.kind, "report")
        incidencia.acciones = acciones_para(incidencia)
        if incidencia.kind == Incident.Kind.BARCODE_MISMATCH:
            incidencia.codigos_tienda = codigos_de_la_tienda(incidencia)

    return render(
        request,
        "ingestion/incidencias.html",
        {
            "registro": registro,
            "totales": totales,
            "pagina": pagina,
            "busqueda": busqueda,
            "comercio": comercio,
            "comercios": list(comercios),
            "tipo": tipo,
            "tipos": [(t.value, t.label, por_tipo.get(t.value, 0)) for t in REGISTROS[FALLIDAS]],
            "estado": estado,
            "periodo": periodo,
            "periodos": [(clave, nombre) for clave, (nombre, _) in PERIODOS.items()],
            "hay_filtros": bool(busqueda or comercio or tipo or periodo or estado),
        },
    )


def _volver(request):
    """La lista de donde vino el administrador, con sus filtros y su página."""
    volver = request.POST.get("volver", "")
    if volver.startswith(reverse("incidencias")) and url_has_allowed_host_and_scheme(
        volver, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return volver
    return reverse("incidencias")


@role_required(User.Role.ADMIN)
@require_POST
def resolver_incidencia(request, pk):
    """Los botones de una extracción fallida: aceptar el precio o el código, cambiar el enlace..."""
    incidencia = get_object_or_404(Incident, pk=pk, kind__in=EXTRACCION_FALLIDA)
    try:
        resultado = Resolucion(incidencia, request.user).ejecutar(
            request.POST.get("accion", ""), url=request.POST.get("url", "")
        )
    except NoSePuedeResolver as error:
        messages.error(request, str(error))
    else:
        (messages.success if resultado.exito else messages.warning)(request, resultado.mensaje)
        if resultado.repetidas == 1:
            messages.info(request, "También se resolvió 1 incidencia repetida del mismo precio.")
        elif resultado.repetidas:
            messages.info(
                request, f"También se resolvieron {resultado.repetidas} incidencias repetidas del mismo precio."
            )
    return redirect(_volver(request))
