from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from accounts.views import INFRACCIONES_REITERADAS
from core.panel import indicador, pestanas, plural
from products.models import Products
from .eliminacion import NoSePuedeEliminar, infracciones_por_autor
from .eliminacion import eliminar_resena as eliminar_por_politicas  # eliminar_resena es la vista del autor
from .forms import EliminarResenaForm, ModerationForm, ReviewForm, ReviewReportForm
from .indicadores import resumen_de_moderacion
from .models import ReviewDeletion, ReviewPhoto, ReviewReport, Reviews

RESENAS_POR_PAGINA = 10


def _delete_review_photo(photo):
    if not photo:
        return
    filename = photo.image.name
    if filename:
        photo.image.storage.delete(filename)
    photo.delete()


def _owned_review(request, pk):
    if not request.user.is_authenticated or request.user.role != "client":
        raise PermissionDenied
    return get_object_or_404(Reviews.objects.select_related("variant"), pk=pk, user_id=request.user.pk)


@login_required
def editar_resena(request, pk):
    resena = _owned_review(request, pk)
    producto_id = resena.variant.product_id
    foto = ReviewPhoto.objects.filter(review_id=resena.pk).first()
    if request.method == "POST":
        form = ReviewForm(request.POST, request.FILES)
        if form.is_valid():
            resena.content = form.cleaned_data["content"]
            resena.score = form.cleaned_data["rating"]
            resena.updated_at = timezone.now()
            resena.save(update_fields=["content", "score", "updated_at"])
            nueva_foto = form.cleaned_data["photo"]
            if nueva_foto:
                if foto:
                    _delete_review_photo(foto)
                foto = ReviewPhoto(review_id=resena.pk)
                foto.image.save(nueva_foto.name, nueva_foto, save=False)
                foto.save()
            elif request.POST.get("remove_photo") == "on" and foto:
                _delete_review_photo(foto)
            return redirect("detalle_producto", pk=producto_id)
    else:
        form = ReviewForm(initial={"rating": resena.score, "content": resena.content})
    producto = get_object_or_404(Products, pk=producto_id)
    return render(
        request,
        "reviews/editar_resena.html",
        {"form": form, "resena": resena, "producto": producto, "foto": foto},
    )


@login_required
def eliminar_resena(request, pk):
    resena = _owned_review(request, pk)
    producto_id = resena.variant.product_id
    if request.method != "POST":
        raise PermissionDenied
    foto = ReviewPhoto.objects.filter(review_id=resena.pk).first()
    if foto:
        _delete_review_photo(foto)
    # Sin la reseña ya no hay nada que moderar: que no queden en la cola del administrador.
    ReviewReport.objects.filter(review_id=resena.pk, status=ReviewReport.Status.PENDING).delete()
    resena.delete()
    return redirect("detalle_producto", pk=producto_id)


def producto_reseñas(request, pk):
    producto = get_object_or_404(Products, pk=pk)
    reviewsProducto = (
        Reviews.objects.select_related("variant")
        .filter(variant__product_id=producto.pk)
        .order_by("-created_at")
    )
    return render(
        request,
        "reviews/producto_reseñas.html",
        {
            "producto": producto,
            "reviews": reviewsProducto,
        },
    )


@role_required(User.Role.CLIENT)
@require_POST
def reportar_resena(request, review_id):
    """El cliente reporta una reseña ajena como inapropiada (RF-28)."""
    resena = get_object_or_404(Reviews.objects.select_related("variant"), pk=review_id)
    destino = redirect("detalle_producto", pk=resena.variant.product_id)

    if resena.user_id == request.user.pk:
        messages.error(request, "No se envió el reporte porque corresponde a su propia reseña. Solo puede reportar reseñas de otras personas.")
        return destino

    form = ReviewReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "No se envió el reporte porque el motivo está vacío o supera los 500 caracteres. Escriba un motivo de hasta 500 caracteres e inténtelo de nuevo.")
        return destino

    _, creado = ReviewReport.objects.get_or_create(
        review_id=resena.pk,
        reporter=request.user,
        defaults={"reason": form.cleaned_data["reason"], "review_author_id": resena.user_id},
    )
    if creado:
        messages.success(request, "Gracias. Su reporte fue enviado y el equipo de PricePeek lo revisará.")
    else:
        messages.info(request, "Esta reseña ya fue reportada por usted; no necesita enviarla de nuevo.")
    return destino


