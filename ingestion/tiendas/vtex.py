"""Catálogo de las tiendas en VTEX: Walmart y Maxipali (las dos son de Walmart México y Centroamérica).

- Lista de productos: el sitemap que anuncia su robots.txt (/sitemap.xml). Es un índice; los
  de productos son /sitemap/product-0.xml, product-1.xml... con unas 1000 páginas cada uno.
  Las páginas de producto terminan en "/p":
  https://www.walmart.co.cr/leche-dos-pinos-semidescremada-1-l-4/p
- Datos: la API pública del catálogo (ver ingestion/scrapers/vtex.py). Trae el código de barras
  (ean), la marca, la ruta de categorías, el color, el modelo, las imágenes y los precios. Su
  robots.txt no prohíbe ni las páginas de producto ni /api/.
- Por categoría (--categoria de obtener_productos): la búsqueda de la misma API, con la ruta
  de la categoría como sale en la URL de la tienda (walmart.co.cr/electronica/celulares). Trae
  50 productos completos por petición, así que no hace falta pedirlos uno por uno.
- Un producto puede tener varias presentaciones (items). Se toma la primera disponible.
"""

from dataclasses import replace
from urllib.parse import urlsplit

from products.barcodes import validar_codigo_barras

from ..scrapers import PrecioNoEncontrado, ProductoNoEncontrado
from ..scrapers import vtex as api
from .base import Ficha, ruta_de_busqueda, urls_del_sitemap


def _primero(valor):
    """Las especificaciones de VTEX vienen como listas: ["Apple"] -> "Apple"."""
    if isinstance(valor, list):
        valor = valor[0] if valor else ""
    return str(valor or "").strip()


def ruta_de_categorias(producto):
    """["/Electrónica/Celulares/APPLE/", "/Electrónica/Celulares/", ...] -> "Electrónica > Celulares > APPLE"."""
    rutas = producto.get("categories") or []
    if not rutas:
        return ""
    mas_larga = max(rutas, key=lambda r: r.count("/"))
    return " > ".join(parte.strip() for parte in mas_larga.split("/") if parte.strip())


def _item_principal(items):
    """La primera presentación disponible (o la primera, si ninguna lo está) y su oferta."""
    con_oferta = [(item, oferta) for item in items if (oferta := api.oferta_del_item(item)) is not None]
    return next(((i, o) for i, o in con_oferta if o.disponible), con_oferta[0] if con_oferta else (None, None))


def ficha_del_producto(url, producto):
    """La Ficha a partir de la respuesta de la API, o None si no tiene ninguna presentación con vendedor."""
    item, oferta = _item_principal(producto.get("items") or [])
    if item is None:
        return None
    codigos_invalidos = ()
    validacion = validar_codigo_barras(oferta.gtins[0]) if oferta.gtins else None
    if validacion is not None and not validacion:
        codigos_invalidos = ((oferta.gtins[0], validacion.motivo),)
        oferta = replace(oferta, gtins=())  # un código inválido no sirve para comparar (RF-38)
    imagenes = item.get("images") or []
    return Ficha(
        url=url,
        nombre=str(producto.get("productName") or item.get("name") or "").strip(),
        oferta=oferta,
        sku=str(item.get("itemId") or ""),
        # "Marca" viene escrita como se debe ("Dos Pinos"); "brand", en mayúsculas ("DOS PINOS").
        marca=_primero(producto.get("Marca")) or str(producto.get("brand") or "").strip(),
        modelo=_primero(producto.get("Modelo o serie del producto")),
        color=_primero(producto.get("Color")),
        categoria=ruta_de_categorias(producto),
        imagen_url=str(imagenes[0].get("imageUrl") or "") if imagenes else "",
        codigos_invalidos=codigos_invalidos,
    )


def subcategorias(arbol, ruta):
    """Las rutas de las subcategorías de esa ruta en el árbol de categorías de VTEX ([] si no tiene)."""
    for nodo in arbol:
        if ruta_de_busqueda(urlsplit(nodo.get("url") or "").path) == ruta:
            return [ruta_de_busqueda(urlsplit(hija.get("url") or "").path) for hija in nodo.get("children") or []]
        if hijas := subcategorias(nodo.get("children") or [], ruta):
            return hijas
    return []


