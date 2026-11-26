"""Rutas HTTP de la aplicación ingestion."""

from django.urls import path

from . import views

urlpatterns = [
    path("incidencias/", views.incidencias, name="incidencias"),
    path(
        "incidencias/<int:pk>/resolver/",
        views.resolver_incidencia,
        name="resolver_incidencia",
    ),
    path("obtencion/", views.obtencion_de_datos, name="obtencion_de_datos"),
    path(
        "obtencion/ejecutar/",
        views.ejecutar_obtencion,
        name="ejecutar_obtencion",
    ),
]
