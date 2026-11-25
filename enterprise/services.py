"""Reglas de escritura del portal de empresas."""

import hashlib
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.translations import translate_text_lazy
from products.models import Currencies, Prices, ProductImages, ProductVariants, Products

from .imagenes import URLImagenInvalida, normalizar_urls_imagenes


class ErrorEmpresa(Exception):
    """Error de negocio que puede mostrarse directamente al usuario."""


# Espacio reservado para los bloqueos advisories del módulo de empresas.
_ESPACIO_BLOQUEO_GTIN = 0x50506565


def _bloquear_gtin(gtin):
    """Serializa las escrituras concurrentes del mismo GTIN.

    ``select_for_update`` no puede bloquear una variante que todavía no
    existe. En PostgreSQL, un lock advisory de transacción cubre esa breve
    ventana y coordina también a tiendas distintas que reciben el mismo GTIN.
    La restricción única de ``product_variants.gtin`` sigue siendo la defensa
    final frente a escritores externos a este módulo.
    """
    if connection.vendor != "postgresql":
        return

    digest = hashlib.sha256(str(gtin).encode("utf-8")).digest()
    clave_gtin = int.from_bytes(digest[:4], byteorder="big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            [_ESPACIO_BLOQUEO_GTIN, clave_gtin],
        )


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


def _urls_imagenes_empresa(urls):
    try:
        return normalizar_urls_imagenes(urls or [])
    except URLImagenInvalida as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El enlace de la imagen debe comenzar con http:// o https://, no debe contener espacios y no puede superar 2000 caracteres."
            )
        ) from error
    except ValueError as error:
        raise ErrorEmpresa(
            translate_text_lazy("No se permiten enlaces de imagen duplicados.")
        ) from error


def _imagenes_bloqueadas(product_id):
    """Devuelve las imágenes del producto bloqueadas para escritura."""
    variant_ids = ProductVariants.objects.filter(product_id=product_id).values_list(
        "id", flat=True
    )
    return list(
        ProductImages.objects.select_for_update()
        .filter(variant_id__in=variant_ids)
        .order_by("number_image", "id")
    )


def _agregar_imagenes(variante, urls, ahora, imagenes_existentes=None):
    """Agrega imágenes con orden consecutive y una sola principal por producto."""
    urls = _urls_imagenes_empresa(urls)
    if not urls:
        return []

    # El producto es el padre estable de todas sus variantes. Bloquearlo
    # serializa las adiciones aunque dos solicitudes lleguen a la vez.
    Products.objects.select_for_update().get(pk=variante.product_id)
    imagenes = (
        imagenes_existentes
        if imagenes_existentes is not None
        else _imagenes_bloqueadas(variante.product_id)
    )
    if imagenes:
        siguiente_numero = max(imagen.number_image for imagen in imagenes) + 1
        es_principal = False
    else:
        siguiente_numero = 1
        es_principal = True

    creadas = []
    for indice, url in enumerate(urls):
        imagen = ProductImages.objects.create(
            variant=variante,
            image_url=url,
            is_main=es_principal and indice == 0,
            number_image=siguiente_numero,
            created_at=ahora,
            updated_at=ahora,
        )
        creadas.append(imagen)
        siguiente_numero += 1
    return creadas


