from django.urls import path

from . import views

urlpatterns = [
    path("incidencias/", views.incidencias, name="incidencias"),
    path("incidencias/<int:pk>/resolver/", views.resolver_incidencia, name="resolver_incidencia"),
]
