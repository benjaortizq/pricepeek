from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .decorators import role_required
from .forms import EliminarCuentaForm, RegistroClienteForm
from .models import User


def registro(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Su cuenta fue creada. Ya puede iniciar sesión.")
            return redirect("login")
    else:
        form = RegistroClienteForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def panel(request):
    if request.user.role == User.Role.ENTERPRISE:
        return redirect("inicio_empresa")
    if request.user.role == User.Role.ADMIN:
        return redirect("inicio_administrador")
    return redirect("inicio_cliente")


@role_required(User.Role.CLIENT)
def inicio_cliente(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Inicio del cliente"})


@role_required(User.Role.ENTERPRISE)
def inicio_empresa(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Panel de empresa"})


@role_required(User.Role.ADMIN)
def inicio_administrador(request):
    return render(request, "accounts/mainpage.html", {"titulo": "Panel de administración"})


@role_required(User.Role.CLIENT)
def eliminar_cuenta(request):
    if request.method == "POST":
        form = EliminarCuentaForm(request.user, request.POST)
        if form.is_valid():
            usuario = request.user
            logout(request)
            usuario.delete()
            messages.success(request, "Su cuenta y sus datos fueron eliminados.")
            return redirect("login")
    else:
        form = EliminarCuentaForm(request.user)
    return render(request, "accounts/eliminar_cuenta.html", {"form": form})
