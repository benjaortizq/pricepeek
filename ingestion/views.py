"""Vistas HTTP de la aplicación ingestion."""

from datetime import timedelta

from django.conf import settings
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
from auditoria.registro import Accion, registrar
from core.panel import (
    duracion_aproximada,
    indicador,
    inicio_de_hoy,
    inicio_del_mes,
    pestanas,
    plural,
)

from . import ejecucion_manual
from .models import Incident, ManualRun
from .resolucion import (
    ACEPTAR_CODIGO,
    ACEPTAR_PRECIO,
    CAMBIAR_ENLACE,
    DESCARTAR,
    EXTRACCION_FALLIDA,
    REVISAR,
    NoSePuedeResolver,
    Resolucion,
    acciones_para,
    codigos_de_la_tienda,
)

# Los botones de una incidencia, como se llaman en la pantalla, para la bitácora.
NOMBRES_DE_ACCION = {
    ACEPTAR_PRECIO: "Aceptar el precio nuevo",
    ACEPTAR_CODIGO: "Aceptar el código de la tienda",
    REVISAR: "Volver a revisar ahora",
    CAMBIAR_ENLACE: "Cambiar el enlace",
    DESCARTAR: "Descartar",
}

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
    nombres = (
        incidencias.exclude(store_name="")
        .order_by()
        .values_list("store_name", flat=True)
        .distinct()
    )
    for nombre in nombres:
        comercios.setdefault(nombre.strip(), []).append(nombre)
    return dict(
        sorted(comercios.items(), key=lambda comercio: comercio[0].casefold())
    )


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

    pendiente = Q(kind__in=REGISTROS[FALLIDAS], status=Incident.Status.PENDING)
    totales = Incident.objects.aggregate(
        fallidas=Count("pk", filter=pendiente),
        excluidos=Count("pk", filter=Q(kind__in=REGISTROS[EXCLUIDOS])),
        fallidas_hoy=Count(
            "pk", filter=pendiente & Q(created_at__gte=inicio_de_hoy())
        ),
        excluidos_mes=Count(
            "pk",
            filter=Q(
                kind__in=REGISTROS[EXCLUIDOS], created_at__gte=inicio_del_mes()
            ),
        ),
        sospechosos=Count(
            "pk", filter=pendiente & Q(kind=Incident.Kind.SUSPICIOUS_PRICE)
        ),
        codigos_distintos=Count(
            "pk", filter=pendiente & Q(kind=Incident.Kind.BARCODE_MISMATCH)
        ),
        resueltas_mes=Count(
            "pk",
            filter=Q(
                kind__in=REGISTROS[FALLIDAS],
                status=Incident.Status.RESOLVED,
                resolved_at__gte=inicio_del_mes(),
            ),
        ),
    )
    comercios_afectados = len(
        comercios_del_registro(Incident.objects.filter(pendiente))
    )
    por_tipo = dict(
        del_registro.order_by().values_list("kind").annotate(total=Count("pk"))
    )
    comercios = comercios_del_registro(del_registro)

    busqueda = request.GET.get("q", "").strip()
    comercio = request.GET.get("comercio", "")
    tipo = request.GET.get("tipo", "")
    periodo = request.GET.get("periodo", "")

    lista = del_registro.select_related("resolved_by")
    if busqueda:
        lista = lista.filter(
            Q(product_name__icontains=busqueda)
            | Q(gtin__icontains=busqueda)
            | Q(reason__icontains=busqueda)
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
        lista = lista.filter(
            created_at__gte=timezone.now() - PERIODOS[periodo][1]
        )
    else:
        periodo = ""

    pagina = Paginator(
        lista.order_by("-created_at", "-pk"), INCIDENCIAS_POR_PAGINA
    ).get_page(request.GET.get("pagina"))
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
            "tipos": [
                (t.value, t.label, por_tipo.get(t.value, 0))
                for t in REGISTROS[FALLIDAS]
            ],
            "estado": estado,
            "periodo": periodo,
            "periodos": [
                (clave, nombre) for clave, (nombre, _) in PERIODOS.items()
            ],
            "hay_filtros": bool(
                busqueda or comercio or tipo or periodo or estado
            ),
            "kpis": tarjetas_de_incidencias(totales, comercios_afectados),
            "pestanas": pestanas(
                reverse("incidencias"),
                "registro",
                [
                    (FALLIDAS, "Extracciones fallidas", totales["fallidas"]),
                    (EXCLUIDOS, "Productos excluidos", totales["excluidos"]),
                ],
                registro,
            ),
            "total_texto": plural(
                pagina.paginator.count, "incidencia", "incidencias"
            ),
        },
    )


