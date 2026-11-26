"""Importación CSV del catálogo de una empresa, con errores por fila."""

import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from core.translations import translate_text_lazy
from products.barcodes import validar_codigo_barras
from products.models import Brands, Categories, Prices, ProductVariants

from .forms import (
    PRECIO_ENTEROS_MAXIMO,
    PRECIO_ENTEROS_MINIMO,
    analizar_atributos_json,
    normalizar_gtin,
)
from .imagenes import URLImagenInvalida, normalizar_urls_imagenes
from .services import ErrorEmpresa, crear_precio_empresa, editar_precio_empresa

COLUMNAS = [
    "gtin",
    "product_name",
    "variant_name",
    "brand_name",
    "category_name",
    "attributes",
    "price",
    "discount",
    "is_available",
    "product_web_url",
    "image_urls",
]


@dataclass
class ResultadoFila:
    linea: int
    gtin: str = ""
    importado: bool = False
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    price_id: int | None = None


def _booleano(valor):
    texto = str(valor or "").strip().lower()
    if not texto:
        return True
    if texto in {"1", "true", "sí", "si", "yes", "disponible", "activo"}:
        return True
    if texto in {"0", "false", "no", "no disponible", "inactivo"}:
        return False
    raise ValueError


def _url_valida(url):
    if not url:
        return True
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    return partes.scheme in {"http", "https"} and bool(partes.netloc)


def _decimal(valor):
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        return Decimal("0.00")
    return Decimal(texto)


def _texto(valores, nombre):
    return str(valores.get(nombre) or "").strip()


def _tiene_urls_imagenes_csv(valores):
    for nombre, valor in valores.items():
        es_columna = nombre in {"image_urls", "image_url"} or re.fullmatch(
            r"image_url_\d+", str(nombre or "")
        )
        if es_columna and str(valor or "").strip():
            return True
    return False


def _urls_imagenes_csv(valores):
    """Lee URLs separadas por ``|`` y acepta columnas ``image_url_N``."""
    partes = []
    texto = str(valores.get("image_urls") or valores.get("image_url") or "")
    if texto:
        partes.extend(re.split(r"[|\r\n]+", texto))

    numeradas = []
    for nombre in valores:
        coincidencia = re.fullmatch(r"image_url_(\d+)", str(nombre or ""))
        if coincidencia:
            numeradas.append(
                (int(coincidencia.group(1)), str(valores[nombre] or ""))
            )
    for _, url in sorted(numeradas):
        if url:
            partes.append(url)

    urls = [url for url in partes if url != ""]
    try:
        return normalizar_urls_imagenes(urls)
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


def procesar_csv(archivo, store, usuario=None):
    """Procesa cada fila de forma independiente y devuelve su resultado."""
    try:
        contenido = archivo.read().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El archivo CSV debe estar codificado en UTF-8."
            )
        ) from error

    lector = csv.DictReader(io.StringIO(contenido))
    if not lector.fieldnames:
        raise ErrorEmpresa(translate_text_lazy("El archivo CSV está vacío."))

    encabezados_originales = [
        str(nombre or "").strip().lower() for nombre in lector.fieldnames
    ]
    if len(encabezados_originales) != len(set(encabezados_originales)):
        raise ErrorEmpresa(
            translate_text_lazy("El archivo CSV tiene encabezados duplicados.")
        )

    # ``DictReader`` conserva los nombres originales. Se normalizan para
    # aceptar espacios y mayúsculas sin romper la lectura de los valores.
    lector.fieldnames = encabezados_originales
    encabezados = set(encabezados_originales)
    faltantes = [
        columna for columna in ("gtin", "price") if columna not in encabezados
    ]
    if faltantes:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El archivo CSV no tiene las columnas obligatorias: {columnas}."
            ).format(columnas=", ".join(faltantes))
        )

    resultados = []
    vistos = set()
    for valores in lector:
        linea = lector.line_num
        resultado = ResultadoFila(linea=linea)
        try:
            _procesar_fila(valores, store, resultado, vistos, usuario)
        except ErrorEmpresa as error:
            resultado.errores.append(str(error))
        except (InvalidOperation, TypeError, ValueError):
            resultado.errores.append(
                str(
                    translate_text_lazy(
                        "La fila contiene un valor numérico o booleano inválido."
                    )
                )
            )
        resultados.append(resultado)
    return resultados