class TiendaVtex:
    """Una tienda en VTEX. Tiene lo mismo que los módulos de las otras tiendas (NOMBRE, listar_urls...)."""

    PAUSA = 1.5
    POR_PAGINA = 50  # lo más que deja pedir la búsqueda de VTEX
    ULTIMO_DESDE = 2500  # la búsqueda no deja pasar de ahí: con más productos, se va por subcategoría
    NIVELES_DEL_ARBOL = 4

    def __init__(self, nombre, dominio):
        self.NOMBRE = nombre
        self.DOMINIO = dominio
        self.SITEMAP = f"https://{dominio}/sitemap.xml"

    def __repr__(self):
        return f"TiendaVtex({self.NOMBRE!r})"

    def es_url_de_producto(self, url):
        partes = urlsplit(url)
        return partes.netloc == self.DOMINIO and not partes.query and partes.path.endswith("/p") and partes.path != "/p"

    def listar_urls(self, http, avisar=None):
        """Las URLs de los sitemaps de productos, en su orden y sin repetir.

        Walmart tiene unos 39 sitemaps de productos (~1 minuto): cada 5 se llama a avisar(texto).
        """
        # los otros sitemaps son de marcas, categorías y páginas
        submapas = [s for s in urls_del_sitemap(http.texto(self.SITEMAP)) if "/sitemap/product-" in s]
        urls = []
        for numero, submapa in enumerate(submapas, 1):
            urls += urls_del_sitemap(http.texto(submapa))
            if avisar and (numero % 5 == 0 or numero == len(submapas)):
                avisar(f"sitemap {numero}/{len(submapas)} · {len(urls)} páginas hasta ahora")
        return list(dict.fromkeys(u for u in urls if self.es_url_de_producto(u)))

    def productos_de_categorias(self, http, categorias, avisar=None):
        """{URL de la página: producto de la API} de los productos de esas categorías.

        Cada categoría es su ruta en la tienda: "electronica" o "electronica/celulares". La
        búsqueda no deja ver más de unos 2550 productos: si una categoría tiene más, se busca en
        cada una de sus subcategorías.
        """
        productos = {}
        pendientes = [ruta for ruta in map(ruta_de_busqueda, categorias) if ruta]
        arbol = None
        while pendientes:
            ruta = pendientes.pop(0)
            # Si la última página que deja ver la búsqueda viene llena, puede que haya más.
            if len(self._pagina(http, ruta, self.ULTIMO_DESDE)) == self.POR_PAGINA:
                if arbol is None:
                    arbol = http.json(f"https://{self.DOMINIO}/api/catalog_system/pub/category/tree/{self.NIVELES_DEL_ARBOL}")
                if hijas := subcategorias(arbol, ruta):
                    if avisar:
                        avisar(f"{ruta}: tiene demasiados productos para una sola búsqueda; se busca en sus {len(hijas)} subcategorías")
                    pendientes[:0] = hijas
                    continue
                if avisar:
                    avisar(f"{ruta}: tiene demasiados productos y no tiene subcategorías: solo se leen los primeros")
            self._buscar(http, ruta, productos, avisar)
        return productos

    def _pagina(self, http, ruta, desde):
        pagina = http.json(
            f"https://{self.DOMINIO}/api/catalog_system/pub/products/search/{ruta}"
            f"?_from={desde}&_to={desde + self.POR_PAGINA - 1}&O=OrderByNameASC"  # en orden, para no saltarse ninguno
        )
        if not isinstance(pagina, list):
            raise PrecioNoEncontrado("La búsqueda de VTEX devolvió algo que no es una lista de productos.")
        return pagina

    def _buscar(self, http, ruta, productos, avisar):
        """Agrega a productos los de la categoría, página por página."""
        antes = len(productos)
        for desde in range(0, self.ULTIMO_DESDE + 1, self.POR_PAGINA):
            pagina = self._pagina(http, ruta, desde)
            for producto in pagina:
                if producto.get("linkText"):
                    productos.setdefault(f"https://{self.DOMINIO}/{producto['linkText']}/p", producto)
            if len(pagina) < self.POR_PAGINA:
                break
        if avisar:
            avisar(
                f"{ruta}: {len(productos) - antes} productos"
                if desde or pagina
                else f"{ruta}: ningún producto. ¿La ruta está bien? Es la de la URL de la categoría en la tienda, "
                "por ejemplo electronica/celulares"
            )

    def ficha_de_la_busqueda(self, url, producto):
        """La Ficha de un producto que ya vino en productos_de_categorias (sin pedirlo otra vez)."""
        return ficha_del_producto(url, producto)

    def obtener_ficha(self, url, http):
        """La ficha del producto, o None si la tienda ya no lo tiene en su catálogo."""
        try:
            producto = api.producto_de_la_api(url, http)
        except ProductoNoEncontrado:
            return None  # el sitemap a veces trae productos desactivados
        return ficha_del_producto(url, producto)


walmart = TiendaVtex("Walmart", "www.walmart.co.cr")
maxipali = TiendaVtex("Maxipali", "www.maxipali.co.cr")
