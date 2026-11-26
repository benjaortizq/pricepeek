"""Piezas comunes de los extractores: la oferta que devuelven, sus errores y el cliente HTTP."""

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

USER_AGENT = "Mozilla/5.0 (compatible; PricePeek/1.0; comparador de precios de Costa Rica)"


@dataclass(frozen=True)
class Oferta:
    """Lo que publica una tienda sobre un producto.

    Los precios van en colones enteros. Son None cuando la tienda no muestra precio
    (por ejemplo, porque el producto está agotado).
    """

    precio_lista: int | None  # sin descuento
    precio_final: int | None  # el que paga el cliente
    disponible: bool
    gtins: tuple[
        str, ...
    ] = ()  # códigos de barras que reporta la tienda (puede no reportar ninguno)

    @property
    def descuento(self):
        """Descuento con 2 decimales, como lo guarda la tabla prices (0.24 = 24 %)."""
        if (
            not self.precio_lista
            or self.precio_final is None
            or self.precio_final >= self.precio_lista
        ):
            return Decimal("0.00")
        descuento = 1 - Decimal(self.precio_final) / Decimal(self.precio_lista)
        return descuento.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def a_colones(valor):
    """19900.0, "19900" o Decimal -> 19900. Cero, vacío o inválido -> None."""
    try:
        colones = round(Decimal(str(valor)))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return int(colones) if colones > 0 else None


def convertir_a_colones(valor, moneda="CRC"):
    """Convierte un importe a colones usando las tasas configuradas en Django.

    ``TIPOS_CAMBIO_A_CRC`` expresa cuántos colones vale una unidad de cada
    moneda ISO 4217. No se asume una tasa para una moneda desconocida.
    """
    tasas = getattr(settings, "TIPOS_CAMBIO_A_CRC", {"CRC": Decimal("1")})
    codigo = (moneda or "CRC").upper()
    tasa = tasas.get(codigo)
    if tasa is None:
        return None
    try:
        colones = (Decimal(str(valor)) * Decimal(str(tasa))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    except (ArithmeticError, ValueError, TypeError):
        return None
    return int(colones) if colones > 0 else None


class ErrorExtraccion(Exception):
    """No se pudo saber el precio de la tienda."""


class ErrorDescarga(ErrorExtraccion):
    """La página no se pudo descargar (sin conexión, timeout, error del servidor...)."""

    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo  # el código HTTP, si la tienda respondió

    @property
    def es_rechazo(self):
        """403 o 429: la tienda no quiere atender más peticiones (por ahora)."""
        return self.codigo in (403, 429)


class ProductoNoEncontrado(ErrorExtraccion):
    """La tienda respondió que el producto ya no existe (404 o búsqueda vacía)."""


class PrecioNoEncontrado(ErrorExtraccion):
    """La página cargó, pero no trae el precio donde se esperaba: la tienda cambió su formato."""


class CodigoDistinto(ErrorExtraccion):
    """El producto de la página tiene otro código de barras que el guardado."""

    def __init__(self, mensaje, codigos=()):
        super().__init__(mensaje)
        self.codigos = tuple(
            codigos
        )  # los que publica la tienda en esa página


class ClienteHttp:
    """Descarga páginas con pausa entre peticiones, timeout y reintentos.

    La pausa es para no cargar los servidores de las tiendas: entre dos peticiones
    siempre pasan al menos `pausa` segundos.
    """

    def __init__(
        self, pausa=1.5, timeout=20, reintentos=2, espera_reintento=5
    ):
        self.pausa = pausa
        self.timeout = timeout
        self.reintentos = reintentos
        self.espera_reintento = espera_reintento
        self.sesion = requests.Session()
        self.sesion.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "es-CR,es-419;q=0.9,es;q=0.8,en;q=0.7",
                "Referer": "https://google.com",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            }
        )
        self._ultima_peticion = 0.0

    def texto(self, url):
        return self._obtener(url).text

    def json(self, url):
        respuesta = self._obtener(url)
        try:
            return respuesta.json()
        except ValueError:
            raise PrecioNoEncontrado("La tienda no devolvió JSON.") from None

    def _obtener(self, url):
        for intento in range(self.reintentos + 1):
            if intento:
                time.sleep(self.espera_reintento * intento)
            self._esperar_turno()
            try:
                respuesta = self.sesion.get(url, timeout=self.timeout)
            except RequestException as error:
                fallo = ErrorDescarga(
                    f"No se pudo conectar con la tienda ({error.__class__.__name__})."
                )
                continue
            if respuesta.status_code in (404, 410):
                raise ProductoNoEncontrado(
                    f"La tienda respondió {respuesta.status_code}: la página del producto ya no existe."
                )
            if respuesta.status_code < 400:
                return respuesta
            fallo = ErrorDescarga(
                f"La tienda respondió con el código {respuesta.status_code}.",
                respuesta.status_code,
            )
            if respuesta.status_code < 500 and respuesta.status_code != 429:
                raise fallo  # 401, 403...: reintentar no lo arregla
        raise fallo

    def _esperar_turno(self):
        espera = self._ultima_peticion + self.pausa - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._ultima_peticion = time.monotonic()
