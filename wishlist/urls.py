from django.urls import path

from . import views

app_name = "wishlist"

urlpatterns = [
    path("", views.lista_deseos, name="lista"),
    path("<int:pk>/agregar/", views.agregar_a_lista_deseos, name="agregar"),
]
