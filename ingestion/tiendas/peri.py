"""Catálogo de Peri (peridomicilio.com): una tienda de Instaleap hecha con Next.js.

- No tiene sitemap ni robots.txt (esas rutas devuelven la página de inicio): se lee por categorías.
- Categorías: el árbol completo (categoryTree) viene en los datos de la página de inicio. La página
  de cada una es /ca/{slug}: https://www.peridomicilio.com/ca/panaderia/galletas/F2/C15
- Productos: la página de una categoría trae desde el servidor sus primeros 50 productos completos
  (nombre, precio, promociones, EAN, sku, marca, foto, disponibilidad y categorías), en los datos
  que Next.js manda con la página (self.__next_f.push). Las páginas siguientes las pide el navegador
  a la API de Instaleap, que aquí no se usa, y la URL no deja pedir otra página ni otro orden. Por eso
  se lee cada categoría y cada subcategoría: las que tienen hasta 50 productos quedan completas y de
  las más grandes solo salen los primeros 50 (el comando avisa cuáles).
- Cada producto tiene su página en /p/{slug}; actualizar_precios la lee con scrapers/ld_json.
- Precio: el mismo que publica esa página. Con una promoción activa de precio por unidad
  (benefit "unitPrice", como "₡340 c/u, máximo 3") se cobra el especial; las de paquete
  ("2 por ₡1720", "bundlePrice") no cambian el precio de una unidad. No publica un precio de lista
  aparte, así que se guarda el que se cobra, sin descuento (igual que scrapers/ld_json).
- Algunos EAN traen dos códigos en el mismo texto: "086581009403,7441163406064".
"""

import json
import re

from products.barcodes import validar_codigo_barras

from ..scrapers import ErrorDescarga, ErrorExtraccion, Oferta, PrecioNoEncontrado
from ..scrapers.base import a_colones
from .base import Ficha, ruta_de_busqueda

DOMINIO = "www.peridomicilio.com"
INICIO = f"https://{DOMINIO}/"
POR_PAGINA = 50  # los productos que trae desde el servidor la página de una categoría

# Next.js manda los datos de la página en bloques <script>self.__next_f.push([1,"…"])</script>.
_BLOQUE_NEXT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_DECODIFICADOR = json.JSONDecoder()


def datos_de_next(html):
    """El texto de los datos que Next.js manda con la página, ya sin escapar."""
    return "".join(json.loads(bloque) for bloque in _BLOQUE_NEXT.findall(html))


def _valores_despues_de(texto, clave):
    """Cada valor JSON que sigue a una aparición de la clave ('"categoryTree":', '"product":'...)."""
    for encontrada in re.finditer(re.escape(clave) + r"\s*", texto):
        try:
            valor, _ = _DECODIFICADOR.raw_decode(texto, encontrada.end())
        except ValueError:
            continue  # una referencia de Next.js ("$8b") u otra cosa que no es el valor
        yield valor


def arbol_de_categorias(html_de_inicio):
    """El árbol de categorías de la página de inicio: las de primer nivel, con sus subCategories."""
    for arbol in _valores_despues_de(datos_de_next(html_de_inicio), '"categoryTree":'):
        if isinstance(arbol, list) and arbol:
            return arbol
    raise PrecioNoEncontrado("La página de inicio no trae el árbol de categorías (categoryTree).")


def recorrer(arbol):
    """Todas las categorías del árbol, cada una antes que sus subcategorías."""
    for categoria in arbol:
        if isinstance(categoria, dict):
            if categoria.get("slug"):
                yield categoria
            yield from recorrer(categoria.get("subCategories") or [])


def ruta_de_la_categoria(categoria):
    """"/Panadería/Galletas" -> "panaderia/galletas": como sale en su URL, sin los códigos (F2/C15)."""
    return ruta_de_busqueda(categoria.get("categoryNamesPath") or "") or ruta_de_busqueda(categoria["slug"])


def url_de_la_categoria(categoria):
    return f"https://{DOMINIO}/ca/{categoria['slug']}"


def productos_de_la_pagina(html):
    """(productos, total) de la página de una categoría: los que trae y cuántos tiene la categoría."""
    texto = datos_de_next(html)
    productos = [
        producto
        for producto in _valores_despues_de(texto, '"product":')
        if isinstance(producto, dict) and producto.get("__typename") == "CatalogProductModel"
    ]
    total = next(
        (
            paginacion["total"].get("value")
            for paginacion in _valores_despues_de(texto, '"pagination":')
            if isinstance(paginacion, dict) and isinstance(paginacion.get("total"), dict)
        ),
        None,
    )
    return productos, total if isinstance(total, int) else len(productos)


def url_del_producto(producto):
    """La página del producto, o "" si no trae su slug."""
    slug = str(producto.get("slug") or "").strip()
    return f"https://{DOMINIO}/p/{slug}" if slug else ""


