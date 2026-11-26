"""Vistas HTTP de la aplicación auditoria."""

from collections import Counter

from django.core.paginator import Paginator
from django.db.models import Count, Min, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import User
from core.panel import (
    indicador,
    inicio_de_hoy,
    inicio_del_mes,
    pestanas,
    plural,
)

from .models import AuditLog

REGISTROS_POR_PAGINA = 25
Target = AuditLog.Target
# Las pestañas de la tabla: el tipo de elemento afectado.
PESTANAS = [
    (Target.CLIENT, "Clientes"),
    (Target.STORE, "Comercios"),
    (Target.ENTERPRISE_ACCOUNT, "Cuentas de empresa"),
    (Target.PRODUCT, "Productos"),
    (Target.REVIEW, "Reseñas"),
    (Target.INCIDENT, "Incidencias"),
    (Target.DATA_RUN, "Obtención de datos"),
]


@role_required(User.Role.ADMIN)
def bitacora(request):
    """Las acciones de los administradores, de la más reciente a la más antigua."""
    busqueda = request.GET.get("q", "").strip()
    tipo = request.GET.get("tipo", "")
    if tipo not in Target.values:
        tipo = ""
    registros = AuditLog.objects.select_related("user")
    if tipo:
        # El tipo de elemento es el prefijo de la acción («cliente.suspender»).
        registros = registros.filter(action__startswith=f"{tipo}.")
    if busqueda:
        registros = registros.filter(
            Q(user__email__icontains=busqueda)
            | Q(target_name__icontains=busqueda)
        )
    pagina = Paginator(registros, REGISTROS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )

    # Pocas consultas: con Supabase cada una tarda unos 80 ms.
    resumen = AuditLog.objects.aggregate(
        total=Count("pk"),
        hoy=Count("pk", filter=Q(created_at__gte=inicio_de_hoy())),
        mes=Count("pk", filter=Q(created_at__gte=inicio_del_mes())),
        administradores=Count("user", distinct=True),
        desde=Min("created_at"),
    )
    por_tipo = Counter()
    for accion, total in (
        AuditLog.objects.order_by()
        .values_list("action")
        .annotate(total=Count("pk"))
    ):
        por_tipo[accion.split(".", 1)[0]] += total
    desde = resumen["desde"]
    return render(
        request,
        "auditoria/bitacora.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "tipo": tipo,
            "kpis": [
                indicador(
                    "Acciones registradas",
                    resumen["total"],
                    pie_izq=(
                        f"Desde el {timezone.localtime(desde):%d/%m/%Y}"
                        if desde
                        else "Todavía no hay acciones"
                    ),
                    destacada=True,
                ),
                indicador(
                    "Acciones de hoy",
                    resumen["hoy"],
                    pie_izq=plural(
                        resumen["mes"],
                        "acción este mes",
                        "acciones este mes",
                    ),
                ),
                indicador(
                    "Administradores",
                    resumen["administradores"],
                    pie_izq="Con acciones registradas",
                ),
                indicador(
                    "Conservación",
                    12,
                    unidad="meses",
                    insignia="Mínimo",
                    tono="bien",
                    icono="lock",
                    pie_izq="Los registros no se modifican",
                ),
            ],
            "pestanas": pestanas(
                reverse("bitacora"),
                "tipo",
                [("", "Todas las acciones", resumen["total"])]
                + [
                    (valor, texto, por_tipo.get(valor, 0))
                    for valor, texto in PESTANAS
                ],
                tipo,
                conservar={"q": busqueda},
            ),
            "total_texto": plural(
                pagina.paginator.count, "registro", "registros"
            ),
        },
    )
