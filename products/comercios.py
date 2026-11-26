"""Comercios asociados: si están activos y cómo se obtienen sus datos.

Issue «Gestión de comercios asociados». Lo que el administrador define queda en PartnerStore
(products/models.py) y tiene efecto en dos lugares:

- Activo o desactivado: los precios de un comercio desactivado no se le muestran al usuario
  final (Prices.visibles) y la obtención de datos deja de revisarlos.
- Mecanismo de adquisición: con «web scraping», la obtención de datos de cada hora revisa sus
  precios en su página; con «datos provistos por el comercio», no se tocan: los carga el
  comercio desde el portal de empresas (formulario o CSV).

Los comercios que ya existían no tienen fila en PartnerStore: siguen activos y su mecanismo se
deduce de si PricePeek sabe leer su página, como hasta ahora.
"""

from django.db.models import Q

from .models import PartnerStore, Prices, Stores


def nombre_del_comercio(tienda):
    """«Walmart\\n» -> «Walmart»: algunos nombres de stores traen saltos de línea."""
    return " ".join((tienda.name or "").split())


def sin_obtencion_automatica():
    """Los comercios que la obtención de datos no revisa: los desactivados y los que proveen sus datos.

    Es una subconsulta, para filtrar precios: .exclude(id_store_id__in=sin_obtencion_automatica()).
    """
    return PartnerStore.objects.filter(
        Q(is_active=False) | Q(data_source=PartnerStore.DataSource.PROVIDED)
    ).values("store_id")


def comercios_con_lector():
    """Los ids de los comercios cuya página PricePeek sabe leer.

    Sirve si alguno de sus precios es de una página que la obtención de datos sabe leer (por el
    dominio, ingestion/scrapers) o si hay un lector de su catálogo con su nombre (ingestion/tiendas).
    """
    from ingestion.scrapers import extractor_para
    from ingestion.tiendas import TIENDAS

    nombres = {lector.NOMBRE.casefold() for lector in TIENDAS.values()}
    ids = {tienda.pk for tienda in Stores.objects.all() if nombre_del_comercio(tienda).casefold() in nombres}
    for tienda_id, url in Prices.objects.values_list("id_store_id", "product_web_url"):
        if tienda_id not in ids and extractor_para(url) is not None:
            ids.add(tienda_id)
    return ids


def mecanismo_de(tienda, perfil, con_lector):
    """El mecanismo que eligió el administrador o, si nunca lo eligió, el que se usa hoy."""
    if perfil is not None:
        return perfil.data_source
    return PartnerStore.DataSource.SCRAPING if tienda.pk in con_lector else PartnerStore.DataSource.PROVIDED