def tarjetas_de_incidencias(totales, comercios_afectados):
    """Las tarjetas de arriba de la tabla (frontend/html/admin-panel-moderacion.html)."""
    return [
        indicador(
            "Extracciones fallidas",
            totales["fallidas"],
            unidad="pendientes",
            insignia=f"+{totales['fallidas_hoy']} hoy",
            tono="alerta" if totales["fallidas_hoy"] else "",
            icono="arrow_upward" if totales["fallidas_hoy"] else "",
            pie_izq=plural(
                comercios_afectados, "comercio afectado", "comercios afectados"
            ),
            destacada=True,
        ),
        indicador(
            "Precios por confirmar",
            totales["sospechosos"] + totales["codigos_distintos"],
            pie_izq=plural(
                totales["sospechosos"],
                "cambio sospechoso",
                "cambios sospechosos",
            ),
            pie_der=plural(
                totales["codigos_distintos"],
                "código distinto",
                "códigos distintos",
            ),
        ),
        indicador(
            "Productos excluidos",
            totales["excluidos"],
            insignia="Automático",
            pie_izq="Sin código de barras válido",
            pie_der=f"+{totales['excluidos_mes']} este mes",
        ),
        indicador(
            "Resueltas este mes",
            totales["resueltas_mes"],
            insignia="Desde el panel",
            tono="bien",
            icono="check_circle",
            pie_izq="Extracciones fallidas",
        ),
    ]