@role_required(User.Role.ADMIN)
def resenas_reportadas(request):
    """Lista de reseñas con reportes pendientes, para que el administrador las revise."""
    pendientes = list(
        ReviewReport.objects.filter(status=ReviewReport.Status.PENDING)
        .select_related("reporter")
        .order_by("created_at")
    )
    resenas = {
        resena.pk: resena
        for resena in Reviews.objects.select_related("variant__product", "user").filter(
            pk__in={reporte.review_id for reporte in pendientes}
        )
    }
    grupos = {}
    for reporte in pendientes:
        resena = resenas.get(reporte.review_id)
        if resena is None:  # la reseña ya no existe (por ejemplo, su autor la borró)
            continue
        grupo = grupos.setdefault(reporte.review_id, {"resena": resena, "reportes": []})
        grupo["reportes"].append(reporte)
    fotos = {foto.review_id: foto for foto in ReviewPhoto.objects.filter(review_id__in=list(grupos))}
    # Reseñas de cada autor que ya se eliminaron antes, para saber si incumple de forma reiterada.
    infracciones = infracciones_por_autor({grupo["resena"].user_id for grupo in grupos.values()})
    for review_id, grupo in grupos.items():
        grupo["foto"] = fotos.get(review_id)
        grupo["infracciones"] = infracciones.get(grupo["resena"].user_id, 0)
        grupo["ultimo_reporte"] = grupo["reportes"][-1].created_at
    grupos = list(grupos.values())

    # Las pestañas de la tabla (frontend/html/admin-resenas-reportadas.html).
    filtros = {
        "": grupos,
        "con-foto": [grupo for grupo in grupos if grupo["foto"]],
        "reiterados": [grupo for grupo in grupos if grupo["infracciones"] >= INFRACCIONES_REITERADAS],
    }
    filtro = request.GET.get("filtro", "")
    if filtro not in filtros:
        filtro = ""
    pagina = Paginator(filtros[filtro], RESENAS_POR_PAGINA).get_page(request.GET.get("pagina"))

    # La que se ve en el panel de inspección: la elegida con «Inspeccionar» o la primera de la página.
    revisar = request.GET.get("revisar", "")
    seleccionado = next((g for g in grupos if str(g["resena"].pk) == revisar), None)
    if seleccionado is None and pagina.object_list:
        seleccionado = pagina.object_list[0]

    return render(
        request,
        "reviews/resenas_reportadas.html",
        {
            "pagina": pagina,
            "grupos": pagina.object_list,
            "seleccionado": seleccionado,
            "filtro": filtro,
            "kpis": tarjetas_de_moderacion(resumen_de_moderacion()),
            "pestanas": pestanas(
                reverse("resenas_reportadas"),
                "filtro",
                [
                    ("", "Todas las reportadas", len(filtros[""])),
                    ("con-foto", "Con foto", len(filtros["con-foto"])),
                    ("reiterados", "Autor reiterado", len(filtros["reiterados"])),
                ],
                filtro,
            ),
            "total_texto": plural(pagina.paginator.count, "reseña reportada", "reseñas reportadas"),
            "reiteradas": INFRACCIONES_REITERADAS,
            "politicas": ReviewDeletion.SELECTABLE,
        },
    )


def tarjetas_de_moderacion(datos):
    """Las tarjetas de arriba de la tabla (frontend/html/admin-resenas-reportadas.html)."""
    tiempo = datos["tiempo_promedio"] or ("—", "")
    tasa = datos["tasa_eliminacion"]
    return [
        indicador(
            "En cola de revisión",
            datos["en_cola"],
            unidad="reseñas" if datos["en_cola"] != 1 else "reseña",
            insignia=f"+{datos['reportes_hoy']} hoy",
            tono="alerta" if datos["reportes_hoy"] else "",
            icono="arrow_upward" if datos["reportes_hoy"] else "",
            pie_izq=plural(datos["reportes_pendientes"], "reporte pendiente", "reportes pendientes"),
            destacada=True,
        ),
        indicador(
            "Tiempo prom. resolución",
            tiempo[0],
            unidad=tiempo[1],
            pie_izq="Últimos 30 días" if datos["tiempo_promedio"] else "Sin datos",
        ),
        indicador(
            "Tasa de eliminación",
            "—" if tasa is None else tasa,
            unidad="" if tasa is None else "%",
            insignia="Últimos 30 días",
            pie_izq=plural(datos["eliminadas_30"], "reseña eliminada", "reseñas eliminadas"),
            pie_der=plural(datos["mantenidas_30"], "reseña mantenida", "reseñas mantenidas"),
        ),
        indicador(
            "Eliminadas este mes",
            datos["eliminadas_mes"],
            unidad="reseñas" if datos["eliminadas_mes"] != 1 else "reseña",
            pie_izq="Por incumplir las políticas",
        ),
    ]