def crear_precio_empresa(store, gtin, datos, producto_datos=None, image_urls=None):
    """Crea el precio propio para un GTIN existente o nuevo.

    Para un GTIN existente solo se crea ``Prices`` y nunca se modifican sus
    imágenes. Para uno nuevo se crean también un ``Products`` mínimo, su
    ``ProductVariants`` y las imágenes indicadas, todo en una sola transacción.
    """
    ahora = timezone.now()
    try:
        with transaction.atomic():
            _bloquear_gtin(gtin)
            variante = (
                ProductVariants.objects.select_for_update()
                .filter(gtin=gtin)
                .first()
            )
            if variante is not None:
                gtin_ya_existia = True
                if Prices.objects.filter(id_store_id=store.pk, gtin_id=gtin).exists():
                    raise ErrorEmpresa(
                        translate_text_lazy(
                            "Esta tienda ya tiene un precio para este GTIN. Edítelo en lugar de agregarlo otra vez."
                        )
                    )
            else:
                gtin_ya_existia = False
                datos_producto = producto_datos or {}
                marca = datos_producto.get("brand")
                categoria = datos_producto.get("category")
                if marca is None or categoria is None:
                    raise ErrorEmpresa(
                        translate_text_lazy(
                            "Para crear un GTIN nuevo se necesita una marca y una categoría existentes."
                        )
                    )
                urls_imagenes = _urls_imagenes_empresa(image_urls)
                if not urls_imagenes:
                    raise ErrorEmpresa(
                        translate_text_lazy(
                            "Debe agregar al menos un enlace de imagen para un GTIN nuevo."
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
                _agregar_imagenes(variante, urls_imagenes, ahora)

            moneda = moneda_para_tienda(store)
            valores = _datos_precio(datos, datos.get("price"))
            precio = Prices.objects.create(
                id_store=store,
                gtin=variante,
                currency=moneda,
                created_at=ahora,
                updated_at=ahora,
                **valores,
            )
            # La vista usa esta marca para distinguir un GTIN recién creado de
            # uno que ya existía, incluso si cambió entre el POST y el lock.
            precio.gtin_ya_existia = gtin_ya_existia
            return precio
    except IntegrityError as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "No se pudo guardar el precio porque el GTIN ya fue registrado para esta tienda."
            )
        ) from error


def editar_imagenes_empresa(
    store,
    price_id,
    image_urls,
    new_image_urls,
    confirm_shared_changes=False,
):
    """Edita y agrega imágenes de un producto que pertenece a la tienda.

    Las imágenes existentes se envían en el mismo orden que devuelve el
    servidor. No se aceptan identificadores de imagen del cliente.
    """
    existentes = _urls_imagenes_empresa(image_urls)
    nuevas = _urls_imagenes_empresa(new_image_urls)
    try:
        normalizar_urls_imagenes(existentes + nuevas)
    except URLImagenInvalida as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El enlace de la imagen debe comenzar con http:// o https://, no debe contener espacios y no puede superar 2000 caracteres."
            )
        ) from error
    except ValueError as error:
        raise ErrorEmpresa(
            translate_text_lazy("No se permiten enlaces de imagen duplicados.")
        ) from error

    ahora = timezone.now()
    with transaction.atomic():
        precio = (
            Prices.objects.select_for_update()
            .filter(pk=price_id, id_store_id=store.pk)
            .select_related("gtin__product")
            .first()
        )
        if precio is None:
            raise ErrorEmpresa(
                translate_text_lazy(
                    "El producto no existe o no pertenece a su tienda."
                )
            )

        product_id = precio.gtin.product_id
        Products.objects.select_for_update().get(pk=product_id)
        imagenes = _imagenes_bloqueadas(product_id)
        if len(existentes) != len(imagenes):
            raise ErrorEmpresa(
                translate_text_lazy(
                    "La lista de imágenes cambió. Recargue la página e intente de nuevo."
                )
            )
        if not imagenes and not nuevas:
            raise ErrorEmpresa(
                translate_text_lazy(
                    "Debe agregar al menos un enlace de imagen para este producto."
                )
            )

        cambiaron_existentes = False
        for imagen, url in zip(imagenes, existentes):
            if imagen.image_url != url:
                cambiaron_existentes = True
                imagen.image_url = url
                imagen.updated_at = ahora
                imagen.save(update_fields=["image_url", "updated_at"])

        if cambiaron_existentes and not confirm_shared_changes:
            raise ErrorEmpresa(
                translate_text_lazy(
                    "Debe confirmar que autoriza actualizar las imágenes compartidas."
                )
            )

        _agregar_imagenes(
            precio.gtin,
            nuevas,
            ahora,
            imagenes_existentes=imagenes,
        )
        return precio


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


def actualizar_informacion_tienda_empresa(store, datos):
    """Actualiza únicamente el nombre y la descripción de la tienda."""
    store.name = datos["name"]
    store.description = datos["description"]
    store.save(update_fields=["name", "description"])
    return store
