"""Rutas HTTP de la aplicación products."""

from django.urls import path

from . import administracion, views, vistas_historial

urlpatterns = [
    path("comparar/", views.comparar_precios, name="comparar_precios"),
    path("filtros/", views.filtros_productos, name="filtros_productos"),
    path("buscar/", views.buscar, name="buscar_productos"),
    path("marca/<slug:slug>/", views.detalle_marca, name="detalle_marca"),
    path("<int:pk>/", views.detalle_producto, name="detalle_producto"),
    # Panel de administración: los datos generales de cada producto.
    path(
        "catalogo/",
        administracion.catalogo_de_productos,
        name="catalogo_de_productos",
    ),
    path(
        "catalogo/<int:pk>/editar/",
        administracion.editar_producto,
        name="editar_producto",
    ),
    # Panel de administración: el historial de precios de las tiendas.
    path(
        "historial/",
        vistas_historial.historial_de_precios,
        name="historial_de_precios",
    ),
    path(
        "historial/<str:gtin>/",
        vistas_historial.historial_de_presentacion,
        name="historial_de_presentacion",
    ),
    path(
        "imagenes/<path:nombre>",
        administracion.imagen_de_producto,
        name="imagen_de_producto",
    ),
]
