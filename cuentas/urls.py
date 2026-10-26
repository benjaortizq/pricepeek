from django.urls import path

from . import views

urlpatterns = [
    path("registro/", views.registro, name="registro"),
]


urlpatterns = [
    path("registro/", views.registro, name="registro"),
    path("panel/", views.panel, name="panel"),
    path("cliente/", views.inicio_cliente, name="inicio_cliente"),
    path("empresa/", views.inicio_empresa, name="inicio_empresa"),
    path("administrador/", views.inicio_administrador, name="inicio_administrador"),
]