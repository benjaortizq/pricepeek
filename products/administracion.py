"""El catálogo de productos en el panel de administración y la edición de sus datos generales.

Issue «Edición de datos generales de productos». Los productos son lo que maneja PricePeek
(nombre, marca, categoría, descripción e imagen); los precios son lo que ofrece cada tienda y
se manejan en el portal de empresas (enterprise/).
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.decorators import role_required
from accounts.models import User
from core.panel import indicador, pestanas, plural
from core.translations import translate_text

from .busqueda import con_imagen
from .edicion import (
    CARPETA_DE_IMAGENES,
    NOMBRE_DE_IMAGEN,
    editar_producto as guardar_edicion,
    imagen_actual,
)
from .forms import EditarProductoForm
from .models import (
    Brands,
    Categories,
    PartnerStore,
    Prices,
    ProductImages,
    Products,
    ProductVariants,
)

PRODUCTOS_POR_PAGINA = 20

SIN_IMAGEN = ~Exists(
    ProductImages.objects.filter(variant__product_id=OuterRef("pk"))
)
SIN_DESCRIPCION = Q(description__isnull=True) | Q(description="")
SIN_PRECIOS = ~Exists(Prices.objects.filter(gtin__product_id=OuterRef("pk")))
FILTROS = {
    "sin-imagen": SIN_IMAGEN,
    "sin-descripcion": SIN_DESCRIPCION,
    "sin-precios": SIN_PRECIOS,
}


@role_required(User.Role.ADMIN)
def catalogo_de_productos(request):
    busqueda = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    if estado not in FILTROS:
        estado = ""
    categorias = list(Categories.objects.order_by("name"))
    categoria = request.GET.get("categoria", "")
    if categoria not in {str(c.pk) for c in categorias}:
        categoria = ""

    lista = Products.objects.select_related("brand", "category")
    if busqueda:
        lista = lista.filter(
            Q(name__icontains=busqueda)
            | Q(brand__name__icontains=busqueda)
            | Q(
                pk__in=ProductVariants.objects.filter(
                    gtin__icontains=busqueda
                ).values("product_id")
            )
        )
    if categoria:
        lista = lista.filter(category_id=categoria)
    if estado:
        lista = lista.filter(FILTROS[estado])
    lista = lista.annotate(
        tiendas=Count("productvariants__prices__id_store", distinct=True),
        presentaciones=Count("productvariants", distinct=True),
    ).order_by("name", "id")
    pagina = Paginator(lista, PRODUCTOS_POR_PAGINA).get_page(
        request.GET.get("pagina")
    )
    con_imagen(pagina.object_list)
    codigos = {}
    for producto_id, gtin in (
        ProductVariants.objects.filter(
            product_id__in=[producto.pk for producto in pagina.object_list]
        )
        .order_by("id")
        .values_list("product_id", "gtin")
    ):
        codigos.setdefault(producto_id, []).append(gtin)
    for producto in pagina.object_list:
        producto.codigos = codigos.get(producto.pk, [])

    total = Products.objects.count()
    sin_imagen = Products.objects.filter(SIN_IMAGEN).count()
    sin_descripcion = Products.objects.filter(SIN_DESCRIPCION).count()
    sin_precios = Products.objects.filter(SIN_PRECIOS).count()
    return render(
        request,
        "products/catalogo_admin.html",
        {
            "pagina": pagina,
            "busqueda": busqueda,
            "estado": estado,
            "categorias": categorias,
            "categoria": categoria,
            # Para que «Volver al catálogo» regrese a esta misma página, con sus filtros.
            "consulta_volver": urlencode({"volver": request.get_full_path()}),
            "kpis": [
                indicador(
                    "Productos en el catálogo",
                    total,
                    pie_izq=f"{plural(Brands.objects.count(), 'marca', 'marcas')} · {plural(len(categorias), 'categoría', 'categorías')}",
                    destacada=True,
                ),
                indicador(
                    "Sin imagen",
                    sin_imagen,
                    insignia="Por completar" if sin_imagen else "",
                    tono="alerta",
                    icono="hide_image",
                    pie_izq="Ninguna presentación tiene foto",
                ),
                indicador(
                    "Sin descripción",
                    sin_descripcion,
                    pie_izq="El detalle dice «Sin descripción.»",
                ),
                indicador(
                    "Sin precio en ninguna tienda",
                    sin_precios,
                    pie_izq="Ninguna tienda lo ofrece",
                ),
            ],
            "pestanas": pestanas(
                reverse("catalogo_de_productos"),
                "estado",
                [
                    ("", "Todos los productos", total),
                    ("sin-imagen", "Sin imagen", sin_imagen),
                    ("sin-descripcion", "Sin descripción", sin_descripcion),
                    ("sin-precios", "Sin precio", sin_precios),
                ],
                estado,
                conservar={"q": busqueda, "categoria": categoria},
            ),
            "total_texto": plural(
                pagina.paginator.count, "producto", "productos"
            ),
        },
    )


def _mensaje_de_cambios(cambios, tiendas):
    """«Se guardaron los cambios del producto (el nombre, la imagen). Se ven igual en las 3 tiendas…»"""
    guardado = translate_text(
        "Se guardaron los cambios del producto ({cambios}).",
        cambios=", ".join(translate_text(cambio) for cambio in cambios),
    )
    if tiendas == 1:
        alcance = translate_text("Se ven en la tienda que lo ofrece.")
    elif tiendas:
        alcance = translate_text(
            "Se ven igual en las {n} tiendas que lo ofrecen.", n=tiendas
        )
    else:
        alcance = translate_text("Todavía ninguna tienda lo ofrece.")
    return f"{guardado} {alcance}"


def _volver(request):
    """La lista de donde vino el administrador, con sus filtros y su página."""
    volver = request.POST.get("volver") or request.GET.get("volver", "")
    if volver.startswith(
        reverse("catalogo_de_productos")
    ) and url_has_allowed_host_and_scheme(
        volver,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return volver
    return reverse("catalogo_de_productos")


@role_required(User.Role.ADMIN)
def editar_producto(request, pk):
    producto = get_object_or_404(
        Products.objects.select_related("brand", "category"), pk=pk
    )
    presentaciones = list(
        ProductVariants.objects.filter(product_id=producto.pk).order_by("id")
    )
    volver = _volver(request)
    if request.method == "POST":
        form = EditarProductoForm(
            request.POST,
            request.FILES,
            producto=producto,
            tiene_presentaciones=bool(presentaciones),
        )
        if form.is_valid():
            datos = form.cleaned_data
            edicion = guardar_edicion(
                producto,
                nombre=datos["name"],
                marca=datos["brand"],
                categoria=datos["category"],
                descripcion=datos["description"],
                imagen=datos["image"],
                imagen_url=datos["image_url"],
            )
            if edicion.cambios:
                tiendas = (
                    Prices.objects.filter(gtin__product_id=producto.pk)
                    .values("id_store")
                    .distinct()
                    .count()
                )
                messages.success(
                    request, _mensaje_de_cambios(edicion.cambios, tiendas)
                )
                if edicion.marca_nueva:
                    messages.info(
                        request,
                        translate_text(
                            "Se creó la marca «{marca}» en el catálogo.",
                            marca=producto.brand.name,
                        ),
                    )
            else:
                messages.info(
                    request, translate_text("No había cambios que guardar.")
                )
            destino = reverse("editar_producto", args=[producto.pk])
            if volver != reverse("catalogo_de_productos"):
                destino += "?" + urlencode({"volver": volver})
            return redirect(destino)
    else:
        form = EditarProductoForm(
            producto=producto, tiene_presentaciones=bool(presentaciones)
        )

    precios = list(
        Prices.objects.filter(gtin__product_id=producto.pk)
        .select_related("id_store", "gtin")
        .order_by("id_store__name", "gtin_id")
    )
    tiendas = {}
    for precio in precios:
        tiendas.setdefault(precio.id_store_id, precio)
    return render(
        request,
        "products/editar_producto.html",
        {
            "producto": producto,
            "form": form,
            "presentaciones": presentaciones,
            "precios": precios,
            "cantidad_tiendas": len(tiendas),
            # Los comercios desactivados tienen precio, pero no se muestra (products/comercios.py).
            "desactivados": set(
                PartnerStore.objects.filter(is_active=False).values_list(
                    "store_id", flat=True
                )
            ),
            "imagen": imagen_actual(producto),
            "marcas": Brands.objects.order_by("name").values_list(
                "name", flat=True
            ),
            "volver": volver,
        },
    )


def imagen_de_producto(request, nombre):
    """Redirige a la imagen que subió un administrador (ver products/edicion.py).

    En Supabase Storage el enlace va firmado y vence en una hora: por eso en product_images queda
    este enlace, que no vence, y aquí se pide uno vigente cada vez.
    """
    if not NOMBRE_DE_IMAGEN.fullmatch(nombre):
        raise Http404
    respuesta = redirect(default_storage.url(CARPETA_DE_IMAGENES + nombre))
    # Menos que lo que dura el enlace firmado (una hora), para que el navegador no use uno vencido.
    patch_cache_control(respuesta, private=True, max_age=1800)
    return respuesta
