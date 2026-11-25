"""Validación de enlaces para las imágenes compartidas del catálogo."""

from urllib.parse import urlsplit

# ``ProductImages.image_url`` es un ``TextField`` sin límite declarado en la
# base de datos. El portal limita las entradas para evitar URLs desmedidas.
IMAGEN_URL_MAX_LENGTH = 2000


class URLImagenInvalida(ValueError):
    """Indica que un enlace no cumple el formato permitido."""


def url_imagen_valida(url):
    """Devuelve ``True`` solo para URLs HTTP(S) con un host válido."""
    if not isinstance(url, str):
        return False

    if not url or len(url) > IMAGEN_URL_MAX_LENGTH:
        return False
    if any(caracter.isspace() for caracter in url):
        return False
    if any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in url):
        return False

    try:
        partes = urlsplit(url)
        # Acceder a ``port`` valida puertos inválidos, por ejemplo ``:abc``.
        _ = partes.port
        host = partes.hostname
    except ValueError:
        return False

    return partes.scheme.lower() in {"http", "https"} and bool(host)


def normalizar_urls_imagenes(urls):
    """Normaliza y valida una lista de URLs sin espacios sobrantes.

    Lanza ``URLImagenInvalida`` para un formato incorrecto y ``ValueError``
    cuando la misma URL aparece más de una vez.
    """
    normalizadas = []
    for url in urls:
        if not isinstance(url, str):
            raise URLImagenInvalida
        if not url_imagen_valida(url):
            raise URLImagenInvalida
        normalizadas.append(url)

    if len(normalizadas) != len(set(normalizadas)):
        raise ValueError("URL duplicada")

    return normalizadas
