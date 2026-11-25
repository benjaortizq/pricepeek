"""Vistas del portal de empresas."""

import csv

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import User
from core.translations import translate_text_lazy
from products.models import Brands, Categories, ProductImages

from .access import tienda_del_usuario
from .csv_import import COLUMNAS, ErrorEmpresa as ErrorCSV, procesar_csv
from .forms import (
    CargarCSVForm,
    PrecioEmpresaForm,
    ProductoEmpresaForm,
    TiendaEmpresaForm,
)
from .reports import generar_pdf_empresa
from .selectors import (
    PRODUCTOS_POR_PAGINA,
    catalogo_de_tienda,
    estadisticas_catalogo,
    obtener_precio_de_tienda,
    problemas_de_precio,
)
from .services import (
    ErrorEmpresa,
    actualizar_informacion_tienda_empresa,
    crear_precio_empresa,
    desactivar_precio_empresa,
    editar_precio_empresa,
    quitar_precio_empresa,
)


@role_required(User.Role.ENTERPRISE)
def panel(request):
    store = tienda_del_usuario(request.user)
    estadisticas = estadisticas_catalogo(store)
    return render(
        request,
        "enterprise/panel.html",
        {
            "store": store,
            "estadisticas": estadisticas,
            "stale_price_days": settings.STALE_PRICE_DAYS,
        },
    )


@role_required(User.Role.ENTERPRISE)
def editar_tienda(request):
    store = tienda_del_usuario(request.user)
    if request.method == "POST":
        form = TiendaEmpresaForm(request.POST)
        if form.is_valid():
            actualizar_informacion_tienda_empresa(store, form.cleaned_data)
            messages.success(
                request,
                translate_text_lazy(
                    "La información de la tienda se actualizó correctamente."
                ),
            )
            return redirect("enterprise:panel")
    else:
        form = TiendaEmpresaForm(
            initial={
                "name": (store.name or "").strip(),
                "description": store.description or "",
            }
        )
    return render(
        request,
        "enterprise/tienda_formulario.html",
        {"store": store, "form": form},
    )


@role_required(User.Role.ENTERPRISE)
def catalogo(request):
    store = tienda_del_usuario(request.user)
    parametros = {
        "q": request.GET.get("q", "").strip(),
        "estado": request.GET.get("estado", "").strip(),
        "competitividad": request.GET.get("competitividad", "").strip(),
        "categoria": request.GET.get("categoria", "").strip(),
        "marca": request.GET.get("marca", "").strip(),
        "orden": request.GET.get("orden", "").strip(),
    }
    queryset = catalogo_de_tienda(store, parametros)
    pagina = Paginator(queryset, PRODUCTOS_POR_PAGINA).get_page(request.GET.get("pagina"))
    return render(
        request,
        "enterprise/catalogo.html",
        {
            "store": store,
            "pagina": pagina,
            "parametros": parametros,
            "brands": Brands.objects.order_by("name"),
            "categories": Categories.objects.order_by("name"),
        },
    )


@role_required(User.Role.ENTERPRISE)
def nuevo_producto(request):
    store = tienda_del_usuario(request.user)
    if request.method == "POST":
        form = ProductoEmpresaForm(request.POST)
        if form.is_valid():
            datos = form.cleaned_data
            try:
                precio = crear_precio_empresa(
                    store,
                    datos["gtin"],
                    datos,
                    producto_datos={
                        "product_name": datos.get("product_name"),
                        "variant_name": datos.get("variant_name"),
                        "brand": datos.get("brand"),
                        "category": datos.get("category"),
                        "description": datos.get("description"),
                        "attributes": datos.get("attributes"),
                    },
                )
            except ErrorEmpresa as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    translate_text_lazy(
                        "El producto se agregó al catálogo de su tienda."
                    ),
                )
                return redirect("enterprise:detalle_producto", price_id=precio.pk)
    else:
        form = ProductoEmpresaForm()
    return render(
        request,
        "enterprise/producto_formulario.html",
        {
            "store": store,
            "form": form,
            "modo": "nuevo",
            "campos_producto": [
                form["gtin"],
                form["product_name"],
                form["variant_name"],
                form["brand"],
                form["category"],
                form["description"],
                form["attributes"],
            ],
            "campos_precio": [
                form["price"],
                form["discount"],
                form["product_web_url"],
            ],
        },
    )


