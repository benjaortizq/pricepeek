from django.urls import path

from . import views

urlpatterns = [
    path("comparar/", views.comparar_precios, name="comparar_precios"),
    path("filtros/", views.filtros_productos, name="filtros_productos"),
    path("<int:pk>/", views.detalle_producto, name="detalle_producto"),
]
