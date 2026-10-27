from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import RegistroClienteForm


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