@role_required(User.Role.ENTERPRISE)
def editar_producto(request, price_id):
    store = tienda_del_usuario(request.user)
    precio = obtener_precio_de_tienda(store, price_id)
    if precio is None:
        return render(
            request,
            "enterprise/no_encontrado.html",
            {"store": store},
            status=404,
        )

    if request.method == "POST":
        form = PrecioEmpresaForm(request.POST)
        if form.is_valid():
            try:
                editar_precio_empresa(store, price_id, form.cleaned_data)
            except ErrorEmpresa as error:
                messages.error(request, str(error))
            else:
                if form.cleaned_data.get("precio_invalido"):
                    messages.warning(
                        request,
                        translate_text_lazy(
                            "El precio se quitó y el producto se marcó como no disponible."
                        ),
                    )
                else:
                    messages.success(
                        request,
                        translate_text_lazy("El precio se actualizó correctamente."),
                    )
                return redirect("enterprise:detalle_producto", price_id=price_id)
    else:
        form = PrecioEmpresaForm(
            initial={
                "price": precio.price,
                "discount": precio.discount,
                "is_available": precio.is_available,
                "product_web_url": precio.product_web_url,
            }
        )
    return render(
        request,
        "enterprise/producto_formulario.html",
        {
            "store": store,
            "form": form,
            "precio": precio,
            "modo": "editar",
            "campos_producto": [],
            "campos_precio": [
                form["price"],
                form["discount"],
                form["product_web_url"],
            ],
        },
    )


@role_required(User.Role.ENTERPRISE)
def detalle_producto(request, price_id):
    store = tienda_del_usuario(request.user)
    precio = obtener_precio_de_tienda(store, price_id)
    if precio is None:
        return render(
            request,
            "enterprise/no_encontrado.html",
            {"store": store},
            status=404,
        )
    imagen = ProductImages.objects.filter(
        variant=precio.gtin,
        is_main=True,
    ).first()
    return render(
        request,
        "enterprise/producto_detalle.html",
        {
            "store": store,
            "precio": precio,
            "imagen": imagen,
            "problemas": problemas_de_precio(precio),
        },
    )


@role_required(User.Role.ENTERPRISE)
def eliminar_producto(request, price_id):
    store = tienda_del_usuario(request.user)
    precio = obtener_precio_de_tienda(store, price_id)
    if precio is None:
        return render(
            request,
            "enterprise/no_encontrado.html",
            {"store": store},
            status=404,
        )
    if request.method == "POST":
        try:
            quitar_precio_empresa(store, price_id)
        except ErrorEmpresa as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                translate_text_lazy(
                    "El precio se quitó y el producto se marcó como no disponible."
                ),
            )
            return redirect("enterprise:detalle_producto", price_id=price_id)
    return render(
        request,
        "enterprise/confirmar_accion.html",
        {
            "store": store,
            "precio": precio,
            "accion": "eliminar",
            "titulo": translate_text_lazy("Quitar el precio"),
            "descripcion": translate_text_lazy(
                "Se borrará el precio de esta oferta y se marcará como no disponible. "
                "El producto y las variantes compartidas no se eliminarán."
            ),
        },
    )


@role_required(User.Role.ENTERPRISE)
def desactivar_producto(request, price_id):
    store = tienda_del_usuario(request.user)
    precio = obtener_precio_de_tienda(store, price_id)
    if precio is None:
        return render(
            request,
            "enterprise/no_encontrado.html",
            {"store": store},
            status=404,
        )
    if request.method == "POST":
        try:
            desactivar_precio_empresa(store, price_id)
        except ErrorEmpresa as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                translate_text_lazy("El producto se marcó como no disponible."),
            )
            return redirect("enterprise:detalle_producto", price_id=price_id)
    return render(
        request,
        "enterprise/confirmar_accion.html",
        {
            "store": store,
            "precio": precio,
            "accion": "desactivar",
            "titulo": translate_text_lazy("Desactivar el producto"),
            "descripcion": translate_text_lazy(
                "El precio y el descuento se conservarán, pero la oferta dejará de estar disponible. "
                "No se modificarán otras tiendas."
            ),
        },
    )


@role_required(User.Role.ENTERPRISE)
def cargar_csv(request):
    store = tienda_del_usuario(request.user)
    resultados = None
    if request.method == "POST":
        form = CargarCSVForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                resultados = procesar_csv(form.cleaned_data["archivo"], store)
            except ErrorCSV as error:
                messages.error(request, str(error))
            else:
                importados = sum(1 for resultado in resultados if resultado.importado)
                errores = len(resultados) - importados
                messages.success(
                    request,
                    translate_text_lazy(
                        "Se importaron {importados} filas y se rechazaron {errores} filas."
                    ).format(importados=importados, errores=errores),
                )
    else:
        form = CargarCSVForm()
    return render(
        request,
        "enterprise/cargar_csv.html",
        {
            "store": store,
            "form": form,
            "resultados": resultados,
            "columnas": COLUMNAS,
        },
    )


@role_required(User.Role.ENTERPRISE)
def plantilla_csv(request):
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = 'attachment; filename="plantilla_productos.csv"'
    writer = csv.writer(respuesta)
    writer.writerow(COLUMNAS)
    return respuesta


@role_required(User.Role.ENTERPRISE)
@require_POST
def reporte_pdf(request):
    store = tienda_del_usuario(request.user)
    pdf = generar_pdf_empresa(store)
    respuesta = HttpResponse(pdf, content_type="application/pdf")
    nombre = slugify(store.name) or "empresa"
    respuesta["Content-Disposition"] = f'attachment; filename="reporte-{nombre}.pdf"'
    return respuesta
