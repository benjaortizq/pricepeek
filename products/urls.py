from django.urls import path

from . import views

urlpatterns = [
    path("<int:pk>/", views.detalle_producto, name="detalle_producto"),
]