def _procesar_fila(valores, store, resultado, vistos, usuario=None):
    codigo = _texto(valores, "gtin")
    resultado.gtin = codigo
    variante_existente = None
    if codigo:
        candidatos = dict.fromkeys((codigo, normalizar_gtin(codigo)))
        for candidato in candidatos:
            variante_existente = ProductVariants.objects.filter(
                gtin=candidato
            ).first()
            if variante_existente is not None:
                break

    if variante_existente is not None:
        gtin = variante_existente.gtin
    else:
        validacion = validar_codigo_barras(codigo)
        if not validacion:
            raise ErrorEmpresa(translate_text_lazy(validacion.motivo))
        gtin = normalizar_gtin(validacion.codigo)

    texto_precio = _texto(valores, "price")
    if not texto_precio:
        raise ErrorEmpresa(translate_text_lazy("El precio es obligatorio."))
    try:
        precio = int(texto_precio)
    except ValueError as error:
        raise ErrorEmpresa(
            translate_text_lazy("El precio debe ser un número entero.")
        ) from error
    if precio < PRECIO_ENTEROS_MINIMO or precio > PRECIO_ENTEROS_MAXIMO:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El precio está fuera del rango de enteros permitido."
            )
        )

    try:
        descuento = _decimal(valores.get("discount"))
    except InvalidOperation as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El descuento debe ser un decimal entre 0 y 1."
            )
        ) from error
    if descuento < 0 or descuento > 1:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El descuento debe ser un decimal entre 0 y 1."
            )
        )

    try:
        disponible = _booleano(valores.get("is_available"))
    except ValueError as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La disponibilidad debe ser verdadero o falso."
            )
        ) from error

    url = _texto(valores, "product_web_url")
    if not _url_valida(url):
        raise ErrorEmpresa(
            translate_text_lazy(
                "El enlace debe comenzar con http:// o https://."
            )
        )

    atributos_texto = _texto(valores, "attributes")
    try:
        atributos = analizar_atributos_json(atributos_texto)
    except ValueError as error:
        raise ErrorEmpresa(
            translate_text_lazy(
                "Las características deben ser un objeto JSON válido."
            )
        ) from error

    variante = (
        variante_existente or ProductVariants.objects.filter(gtin=gtin).first()
    )
    producto_datos = None
    urls_imagenes = []
    if variante is None:
        nombre_producto = _texto(valores, "product_name")
        nombre_variante = _texto(valores, "variant_name")
        if not nombre_producto or not nombre_variante:
            raise ErrorEmpresa(
                translate_text_lazy(
                    "Para un GTIN nuevo se necesitan product_name y variant_name."
                )
            )
        urls_imagenes = _urls_imagenes_csv(valores)
        if not urls_imagenes:
            raise ErrorEmpresa(
                translate_text_lazy(
                    "Debe agregar al menos un enlace de imagen para un GTIN nuevo."
                )
            )
        marca = _marca(valores.get("brand_name"))
        categoria = _categoria(valores.get("category_name"))
        producto_datos = {
            "product_name": nombre_producto,
            "variant_name": nombre_variante,
            "brand": marca,
            "category": categoria,
            "description": "",
            "attributes": atributos,
        }
    elif _tiene_urls_imagenes_csv(valores):
        resultado.avisos.append(
            str(
                translate_text_lazy(
                    "Las imágenes de un GTIN existente no se modificaron; se gestionan en su pantalla de detalle."
                )
            )
        )

    if precio < 0:
        precio = None
        disponible = False
        resultado.avisos.append(
            str(
                translate_text_lazy(
                    "El precio era inferior a 0; se quitó y el producto se marcó como no disponible."
                )
            )
        )

    if gtin in vistos:
        raise ErrorEmpresa(
            translate_text_lazy(
                "El GTIN ya aparece en otra fila de este archivo."
            )
        )

    datos_precio = {
        "price": precio,
        "discount": descuento,
        "is_available": disponible,
        "product_web_url": url,
    }
    existente = Prices.objects.filter(
        id_store_id=store.pk, gtin_id=gtin
    ).first()
    if existente is not None:
        creado = editar_precio_empresa(
            store,
            existente.pk,
            datos_precio,
            usuario=usuario,
        )
    else:
        creado = crear_precio_empresa(
            store,
            gtin,
            datos_precio,
            producto_datos=producto_datos,
            image_urls=urls_imagenes,
        )
    resultado.importado = True
    resultado.price_id = creado.pk
    vistos.add(gtin)


def _marca(valor):
    nombre = str(valor or "").strip()
    if not nombre:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La marca '{nombre}' no existe en el catálogo."
            ).format(nombre=nombre)
        )
    coincidencias = list(
        Brands.objects.filter(name__iexact=nombre).order_by("id")[:2]
    )
    if not coincidencias:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La marca '{nombre}' no existe en el catálogo."
            ).format(nombre=nombre)
        )
    if len(coincidencias) > 1:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La marca '{nombre}' coincide con más de una marca del catálogo."
            ).format(nombre=nombre)
        )
    return coincidencias[0]


def _categoria(valor):
    nombre = str(valor or "").strip()
    if not nombre:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La categoría '{nombre}' no existe en el catálogo."
            ).format(nombre=nombre)
        )
    coincidencias = list(
        Categories.objects.filter(name__iexact=nombre).order_by("id")[:2]
    )
    if not coincidencias:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La categoría '{nombre}' no existe en el catálogo."
            ).format(nombre=nombre)
        )
    if len(coincidencias) > 1:
        raise ErrorEmpresa(
            translate_text_lazy(
                "La categoría '{nombre}' coincide con más de una categoría del catálogo."
            ).format(nombre=nombre)
        )
    return coincidencias[0]
