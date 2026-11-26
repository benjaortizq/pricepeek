"""Registro de comercios asociados y de sus cuentas de empresa, desde el panel de administración.

Issue «Gestión de comercios asociados». El comercio es una fila de stores (Supabase) con su
PartnerStore (products/models.py: mecanismo de obtención de datos y si está activo). Cada
cuenta de empresa es un usuario con rol «enterprise» cuyo accounts_user.from_store apunta al
comercio: así lo encuentra el portal de empresas (enterprise/access.py).

La contraseña de la cuenta nueva no la elige ni la ve el administrador: la cuenta queda con una
contraseña al azar y a su correo llega un enlace para elegir la suya (el mismo de «¿Olvidaste tu
contraseña?»). Si el enlace vence, sirve pedir uno nuevo desde el inicio de sesión.
"""

import secrets

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from ingestion.catalogo import arreglar_secuencias, secuencias_atrasadas
from products.comercios import (
    comercios_con_lector,
    mecanismo_de,
    nombre_del_comercio,
)
from products.models import PartnerStore, Stores

from .models import AccountsUser, User


def cuentas_de_empresa(tienda):
    """Las cuentas de empresa del comercio, la más antigua primero."""
    ids = AccountsUser.objects.filter(
        from_store_id=tienda.pk, role=User.Role.ENTERPRISE
    ).values("pk")
    return User.objects.filter(pk__in=ids).order_by("date_joined", "pk")


def perfil_de(tienda):
    return PartnerStore.objects.filter(store_id=tienda.pk).first()


@transaction.atomic
def registrar_comercio(
    *, nombre, descripcion, mecanismo, activo, administrador
):
    """Crea el comercio (stores) y su PartnerStore. Devuelve la tienda."""
    ahora = timezone.now()
    # Si alguien insertó tiendas con el id escrito a mano, el contador quedó atrás (ingestion/catalogo.py).
    arreglar_secuencias(secuencias_atrasadas([Stores]))
    tienda = Stores.objects.create(
        name=nombre,
        description=descripcion or None,
        created_at=ahora,
        updated_at=ahora,
    )
    PartnerStore.objects.create(
        store=tienda,
        data_source=mecanismo,
        is_active=activo,
        status_changed_at=ahora,
        status_changed_by=administrador,
    )
    return tienda


@transaction.atomic
def guardar_datos_del_comercio(tienda, *, nombre, descripcion, mecanismo):
    """Cambia el nombre, la descripción y el mecanismo de obtención de datos. Devuelve si cambió algo."""
    perfil = perfil_de(tienda)
    actual = mecanismo_de(
        tienda, perfil, comercios_con_lector() if perfil is None else set()
    )
    # «Walmart\n» y «Walmart» son el mismo nombre: la obtención de datos compara sin espacios ni mayúsculas.
    if (nombre_del_comercio(tienda), tienda.description or None, actual) == (
        nombre,
        descripcion or None,
        mecanismo,
    ):
        return False
    tienda.name, tienda.description, tienda.updated_at = (
        nombre,
        descripcion or None,
        timezone.now(),
    )
    tienda.save(update_fields=["name", "description", "updated_at"])
    PartnerStore.objects.update_or_create(
        store=tienda, defaults={"data_source": mecanismo}
    )
    return True


@transaction.atomic
def cambiar_estado(tienda, *, activo, administrador):
    """Activa o desactiva el comercio. Devuelve False si ya estaba así."""
    perfil = perfil_de(tienda)
    if (perfil.is_active if perfil else True) == activo:
        return False
    mecanismo = (
        perfil.data_source
        if perfil
        else mecanismo_de(tienda, None, comercios_con_lector())
    )
    PartnerStore.objects.update_or_create(
        store=tienda,
        defaults={
            "data_source": mecanismo,
            "is_active": activo,
            "status_changed_at": timezone.now(),
            "status_changed_by": administrador,
        },
    )
    return True


@transaction.atomic
def crear_cuenta_de_empresa(tienda, *, correo, nombre="", apellidos=""):
    """Crea la cuenta de empresa del comercio. Después hay que enviarle el acceso (enviar_acceso)."""
    cuenta = User.objects.create_user(
        email=correo,
        # Nadie la conoce: la persona elige la suya con el enlace del correo (o con «¿Olvidaste tu contraseña?»).
        password=secrets.token_urlsafe(32),
        role=User.Role.ENTERPRISE,
        first_name=nombre,
        last_name=apellidos,
    )
    AccountsUser.objects.filter(pk=cuenta.pk).update(from_store_id=tienda.pk)
    return cuenta


def enviar_acceso(cuenta, tienda, request):
    """Envía a la cuenta el enlace para elegir su contraseña. Devuelve False si el correo no salió."""
    enlace = request.build_absolute_uri(
        reverse(
            "password_reset_confirm",
            kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(cuenta.pk)),
                "token": default_token_generator.make_token(cuenta),
            },
        )
    )
    contexto = {
        "cuenta": cuenta,
        "comercio": " ".join(tienda.name.split()),
        "enlace": enlace,
    }
    asunto = render_to_string(
        "accounts/correo_cuenta_empresa_asunto.txt", contexto
    )
    cuerpo = render_to_string("accounts/correo_cuenta_empresa.txt", contexto)
    try:
        send_mail("".join(asunto.splitlines()), cuerpo, None, [cuenta.email])
    except Exception:  # noqa: BLE001 - un servidor de correo caído no deshace lo que ya se guardó
        return False
    return True
