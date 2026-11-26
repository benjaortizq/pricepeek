"""Revisión de los precios guardados contra lo que publica cada tienda (SCRUM-56).

Por cada fila de prices: se descarga la página de la tienda, se elige la oferta de la
presentación guardada y se actualizan precio, descuento y disponibilidad. Si algo
falla, el precio no se toca y queda una incidencia para revisarla.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from products.auditoria import registrar_cambio_precio
from products.barcodes import calcular_digito_verificador
from products.models import Prices

from .models import Incident, StoreProduct
from .scrapers import (
    CodigoDistinto,
    ErrorDescarga,
    ErrorExtraccion,
    Oferta,
    PrecioNoEncontrado,
    ProductoNoEncontrado,
    extractor_para,
)

# Si el precio final cambia más que esto (50 %), no se guarda: puede ser un error de lectura.
CAMBIO_SOSPECHOSO = Decimal("0.5")

ACTUALIZADO = "actualizado"
SIN_CAMBIOS = "sin cambios"
FALLO = "fallo"
NO_SOPORTADA = "tienda no soportada"

TIPOS_DE_INCIDENCIA = [
    (ErrorDescarga, Incident.Kind.DOWNLOAD_FAILED),
    (ProductoNoEncontrado, Incident.Kind.PRODUCT_NOT_FOUND),
    (CodigoDistinto, Incident.Kind.BARCODE_MISMATCH),
    (PrecioNoEncontrado, Incident.Kind.PRICE_NOT_FOUND),
]


@dataclass
class Revision:
    precio: Prices
    resultado: str
    cambios: dict = field(default_factory=dict)  # campo -> (antes, después)
    incidencia: Incident | None = None


def expandir_upc_e(codigo):
    """UPC-E (8 dígitos, la versión comprimida del UPC-A) -> UPC-A de 12 dígitos, o None si no lo es.

    Por ejemplo, Peri y Megasuper reportan la salsa de tomate Heinz como 01307605,
    que es el UPC-A 013000000765.
    """
    if len(codigo) != 8 or not codigo.isdigit() or codigo[0] not in "01":
        return None
    sistema, cuerpo, verificador = codigo[0], codigo[1:7], codigo[7]
    ultimo = cuerpo[5]
    if ultimo in "012":
        expandido = cuerpo[:2] + ultimo + "0000" + cuerpo[2:5]
    elif ultimo == "3":
        expandido = cuerpo[:3] + "00000" + cuerpo[3:5]
    elif ultimo == "4":
        expandido = cuerpo[:4] + "00000" + cuerpo[4]
    else:
        expandido = cuerpo[:5] + "0000" + ultimo
    upc_a = sistema + expandido + verificador
    return upc_a if calcular_digito_verificador(upc_a[:-1]) == int(verificador) else None


def formas_del_codigo(codigo):
    """Las formas en que se puede escribir el mismo código, con 14 dígitos (como en products.barcodes)."""
    codigo = str(codigo).strip()
    formas = {codigo.zfill(14)}
    upc_a = expandir_upc_e(codigo)
    if upc_a:
        formas.add(upc_a.zfill(14))
    return formas


def elegir_oferta(ofertas, gtin, aceptados=()):
    """La oferta de la presentación guardada.

    Si la tienda reporta códigos de barras, uno tiene que coincidir con el guardado (o con
    alguno de `aceptados`: los que una persona confirmó para esta página en el admin).
    Si no reporta ninguno (Automercado) y la página tiene una sola oferta, se confía en la URL.
    """
    buscado = formas_del_codigo(gtin).union(*(formas_del_codigo(c) for c in aceptados))
    for oferta in ofertas:
        if any(buscado & formas_del_codigo(codigo) for codigo in oferta.gtins):
            return oferta
    reportados = sorted({codigo for oferta in ofertas for codigo in oferta.gtins})
    if reportados:
        raise CodigoDistinto(
            f"La página es del código {', '.join(reportados)}, pero el precio guardado es del {gtin}.",
            codigos=reportados,
        )
    if len(ofertas) == 1:
        return ofertas[0]
    raise PrecioNoEncontrado("La página tiene varias presentaciones sin código de barras y no se sabe cuál es.")


def codigos_confirmados(url):
    """Los códigos que publica la tienda en esa página, si una persona confirmó en el admin que
    es la variante guardada aunque el código sea otro (Ingestion › Productos de tiendas)."""
    return (
        StoreProduct.objects.filter(url=url, status=StoreProduct.Status.CONFIRMED)
        .values_list("barcodes", flat=True)
        .first()
        or []
    )


def precio_final_guardado(precio):
    if precio.price is None:
        return None
    return round(precio.price * (1 - precio.discount))


def es_sospechoso(precio, oferta):
    antes = precio_final_guardado(precio)
    if not antes or oferta.precio_final is None:
        return False
    return Decimal(abs(oferta.precio_final - antes)) / antes > CAMBIO_SOSPECHOSO


def _objetivo_oferta(oferta):
    """Los valores que la oferta quiere dejar en ``prices``."""
    nuevos = {"is_available": oferta.disponible}
    if oferta.precio_final is not None:
        nuevos["price"] = oferta.precio_lista
        nuevos["discount"] = oferta.descuento
    return nuevos


def cambios_para(precio, oferta):
    """Los campos que cambian. Si la oferta no trae precio, se conserva el último conocido."""
    return {
        campo: (getattr(precio, campo), valor)
        for campo, valor in _objetivo_oferta(oferta).items()
        if getattr(precio, campo) != valor
    }


def revisar(precio, http, guardar=True, permitir_cambio_grande=False):
    """Revisa una fila de prices (con id_store y gtin cargados). Con guardar=False no escribe nada.

    Con permitir_cambio_grande=True se guarda el precio aunque cambie más de CAMBIO_SOSPECHOSO:
    es para cuando el administrador ya confirmó que el cambio es real.
    """
    extractor = extractor_para(precio.product_web_url)
    if extractor is None:
        return Revision(precio, NO_SOPORTADA)

    aceptados = codigos_confirmados(precio.product_web_url)
    try:
        oferta = elegir_oferta(extractor(precio.product_web_url, http), precio.gtin_id, aceptados)
    except ProductoNoEncontrado as error:
        # La tienda ya no lo vende: queda como no disponible, con su último precio.
        revision = _aplicar(precio, Oferta(None, None, False), guardar)
        revision.incidencia = _incidencia(precio, Incident.Kind.PRODUCT_NOT_FOUND, error, guardar)
        return revision
    except ErrorExtraccion as error:
        tipo = next(t for clase, t in TIPOS_DE_INCIDENCIA if isinstance(error, clase))
        detalles = {"codigos": list(error.codigos)} if isinstance(error, CodigoDistinto) else {}
        return Revision(precio, FALLO, incidencia=_incidencia(precio, tipo, error, guardar, detalles))
    except Exception as error:  # un formato inesperado no debe detener la revisión de las demás
        motivo = f"Error inesperado al leer la página ({error.__class__.__name__}: {error})."
        return Revision(precio, FALLO, incidencia=_incidencia(precio, Incident.Kind.PRICE_NOT_FOUND, motivo, guardar))

    if not permitir_cambio_grande and es_sospechoso(precio, oferta):
        motivo = (
            f"El precio final pasaría de {precio_final_guardado(precio)} a {oferta.precio_final} colones. "
            "No se guardó para que alguien lo revise."
        )
        detalles = {
            "precio_antes": precio_final_guardado(precio),
            "precio_lista": oferta.precio_lista,
            "precio_final": oferta.precio_final,
            "disponible": oferta.disponible,
        }
        incidencia = _incidencia(precio, Incident.Kind.SUSPICIOUS_PRICE, motivo, guardar, detalles)
        return Revision(precio, FALLO, incidencia=incidencia)

    return _aplicar(precio, oferta, guardar)


def guardar_cambios(precio, cambios, valores_objetivo=None):
    """Bloquea el precio, escribe los cambios y registra la auditoría.

    La comparación se hace sobre la fila bloqueada para que el valor anterior
    de la auditoría sea siempre el que estaba realmente guardado. La escritura
    y el registro comparten la misma transacción. ``updated_at`` queda como la
    última vez que se verificó el precio, aunque no haya cambiado.
    """
    with transaction.atomic():
        fila = Prices.objects.select_for_update().get(pk=precio.pk)
        if valores_objetivo is None:
            objetivo = {
                campo: despues for campo, (_, despues) in cambios.items()
            }
        else:
            objetivo = dict(valores_objetivo)

        cambios_reales = {
            campo: (getattr(fila, campo), valor)
            for campo, valor in objetivo.items()
            if getattr(fila, campo) != valor
        }
        ahora = timezone.now()
        if cambios_reales:
            antes = {
                "price": fila.price,
                "discount": fila.discount,
                "is_available": fila.is_available,
            }
            for campo, (_, valor) in cambios_reales.items():
                setattr(fila, campo, valor)
            fila.updated_at = ahora
            fila.save(update_fields=[*cambios_reales, "updated_at"])
            registrar_cambio_precio(
                fila,
                antes,
                {
                    "price": fila.price,
                    "discount": fila.discount,
                    "is_available": fila.is_available,
                },
                id_requested_by=None,
            )
        else:
            Prices.objects.filter(pk=fila.pk).update(updated_at=ahora)

        for campo, (_, valor) in cambios_reales.items():
            setattr(precio, campo, valor)
        precio.updated_at = ahora
        return cambios_reales


def _aplicar(precio, oferta, guardar):
    cambios = cambios_para(precio, oferta)
    if guardar:
        cambios = guardar_cambios(precio, cambios, _objetivo_oferta(oferta))
    return Revision(precio, ACTUALIZADO if cambios else SIN_CAMBIOS, cambios)


def _incidencia(precio, tipo, motivo, guardar, detalles=None):
    incidencia = Incident(
        kind=tipo,
        store_name=precio.id_store.name.strip()[: Incident.NAME_MAX_LENGTH],
        product_name=precio.gtin.name[: Incident.NAME_MAX_LENGTH],
        gtin=str(precio.gtin_id)[: Incident.GTIN_MAX_LENGTH],
        reason=f"{motivo}\n{precio.product_web_url}",
        details=detalles or {},
    )
    if guardar:
        incidencia.save()
    return incidencia
