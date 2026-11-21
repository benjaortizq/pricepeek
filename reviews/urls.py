from django.urls import path

from . import views

urlpatterns = [
    path("<int:pk>/editar/", views.editar_resena, name="editar_resena"),
    path("<int:pk>/eliminar/", views.eliminar_resena, name="eliminar_resena"),
    path("<int:review_id>/reportar/", views.reportar_resena, name="reportar_resena"),
    path("moderacion/", views.resenas_reportadas, name="resenas_reportadas"),
    path("moderacion/<int:review_id>/", views.moderar_resena, name="moderar_resena"),
]
