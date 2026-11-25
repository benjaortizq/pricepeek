"""Acceso seguro al portal de empresas.

La tienda de una cuenta nunca se recibe desde el navegador: se obtiene de
``accounts_user.from_store`` y se usa como filtro obligatorio en todas las
consultas y escrituras del portal.
"""

from django.core.exceptions import PermissionDenied

from accounts.models import AccountsUser, User
from core.translations import translate_text_lazy
from products.models import Stores

MENSAJE_SIN_TIENDA = (
    "Su cuenta de empresa no tiene una tienda asignada. Contacte al administrador."
)


def tienda_del_usuario(user):
    """Devuelve la tienda asignada a un usuario empresa.

    ``AccountsUser`` y ``User`` representan la misma fila de ``accounts_user``.
    Por eso la relación se resuelve por el identificador del usuario autenticado
    y nunca por un dato enviado en la petición.
    """
    if not user.is_authenticated or user.role != User.Role.ENTERPRISE:
        raise PermissionDenied

    store_id = (
        AccountsUser.objects.filter(pk=user.pk)
        .values_list("from_store_id", flat=True)
        .first()
    )
    if store_id is None:
        raise PermissionDenied(translate_text_lazy(MENSAJE_SIN_TIENDA))

    try:
        return Stores.objects.get(pk=store_id)
    except Stores.DoesNotExist as error:
        raise PermissionDenied(translate_text_lazy(MENSAJE_SIN_TIENDA)) from error
