from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import RegistroClienteForm

from django.contrib.auth.decorators import login_required

from .decorators import rol_requerido
from .models import Usuario

def registro(request):
    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Su cuenta fue creada. Ya puede iniciar sesión.")
            return redirect("login")
    else:
        form = RegistroClienteForm()
    return render(request, "cuentas/registro.html", {"form": form})


@login_required
def panel(request):
    if request.user.rol == Usuario.Rol.EMPRESA:
        return redirect("inicio_empresa")
    if request.user.rol == Usuario.Rol.ADMINISTRADOR:
        return redirect("inicio_administrador")
    return redirect("inicio_cliente")


@rol_requerido(Usuario.Rol.CLIENTE)
def inicio_cliente(request):
    return render(request, "cuentas/inicio.html", {"titulo": "Inicio del cliente"})


@rol_requerido(Usuario.Rol.EMPRESA)
def inicio_empresa(request):
    return render(request, "cuentas/inicio.html", {"titulo": "Panel de empresa"})


@rol_requerido(Usuario.Rol.ADMINISTRADOR)
def inicio_administrador(request):
    return render(request, "cuentas/inicio.html", {"titulo": "Panel de administración"})