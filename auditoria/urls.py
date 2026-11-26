"""Rutas HTTP de la aplicación auditoria."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.bitacora, name="bitacora"),
]
