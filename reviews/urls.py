from django.urls import path

from . import views

urlpatterns = [
    path("<int:pk>/editar/", views.editar_resena, name="editar_resena"),
    path("<int:pk>/eliminar/", views.eliminar_resena, name="eliminar_resena"),
]
