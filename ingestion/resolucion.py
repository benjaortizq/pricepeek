"""Lo que el administrador hace con una extracción fallida desde el registro de incidencias (RF-43).

Cada acción corrige el precio guardado (o deja constancia de que no hacía falta) y marca como
resuelta la incidencia junto con sus repetidas: actualizar_precios corre cada hora y, mientras
el problema siga, anota una incidencia igual en cada corrida.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from products.models import Prices
from products.templatetags.precios import miles

from .actualizacion import NO_SOPORTADA, cambios_para, guardar_cambios, revisar
from .models import Incident, StoreProduct
from .scrapers import ClienteHttp, Oferta, extractor_para

Kind = Incident.Kind
EXTRACCION_FALLIDA = [tipo for tipo in Kind if tipo != Kind.INVALID_BARCODE]

ACEPTAR_PRECIO = "aceptar_precio"
ACEPTAR_CODIGO = "aceptar_codigo"
REVISAR = "revisar"
CAMBIAR_ENLACE = "enlace"
DESCARTAR = "descartar"

# Lo que tiene sentido hacer con cada tipo de incidencia, en el orden en que se ofrece.
ACCIONES = {
    Kind.SUSPICIOUS_PRICE: [ACEPTAR_PRECIO, DESCARTAR, CAMBIAR_ENLACE],
    Kind.BARCODE_MISMATCH: [ACEPTAR_CODIGO, CAMBIAR_ENLACE, DESCARTAR],
    Kind.PRODUCT_NOT_FOUND: [CAMBIAR_ENLACE, REVISAR, DESCARTAR],
    Kind.DOWNLOAD_FAILED: [REVISAR, CAMBIAR_ENLACE, DESCARTAR],
    Kind.PRICE_NOT_FOUND: [REVISAR, CAMBIAR_ENLACE, DESCARTAR],
}

# Cómo lo anotaba elegir_oferta antes de guardar los códigos en details.
_CODIGOS_EN_EL_MOTIVO = re.compile(
    r"La página es del código (.+?), pero el precio guardado"
)


class NoSePuedeResolver(Exception):
    pass


@dataclass
class Resultado:
    mensaje: str
    exito: bool = True
    repetidas: int = (
        0  # cuántas incidencias iguales se resolvieron además de esta
    )


def cliente_http():
    # Una sola página y sin reintentos largos: el administrador está esperando la respuesta.
    return ClienteHttp(pausa=0, timeout=15, reintentos=0)


def acciones_para(incidencia):
    if incidencia.status != Incident.Status.PENDING:
        return []
    return ACCIONES.get(incidencia.kind, [])


def codigos_de_la_tienda(incidencia):
    """Los códigos de barras que publica la tienda en la página de un «código distinto»."""
    codigos = incidencia.details.get("codigos")
    if codigos:
        return list(codigos)
    encontrado = _CODIGOS_EN_EL_MOTIVO.search(incidencia.reason)
    return (
        [codigo.strip() for codigo in encontrado.group(1).split(",")]
        if encontrado
        else []
    )


def precio_de(incidencia):
    """La fila de prices de la incidencia: la de ese código en ese comercio (prices no repite la pareja)."""
    if incidencia.kind not in EXTRACCION_FALLIDA or not incidencia.gtin:
        return None
    filas = Prices.objects.select_related("id_store", "gtin").filter(
        gtin_id=incidencia.gtin
    )
    return next(
        (
            fila
            for fila in filas
            if fila.id_store.name.strip() == incidencia.store_name.strip()
        ),
        None,
    )


def _final(precio, descuento):
    return None if precio is None else round(precio * (1 - descuento))


def _dominio(url):
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


class Resolucion:
    """Una acción del administrador sobre una incidencia pendiente."""

    def __init__(self, incidencia, usuario, http=None):
        if incidencia.status != Incident.Status.PENDING:
            raise NoSePuedeResolver("Esta incidencia ya estaba resuelta.")
        self.incidencia = incidencia
        self.usuario = usuario
        self._http = http

    @property
    def http(self):
        if self._http is None:
            self._http = cliente_http()
        return self._http

    def precio(self):
        precio = precio_de(self.incidencia)
        if precio is None:
            raise NoSePuedeResolver(
                "El precio de esta incidencia ya no existe en el catálogo."
            )
        return precio

    def resolver(self, nota, todos_los_tipos=False, excepto=None):
        """Marca como resuelta la incidencia y las pendientes iguales del mismo precio.

        Con todos_los_tipos=True, todas las extracciones fallidas pendientes de ese precio
        (por ejemplo, cuando el precio quedó al día y ya no importa por qué falló antes).
        """
        incidencia = self.incidencia
        if incidencia.gtin and incidencia.store_name:
            pendientes = Incident.objects.filter(
                status=Incident.Status.PENDING,
                gtin=incidencia.gtin,
                store_name=incidencia.store_name,
                kind__in=EXTRACCION_FALLIDA
                if todos_los_tipos
                else [incidencia.kind],
            )
        else:  # sin precio al que pertenezca, no hay repetidas que reconocer
            pendientes = Incident.objects.filter(
                pk=incidencia.pk, status=Incident.Status.PENDING
            )
        if excepto is not None and excepto.pk:
            pendientes = pendientes.exclude(pk=excepto.pk)
        resueltas = pendientes.update(
            status=Incident.Status.RESOLVED,
            resolved_by=self.usuario,
            resolved_at=timezone.now(),
            resolution=nota[: Incident.RESOLUTION_MAX_LENGTH],
        )
        return max(resueltas - 1, 0)

    # Las acciones que descargan la página lo hacen antes de abrir la transacción, para no
    # tenerla abierta mientras se espera a la tienda.

    def aceptar_precio_nuevo(self):
        precio = self.precio()
        detalles = self.incidencia.details
        if detalles.get("precio_final") is not None:
            final = detalles["precio_final"]
            oferta = Oferta(
                detalles.get("precio_lista") or final,
                final,
                detalles.get("disponible", True),
            )
            cambios = cambios_para(precio, oferta)
        else:
            # Incidencias anotadas antes de guardar el precio leído: se vuelve a leer la página.
            revision = revisar(
                precio, self.http, guardar=False, permitir_cambio_grande=True
            )
            if revision.resultado == NO_SOPORTADA:
                raise NoSePuedeResolver(
                    "PricePeek no sabe leer las páginas de esa tienda."
                )
            if revision.incidencia is not None:
                raise NoSePuedeResolver(
                    f"No se pudo leer el precio de la tienda: {revision.incidencia.motivo}"
                )
            cambios = revision.cambios
        lista = cambios["price"][1] if "price" in cambios else precio.price
        descuento = (
            cambios["discount"][1]
            if "discount" in cambios
            else precio.discount
        )
        nota = (
            f"Se aceptó el precio nuevo: ₡{miles(_final(lista, descuento))}."
        )
        with transaction.atomic():
            guardar_cambios(precio, cambios)
            repetidas = self.resolver(nota, todos_los_tipos=True)
        return Resultado(nota, repetidas=repetidas)

    @transaction.atomic
    def aceptar_codigo_de_la_tienda(self):
        """La página sí es la variante guardada, aunque la tienda publique otro código.

        Queda como producto de tienda confirmado (Ingestion › Productos de tiendas), que es de
        donde actualizar_precios toma los códigos aceptados para cada página.
        """
        precio = self.precio()
        codigos = codigos_de_la_tienda(self.incidencia)
        if not codigos:
            raise NoSePuedeResolver(
                "No se sabe qué código publica la tienda; vuelva a revisar la página."
            )
        url = precio.product_web_url
        if len(url) > StoreProduct._meta.get_field("url").max_length:
            raise NoSePuedeResolver(
                "El enlace del precio es demasiado largo para guardarlo como producto de tienda."
            )
        producto = StoreProduct.objects.filter(url=url).first()
        if producto is None:
            producto = StoreProduct(
                url=url,
                store_name=precio.id_store.name.strip()[:100],
                name=precio.gtin.name[:255],
            )
        elif (
            producto.status == StoreProduct.Status.CONFIRMED
            and producto.suggested_gtin not in ("", precio.gtin_id)
        ):
            raise NoSePuedeResolver(
                f"Esa página ya está vinculada a otra variante del catálogo ({producto.suggested_gtin})."
            )
        producto.barcodes = sorted(set(producto.barcodes) | set(codigos))
        producto.suggested_gtin = precio.gtin_id
        producto.status = StoreProduct.Status.CONFIRMED
        producto.score = None
        producto.match_reason = "código aceptado en el registro de incidencias"
        producto.save()
        nota = f"Se aceptó el código {', '.join(codigos)} de la tienda para esta variante."
        repetidas = self.resolver(nota)
        return Resultado(
            f"{nota} El precio se actualizará en la próxima revisión.",
            repetidas=repetidas,
        )

    def volver_a_revisar(self):
        precio = self.precio()
        revision = revisar(
            precio, self.http
        )  # guarda el precio o una incidencia nueva, como cada hora
        if revision.resultado == NO_SOPORTADA:
            raise NoSePuedeResolver(
                "PricePeek no sabe leer las páginas de esa tienda."
            )
        if revision.incidencia is not None:
            # Quedó una incidencia nueva con el motivo de ahora; las anteriores ya no hacen falta.
            nota = "Se volvió a revisar y siguió fallando; quedó una incidencia nueva."
            repetidas = self.resolver(
                nota, todos_los_tipos=True, excepto=revision.incidencia
            )
            return Resultado(
                f"Sigue fallando: {revision.incidencia.motivo}",
                exito=False,
                repetidas=repetidas,
            )
        nota = "Se volvió a revisar y el precio quedó al día."
        return Resultado(
            nota, repetidas=self.resolver(nota, todos_los_tipos=True)
        )

    def cambiar_enlace(self, url):
        precio = self.precio()
        url = (url or "").strip()
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            raise NoSePuedeResolver(
                "Escriba la dirección completa de la página, con https://."
            ) from None
        if url == precio.product_web_url:
            raise NoSePuedeResolver(
                "Es el mismo enlace que ya tiene el precio."
            )
        if extractor_para(url) is None:
            raise NoSePuedeResolver(
                "PricePeek no sabe leer las páginas de ese sitio."
            )
        if _dominio(url) != _dominio(precio.product_web_url):
            raise NoSePuedeResolver(
                f"El enlace nuevo tiene que ser de la misma tienda ({_dominio(precio.product_web_url)})."
            )

        # Antes de guardarla, se revisa que la página nueva sí sirva.
        precio.product_web_url = url
        revision = revisar(precio, self.http, guardar=False)
        if revision.incidencia is not None:
            raise NoSePuedeResolver(
                f"No se cambió el enlace porque la página nueva falló: {revision.incidencia.motivo}"
            )
        nota = "Se cambió el enlace del precio y quedó al día."
        with transaction.atomic():
            Prices.objects.filter(pk=precio.pk).update(product_web_url=url)
            guardar_cambios(precio, revision.cambios)
            repetidas = self.resolver(nota, todos_los_tipos=True)
        return Resultado(nota, repetidas=repetidas)

    @transaction.atomic
    def descartar(self):
        if self.incidencia.kind == Kind.SUSPICIOUS_PRICE:
            nota = "Se mantuvo el precio guardado."
        else:
            nota = "Se marcó como revisada sin cambios."
        return Resultado(nota, repetidas=self.resolver(nota))

    def ejecutar(self, accion, url=""):
        if accion not in acciones_para(self.incidencia):
            raise NoSePuedeResolver("Esa acción no aplica a esta incidencia.")
        if accion == ACEPTAR_PRECIO:
            return self.aceptar_precio_nuevo()
        if accion == ACEPTAR_CODIGO:
            return self.aceptar_codigo_de_la_tienda()
        if accion == REVISAR:
            return self.volver_a_revisar()
        if accion == CAMBIAR_ENLACE:
            return self.cambiar_enlace(url)
        return self.descartar()