def _volver(request):
    """La lista de donde vino el administrador, con sus filtros y su página."""
    volver = request.POST.get("volver", "")
    if volver.startswith(
        reverse("incidencias")
    ) and url_has_allowed_host_and_scheme(
        volver,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return volver
    return reverse("incidencias")


@role_required(User.Role.ADMIN)
@require_POST
def resolver_incidencia(request, pk):
    """Los botones de una extracción fallida: aceptar el precio o el código, cambiar el enlace..."""
    incidencia = get_object_or_404(
        Incident, pk=pk, kind__in=EXTRACCION_FALLIDA
    )
    accion = request.POST.get("accion", "")
    url = request.POST.get("url", "")
    try:
        resultado = Resolucion(incidencia, request.user).ejecutar(
            accion, url=url
        )
    except NoSePuedeResolver as error:
        messages.error(request, str(error))
    else:
        detalles = {
            "Tipo": incidencia.get_kind_display(),
            "Acción elegida": NOMBRES_DE_ACCION.get(accion, accion),
            "Resultado": resultado.mensaje,
        }
        if accion == CAMBIAR_ENLACE:
            detalles["Enlace nuevo"] = url
        if resultado.repetidas:
            detalles["Incidencias repetidas resueltas"] = resultado.repetidas
        registrar(
            request.user,
            Accion.INCIDENT_RESOLVE,
            incidencia.pk,
            " — ".join(
                parte
                for parte in (
                    incidencia.product_name or incidencia.gtin,
                    incidencia.store_name,
                )
                if parte
            )
            or f"Incidencia {incidencia.pk}",
            detalles,
        )
        (messages.success if resultado.exito else messages.warning)(
            request, resultado.mensaje
        )
        if resultado.repetidas == 1:
            messages.info(
                request,
                "También se resolvió 1 incidencia repetida del mismo precio.",
            )
        elif resultado.repetidas:
            messages.info(
                request,
                f"También se resolvieron {resultado.repetidas} incidencias repetidas del mismo precio.",
            )
    return redirect(_volver(request))


# --- Ejecución manual de la obtención de datos ---


@role_required(User.Role.ADMIN)
def obtencion_de_datos(request):
    """Los comercios que usan web scraping, para actualizarlos sin esperar a la corrida de cada hora."""
    ejecucion_manual.marcar_interrumpidas()
    github_al_dia = ejecucion_manual.sincronizar_con_github()
    comercios = ejecucion_manual.comercios_con_scraping()
    ejecuciones = list(ejecucion_manual.ultimas_ejecuciones())
    activas = {}
    for ejecucion in ManualRun.objects.filter(
        status__in=ManualRun.ACTIVE
    ).order_by("created_at"):
        activas[ejecucion.store_name] = ejecucion
    for comercio in comercios:
        comercio["en_curso"] = activas.get(comercio["nombre"])

    precios = sum(comercio["precios"] for comercio in comercios)
    desactualizados = sum(
        comercio["desactualizados"] for comercio in comercios
    )
    revisiones = [
        comercio["ultima_revision"]
        for comercio in comercios
        if comercio["ultima_revision"]
    ]
    hace = (
        duracion_aproximada(timezone.now() - max(revisiones))
        if revisiones
        else ("—", "")
    )
    hoy = ManualRun.objects.filter(created_at__gte=inicio_de_hoy()).count()
    opciones = ejecucion_manual.opciones_disponibles()
    return render(
        request,
        "ingestion/obtencion.html",
        {
            "comercios": comercios,
            "ejecuciones": ejecuciones,
            "hay_en_curso": bool(activas),
            "github_al_dia": github_al_dia,
            "en_el_servidor": opciones[ManualRun.Runner.SERVER],
            "en_github": opciones[ManualRun.Runner.GITHUB],
            "url_del_workflow": (
                f"https://github.com/{settings.GITHUB_REPOSITORIO}/actions/workflows/{settings.GITHUB_WORKFLOW_PRECIOS}"
                if settings.GITHUB_REPOSITORIO
                else ""
            ),
            "minutos": ejecucion_manual.MINUTOS,
            "minutos_por_defecto": ejecucion_manual.MINUTOS_POR_DEFECTO,
            "kpis": [
                indicador(
                    "Comercios con web scraping",
                    len(comercios),
                    pie_izq=plural(
                        precios,
                        "precio que se revisa",
                        "precios que se revisan",
                    ),
                    destacada=True,
                ),
                indicador(
                    "Desde la última revisión",
                    hace[0],
                    unidad=hace[1],
                    insignia="Cada hora",
                    tono="bien",
                    icono="schedule",
                    pie_izq="Actualización programada en GitHub Actions",
                ),
                indicador(
                    "Precios desactualizados",
                    desactualizados,
                    insignia=f"Más de {ejecucion_manual.HORAS_DESACTUALIZADO} h",
                    tono="alerta" if desactualizados else "",
                    pie_izq="Sin revisar en su tienda",
                ),
                indicador(
                    "Ejecuciones manuales hoy",
                    hoy,
                    insignia=f"{len(activas)} en curso" if activas else "",
                    tono="marca",
                    pie_izq="Pedidas desde este panel",
                ),
            ],
        },
    )


@role_required(User.Role.ADMIN)
@require_POST
def ejecutar_obtencion(request):
    """El botón «Ejecutar ahora» de un comercio: en el servidor o en GitHub Actions."""
    try:
        ejecucion = ejecucion_manual.solicitar(
            request.POST.get("comercio"),
            request.POST.get("donde"),
            request.user,
            minutos=request.POST.get("minutos"),
            todos=request.POST.get("todos") == "on",
            prueba=request.POST.get("prueba") == "on",
        )
    except ejecucion_manual.NoSePuedeEjecutar as error:
        messages.error(request, str(error))
    else:
        registrar(
            request.user,
            Accion.DATA_RUN_REQUEST,
            ejecucion.pk,
            ejecucion.store_name,
            {
                "Dónde": ejecucion.get_runner_display(),
                "Minutos como máximo": ejecucion.minutes,
                "Todos los precios": ejecucion.all_prices,
                "Modo de prueba": ejecucion.dry_run,
            },
            comercio=ejecucion.store_id,
        )
        if ejecucion.runner == ManualRun.Runner.SERVER:
            messages.success(
                request,
                f"Empezó la obtención de datos de {ejecucion.store_name} en el servidor.",
            )
        else:
            messages.success(
                request,
                f"Se pidió a GitHub Actions la obtención de datos de {ejecucion.store_name}; "
                "puede tardar un par de minutos en empezar.",
            )
    return redirect("obtencion_de_datos")