@role_required(User.Role.ADMIN)
@require_POST
def moderar_resena(request, review_id):
    """El administrador mantiene o elimina una reseña reportada (RF-41) y puede suspender al autor (RF-42)."""
    pendientes = ReviewReport.objects.filter(
        review_id=review_id, status=ReviewReport.Status.PENDING
    )
    if not pendientes.exists():
        messages.info(request, "Esta reseña ya no tiene reportes pendientes. Actualice la lista para ver las reseñas que todavía requieren revisión.")
        return redirect("resenas_reportadas")

    form = ModerationForm(request.POST)
    if not form.is_valid():
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
        return redirect("resenas_reportadas")

    nota = form.cleaned_data["note"]
    resena = Reviews.objects.select_related("variant__product", "user").filter(pk=review_id).first()
    if resena is None:
        # Su autor la borró: ya no hay nada que moderar.
        pendientes.delete()
        messages.info(request, "Esa reseña ya no existe; sus reportes salieron de la cola.")
        return redirect("resenas_reportadas")

    if form.cleaned_data["action"] == ModerationForm.DELETE:
        eliminacion = eliminar_por_politicas(
            resena, request.user, form.cleaned_data["policy"], nota, form.cleaned_data["suspend"]
        )
        avisar_eliminacion(request, eliminacion)
        return redirect("resenas_reportadas")

    pendientes.update(
        status=ReviewReport.Status.KEPT,
        resolved_by_id=request.user.pk,
        resolved_at=timezone.now(),
        resolution_note=nota,
        review_author_id=resena.user_id,  # por si el reporte se creó antes de guardar el autor
    )
    messages.success(request, "La reseña se mantiene y los reportes quedaron resueltos.")
    return redirect("resenas_reportadas")


def avisar_eliminacion(request, eliminacion):
    mensaje = "Reseña eliminada."
    if eliminacion.suspendido:
        mensaje += " La cuenta del autor fue suspendida."
    messages.success(request, mensaje)
    if eliminacion.foto_sin_borrar:
        messages.warning(request, "La reseña se eliminó, pero no se pudo borrar su foto del almacenamiento. Avise al equipo de soporte para que elimine el archivo pendiente.")


# --- Todas las reseñas (issue «Eliminación de reseñas») ---

RESENAS_EN_LA_LISTA = 20
VISTAS = ("", "reportadas", "eliminadas")


def _buscar_resenas(resenas, busqueda):
    if not busqueda:
        return resenas
    return resenas.filter(
        Q(content__icontains=busqueda)
        | Q(variant__product__name__icontains=busqueda)
        | Q(variant__name__icontains=busqueda)
        | Q(user__email__icontains=busqueda)
        | Q(user__first_name__icontains=busqueda)
        | Q(user__last_name__icontains=busqueda)
    )


def _buscar_eliminadas(eliminadas, busqueda):
    if not busqueda:
        return eliminadas
    return eliminadas.filter(
        Q(content__icontains=busqueda)
        | Q(product_name__icontains=busqueda)
        | Q(reason__icontains=busqueda)
        | Q(author__email__icontains=busqueda)
    )


