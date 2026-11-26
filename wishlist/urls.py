"""Rutas HTTP de la aplicación wishlist."""

from django.urls import path

from . import views

app_name = "wishlist"

urlpatterns = [
    path("", views.lista_deseos, name="lista"),
    path("<int:pk>/agregar/", views.agregar_a_lista_deseos, name="agregar"),
    path(
        "<int:pk>/eliminar/", views.eliminar_de_lista_deseos, name="eliminar"
    ),
]
