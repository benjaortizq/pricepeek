"""Lógica de services de la aplicación ingestion."""

from products.barcodes import validar_codigo_barras

from .models import Incident


def filtrar_productos_con_codigo_valido(productos, tienda=""):
    """Deja pasar solo los productos con código de barras válido (RF-38).

    `productos` es una lista de diccionarios con al menos las claves "gtin" y "name".
    Devuelve una lista nueva con los productos válidos, con el "gtin" ya normalizado a
    14 dígitos. Los productos sin código válido quedan fuera de la comparación y cada
    uno se anota como incidencia. No modifica los diccionarios que recibe.
    """
    validos = []
    incidencias = []
    for producto in productos:
        resultado = validar_codigo_barras(producto.get("gtin"))
        if resultado:
            validos.append({**producto, "gtin": resultado.normalizado})
            continue
        incidencias.append(
            Incident(
                kind=Incident.Kind.INVALID_BARCODE,
                store_name=str(tienda)[: Incident.NAME_MAX_LENGTH],
                product_name=str(producto.get("name") or "")[
                    : Incident.NAME_MAX_LENGTH
                ],
                gtin=str(producto.get("gtin") or "")[
                    : Incident.GTIN_MAX_LENGTH
                ],
                reason=resultado.motivo,
            )
        )
    Incident.objects.bulk_create(incidencias)
    return validos
