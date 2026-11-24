"""Reglas transaccionales para escribir precios del portal de empresas."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.translations import translate_text_lazy
from products.models import Currencies, Prices, ProductVariants, Products


class ErrorEmpresa(Exception):
    """Error de negocio que puede mostrarse directamente al usuario."""


def moneda_para_tienda(store):
    """Usa la moneda ya asociada a la tienda; nunca convierte precios."""
    precio_previo = (
        Prices.objects.filter(id_store_id=store.pk)
        .exclude(currency__isnull=True)
        .select_related("currency")
        .first()
    )
    if precio_previo is not None:
        return precio_previo.currency

    moneda = Currencies.objects.filter(name__iexact="colones").first()
    if moneda is None:
        moneda = Currencies.objects.order_by("id").first()
    if moneda is None:
        raise ErrorEmpresa(
            translate_text_lazy("No hay una moneda configurada para registrar el precio.")
        )
    return moneda


def _datos_precio(datos, precio):
    return {
        "price": precio,
        "discount": datos.get("discount") or Decimal("0.00"),
        "is_available": bool(datos.get("is_available")) and precio is not None,
        "product_web_url": datos.get("product_web_url") or "",
    }


def crear_precio_empresa(store, gtin, datos, producto_datos=None):
    """Crea el precio propio para un GTIN existente o nuevo.

    Para un GTIN existente solo se crea ``Prices``. Para uno nuevo se crean
    también un ``Products`` mínimo y su ``ProductVariants``.
    """
    ahora = timezone.now()
    try:
        with transaction.atomic():
            variante = (
                ProductVariants.objects.select_for_update()
                .filter(gtin=gtin)
                .first()
            )
            if variante is not None:
                if Prices.objects.filter(id_store_id=store.pk, gtin_id=gtin).exists():
                    raise ErrorEmpresa(
                        translate_text_lazy(
                            "Esta tienda ya tiene un precio para este GTIN. Edítelo en lugar de agregarlo otra vez."
                        )
                    )
            else:
                datos_producto = producto_datos or {}
                marca = datos_producto.get("brand")
                categoria = datos_producto.get("category")
                if marca is None or categoria is None:
                    raise ErrorEmpresa(
                        translate_text_lazy(
                            "Para crear un GTIN nuevo se necesita una marca y una categoría existentes."
                        )
                    )
                producto = Products.objects.create(
                    name=datos_producto.get("product_name") or datos_producto.get("variant_name"),
                    description=datos_producto.get("description") or "",
                    brand=marca,
                    category=categoria,
                    created_at=ahora,
                    updated_at=ahora,
                )
                variante = ProductVariants.objects.create(
                    product=producto,
                    gtin=gtin,
                    name=datos_producto.get("variant_name") or producto.name,
                    attributes=datos_producto.get("attributes"),
                    created_at=ahora,
                    updated_at=ahora,
                )

            moneda = moneda_para_tienda(store)
            valores = _datos_precio(datos, datos.get("price"))
            return Prices.objects.create(
                id_store=store,
                gtin=variante,
                currency=moneda,
                created_at=ahora,
                updated_at=ahora,
                **valores,
            )
    except IntegrityError as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "No se pudo guardar el precio porque el GTIN ya fue registrado para esta tienda."
            )
        ) from error


def editar_precio_empresa(store, price_id, datos):
    """Actualiza únicamente la fila ``Prices`` de la tienda."""
    with transaction.atomic():
        precio = (
            Prices.objects.select_for_update()
            .filter(pk=price_id, id_store_id=store.pk)
            .first()
        )
        if precio is None:
            raise ErrorEmpresa(translate_text_lazy("El precio no existe o no pertenece a su tienda."))

        valores = _datos_precio(datos, datos.get("price"))
        precio.price = valores["price"]
        precio.discount = valores["discount"]
        precio.is_available = valores["is_available"]
        precio.product_web_url = valores["product_web_url"]
        precio.updated_at = timezone.now()
        precio.save(
            update_fields=[
                "price",
                "discount",
                "is_available",
                "product_web_url",
                "updated_at",
            ]
        )
        return precio


def quitar_precio_empresa(store, price_id):
    """Quita el precio propio y marca la oferta como no disponible.

    Se conserva la fila para no afectar el GTIN ni las variantes compartidas.
    """
    with transaction.atomic():
        precio = (
            Prices.objects.select_for_update()
            .filter(pk=price_id, id_store_id=store.pk)
            .first()
        )
        if precio is None:
            raise ErrorEmpresa(translate_text_lazy("El precio no existe o no pertenece a su tienda."))
        precio.price = None
        precio.is_available = False
        precio.updated_at = timezone.now()
        precio.save(update_fields=["price", "is_available", "updated_at"])
        return precio


def desactivar_precio_empresa(store, price_id):
    """Desactiva solamente el precio propio de la tienda."""
    with transaction.atomic():
        precio = (
            Prices.objects.select_for_update()
            .filter(pk=price_id, id_store_id=store.pk)
            .first()
        )
        if precio is None:
            raise ErrorEmpresa(translate_text_lazy("El precio no existe o no pertenece a su tienda."))
        precio.is_available = False
        precio.updated_at = timezone.now()
        precio.save(update_fields=["is_available", "updated_at"])
        return precio