@role_required(User.Role.ADMIN)
def todas_las_resenas(request):
    """Todas las reseñas publicadas, para revisarlas y eliminar las que incumplen las políticas,
    y el registro de las eliminadas, con su política y su razón."""
    vista = request.GET.get("vista", "")
    if vista not in VISTAS:
        vista = ""
    busqueda = request.GET.get("q", "").strip()
    calificacion = request.GET.get("calificacion", "")
    if calificacion not in ("1", "2", "3", "4", "5"):
        calificacion = ""

    con_reportes = set(
        ReviewReport.objects.filter(status=ReviewReport.Status.PENDING).values_list("review_id", flat=True)
    )
    resenas = Reviews.objects.select_related("variant__product__brand", "user").order_by("-created_at", "-id")
    resenas = _buscar_resenas(resenas, busqueda)
    eliminadas = _buscar_eliminadas(ReviewDeletion.objects.select_related("author", "deleted_by"), busqueda)
    if calificacion:
        resenas = resenas.filter(score=int(calificacion))
        eliminadas = eliminadas.filter(score=int(calificacion))
    reportadas = resenas.filter(pk__in=con_reportes)

    lista = {"": resenas, "reportadas": reportadas, "eliminadas": eliminadas}[vista]
    pagina = Paginator(lista, RESENAS_EN_LA_LISTA).get_page(request.GET.get("pagina"))
    if vista != "eliminadas":
        ids = [resena.pk for resena in pagina.object_list]
        fotos = {foto.review_id: foto for foto in ReviewPhoto.objects.filter(review_id__in=ids)}
        reportes = dict(
            ReviewReport.objects.filter(status=ReviewReport.Status.PENDING, review_id__in=ids)
            .values("review_id")
            .annotate(total=Count("id"))
            .values_list("review_id", "total")
        )
        primeros = {}
        for review_id, motivo in (
            ReviewReport.objects.filter(status=ReviewReport.Status.PENDING, review_id__in=ids)
            .order_by("created_at")
            .values_list("review_id", "reason")
        ):
            primeros.setdefault(review_id, motivo)
        infracciones = infracciones_por_autor({resena.user_id for resena in pagina.object_list})
        for resena in pagina.object_list:
            resena.foto = fotos.get(resena.pk)
            resena.reportes = reportes.get(resena.pk, 0)
            resena.primer_reporte = primeros.get(resena.pk, "")
            resena.infracciones = infracciones.get(resena.user_id, 0)

    total = Reviews.objects.count()
    promedio = Reviews.objects.aggregate(promedio=Avg("score"))["promedio"]
    moderacion = resumen_de_moderacion()
    total_eliminadas = ReviewDeletion.objects.count()
    conservar = {"q": busqueda, "calificacion": calificacion}
    return render(
        request,
        "reviews/todas_las_resenas.html",
        {
            "vista": vista,
            "pagina": pagina,
            "busqueda": busqueda,
            "calificacion": calificacion,
            "hay_filtros": bool(busqueda or calificacion),
            "politicas": ReviewDeletion.SELECTABLE,
            "reiteradas": INFRACCIONES_REITERADAS,
            "total_texto": (
                plural(pagina.paginator.count, "reseña eliminada", "reseñas eliminadas")
                if vista == "eliminadas"
                else plural(pagina.paginator.count, "reseña encontrada", "reseñas encontradas")
            ),
            "kpis": [
                indicador(
                    "Reseñas publicadas",
                    total,
                    insignia=f"Promedio {promedio:.1f} ★" if promedio is not None else "",
                    tono="marca",
                    pie_izq="De todos los clientes",
                    destacada=True,
                ),
                indicador(
                    "Con reportes pendientes",
                    moderacion["en_cola"],
                    insignia=f"+{moderacion['reportes_hoy']} hoy" if moderacion["reportes_hoy"] else "",
                    tono="alerta",
                    icono="arrow_upward",
                    pie_izq="En la cola de revisión",
                ),
                indicador("Eliminadas este mes", moderacion["eliminadas_mes"], pie_izq="Por incumplir las políticas"),
                indicador(
                    "Eliminadas en total",
                    total_eliminadas,
                    insignia="Con su razón",
                    tono="bien",
                    icono="history",
                    pie_izq="Registro de eliminaciones",
                ),
            ],
            "pestanas": pestanas(
                reverse("todas_las_resenas"),
                "vista",
                [
                    ("", "Publicadas", resenas.count()),
                    ("reportadas", "Con reportes pendientes", reportadas.count()),
                    ("eliminadas", "Eliminadas", eliminadas.count()),
                ],
                vista,
                conservar=conservar,
            ),
        },
    )


def _volver_a_la_lista(request):
    volver = request.POST.get("volver", "")
    if volver.startswith(reverse("todas_las_resenas")) and url_has_allowed_host_and_scheme(
        volver, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return volver
    return reverse("todas_las_resenas")


@role_required(User.Role.ADMIN)
@require_POST
def eliminar_por_incumplimiento(request, review_id):
    """Elimina una reseña desde «Todas las reseñas»: con la política que incumple y la razón."""
    resena = get_object_or_404(Reviews.objects.select_related("variant__product", "user"), pk=review_id)
    form = EliminarResenaForm(request.POST)
    if not form.is_valid():
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
        return redirect(_volver_a_la_lista(request))
    try:
        eliminacion = eliminar_por_politicas(
            resena,
            request.user,
            form.cleaned_data["policy"],
            form.cleaned_data["note"],
            form.cleaned_data["suspend"],
        )
    except NoSePuedeEliminar as error:
        messages.error(request, str(error))
    else:
        avisar_eliminacion(request, eliminacion)
    return redirect(_volver_a_la_lista(request))
