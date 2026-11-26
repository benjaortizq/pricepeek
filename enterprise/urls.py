"""Rutas del portal de empresas."""

from django.urls import path

from . import views

app_name = "enterprise"

urlpatterns = [
    path("panel/", views.panel, name="panel"),
    path("tienda/editar/", views.editar_tienda, name="editar_tienda"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo/nuevo/", views.nuevo_producto, name="nuevo_producto"),
    path("catalogo/gtin-existe/", views.comprobar_gtin, name="comprobar_gtin"),
    path("catalogo/cargar/", views.cargar_csv, name="cargar_csv"),
    path("catalogo/plantilla.csv/", views.plantilla_csv, name="plantilla_csv"),
    path(
        "catalogo/<int:price_id>/",
        views.detalle_producto,
        name="detalle_producto",
    ),
    path(
        "catalogo/<int:price_id>/editar/",
        views.editar_producto,
        name="editar_producto",
    ),
    path(
        "catalogo/<int:price_id>/eliminar/",
        views.eliminar_producto,
        name="eliminar_producto",
    ),
    path(
        "catalogo/<int:price_id>/desactivar/",
        views.desactivar_producto,
        name="desactivar_producto",
    ),
    path("reporte.pdf", views.reporte_pdf, name="reporte_pdf"),
]
