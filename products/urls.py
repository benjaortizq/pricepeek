from django.urls import path

from . import views

urlpatterns = [
    path("buscar/", views.buscar, name="buscar_productos"),
    path("<int:pk>/", views.detalle_producto, name="detalle_producto"),
]