def precio_que_se_cobra(producto):
    """El precio de una unidad, como lo publica la página del producto (ver la explicación arriba)."""
    normal = a_colones(producto.get("price"))
    especiales = [
        a_colones((promocion.get("benefit") or {}).get("value"))
        for promocion in producto.get("promotions") or []
        if isinstance(promocion, dict)
        and promocion.get("isActive")
        and (promocion.get("benefit") or {}).get("type") == "unitPrice"
    ]
    especiales = [precio for precio in especiales if precio is not None and (normal is None or precio < normal)]
    return min(especiales) if especiales else normal


def codigos_de_barras(producto):
    """(válidos, inválidos con su motivo) de los EAN del producto, sin repetir."""
    validos, invalidos = [], []
    for texto in producto.get("ean") or []:
        for codigo in re.split(r"[\s,;]+", str(texto)):
            if not codigo.strip("0"):
                continue  # vacío o "0": no tiene código
            resultado = validar_codigo_barras(codigo)
            if resultado:
                validos.append(codigo)
            else:
                invalidos.append((codigo, resultado.motivo))
    return tuple(dict.fromkeys(validos)), tuple(dict.fromkeys(invalidos))


def categoria_del_producto(producto):
    """La más específica de sus categorías: "Panadería > Galletas"."""
    rutas = [
        categoria.get("categoryNamesPath")
        for categoria in producto.get("categoriesData") or []
        if isinstance(categoria, dict) and categoria.get("categoryNamesPath")
    ]
    if not rutas:
        return ""
    return " > ".join(parte for parte in max(rutas, key=lambda ruta: ruta.count("/")).split("/") if parte)


def ficha_del_producto(url, producto):
    precio = precio_que_se_cobra(producto)
    disponible = bool(producto.get("isAvailable"))
    if precio is None and disponible:
        raise PrecioNoEncontrado("Los datos del producto no traen el precio.")
    validos, invalidos = codigos_de_barras(producto)
    fotos = producto.get("photosUrl") or []
    return Ficha(
        url=url,
        nombre=" ".join(str(producto.get("name") or "").split()),
        oferta=Oferta(precio, precio, disponible, validos),  # un código inválido no sirve para comparar (RF-38)
        sku=str(producto.get("sku") or ""),
        marca=str(producto.get("brand") or "").strip(),
        categoria=categoria_del_producto(producto),
        imagen_url=str(fotos[0]) if fotos else "",
        codigos_invalidos=invalidos,
    )


class TiendaPeri:
    """No tiene listar_urls (no tiene sitemap): siempre se lee por productos_de_categorias."""

    NOMBRE = "Peri"
    PAUSA = 1.5

    def __repr__(self):
        return "TiendaPeri()"

    def _elegir(self, todas, categorias, avisar):
        """Las categorías pedidas, cada una con sus subcategorías (cada página trae solo 50 productos)."""
        elegidas = []
        for pedida in categorias:
            ruta = ruta_de_busqueda(pedida)
            categoria = next((c for c in todas if ruta in (ruta_de_la_categoria(c), ruta_de_busqueda(c["slug"]))), None)
            if categoria is None:
                avisar(f"{ruta}: no existe en Peri. Es la ruta de su URL sin los códigos, por ejemplo panaderia/galletas")
                continue
            elegidas += [categoria, *recorrer(categoria.get("subCategories") or [])]
        return elegidas

    def productos_de_categorias(self, http, categorias, avisar=None):
        """{URL de la página: producto} de esas categorías ("panaderia", "panaderia/galletas"), o de todas."""
        avisar = avisar or (lambda texto: None)
        todas = list(recorrer(arbol_de_categorias(http.texto(INICIO))))
        elegidas = self._elegir(todas, categorias, avisar) if categorias else todas
        elegidas = list({categoria["slug"]: categoria for categoria in elegidas}.values())  # sin repetir

        productos = {}
        incompletas = 0
        for categoria in elegidas:
            ruta = ruta_de_la_categoria(categoria)
            try:
                de_la_pagina, total = productos_de_la_pagina(http.texto(url_de_la_categoria(categoria)))
            except ErrorExtraccion as error:
                if isinstance(error, ErrorDescarga) and error.es_rechazo:
                    raise  # si la tienda nos rechaza, seguir pidiendo no lo arregla
                avisar(f"{ruta}: no se pudo leer ({error})")
                continue
            antes = len(productos)
            for producto in de_la_pagina:
                if url := url_del_producto(producto):
                    productos.setdefault(url, producto)
            nuevos = len(productos) - antes
            if total > len(de_la_pagina):
                incompletas += 1
                avisar(f"{ruta}: {nuevos} productos nuevos (tiene {total}; su página solo muestra {len(de_la_pagina)})")
            else:
                avisar(f"{ruta}: {nuevos} productos nuevos")
        if incompletas:
            avisar(
                f"{incompletas} categoría(s) con más productos de los que muestra su página: de esas solo salen "
                f"los primeros {POR_PAGINA} (los demás los carga el navegador desde la API de Instaleap, que no se usa)."
            )
        return productos

    def ficha_de_la_busqueda(self, url, producto):
        return ficha_del_producto(url, producto)


peri = TiendaPeri()
