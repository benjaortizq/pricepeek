"""Rutas HTTP de la aplicación products."""

from django.urls import path

from . import administracion, views

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
    path(
        "imagenes/<path:nombre>",
        administracion.imagen_de_producto,
        name="imagen_de_producto",
    ),
]
