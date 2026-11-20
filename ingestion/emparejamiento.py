"""Sugerencias de coincidencia entre un producto de una tienda y las variantes del catálogo.

Sirve para tiendas que no publican el código de barras (Monge). Se compara marca, modelo,
capacidad y color, por ejemplo:
    Monge:    "Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB" (marca Apple, color Negro)
    Catálogo: "iPhone 17- 256GB Negro" (marca Apple)
La sugerencia siempre la confirma una persona en el admin.

Si comparten un código de modelo (RS27T5200S9) el puntaje es 100. Si no, primero se
descarta lo que se contradice (otra marca, otro color, otra capacidad, "Pro" de un lado
y no del otro, un número de modelo distinto) y lo que queda recibe un puntaje de 0 a 100.
"""

import re
import unicodedata
from dataclasses import dataclass

PUNTAJE_PARA_SUGERIR = 70

COLORES = {
    "negro", "blanco", "azul", "gris", "plata", "plateado", "silver", "dorado", "oro", "rojo", "verde",
    "morado", "lavanda", "rosado", "rosa", "naranja", "amarillo", "celeste", "cafe", "beige", "grafito",
}
# Palabras que distinguen un modelo de otro de la misma línea (iPhone 17 vs iPhone 17 Pro).
# "combo": un combo (celular + audífonos) nunca es el mismo producto que el celular solo.
MODIFICADORES = {"pro", "max", "plus", "ultra", "mini", "air", "lite", "fe", "neo", "prime", "combo"}
# Si la tienda dice un número de modelo que el catálogo no dice ("Redmi Note 17" contra
# "Redmi Note"), puede ser otro modelo: se resta esto al puntaje.
CASTIGO_NUMERO_DE_MAS = 15
RELLENO = {
    "celular", "telefono", "smartphone", "de", "del", "con", "y", "el", "la", "los", "las", "para", "en",
    "ram", "color", "5g", "4g", "lte", "dual", "sim", "x", "-",
}
UNIDADES = {
    "tb": "tb", "gb": "gb", "ml": "ml", "l": "l", "lt": "l", "lts": "l", "litro": "l", "litros": "l",
    "g": "g", "gr": "g", "gramos": "g", "kg": "kg", "cp": "cp", "pies": "cp", "w": "w", "mah": "mah",
    "pulgadas": "pulg", "pulg": "pulg",
}
_CAPACIDAD = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s?(" + "|".join(sorted(UNIDADES, key=len, reverse=True)) + r")\b")


def normalizar(texto):
    """Minúsculas, sin tildes y solo letras, números y puntos decimales."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()  # quita tildes: í -> i, ñ -> n
    texto = re.sub(r"(\d),(\d)", r"\1.\2", texto)
    texto = re.sub(r"[^a-z0-9.]+", " ", texto)
    texto = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", texto)
    return " ".join(texto.split())


@dataclass(frozen=True)
class Rasgos:
    palabras: frozenset  # sin relleno, colores ni capacidades
    capacidades: frozenset  # {"8gb", "256gb"}
    colores: frozenset
    modificadores: frozenset
    numeros: frozenset  # palabras con dígitos: identifican el modelo ("17", "s26", "rs27t5200s9")

    @property
    def codigos(self):
        """Códigos de modelo: letras y números, de 6 caracteres o más."""
        return {n for n in self.numeros if len(n) >= 6 and re.search(r"[a-z]", n)}


def rasgos(*textos):
    # "Pro+" es otro modelo que "Pro"; pero en "8GB + 256GB" o "Black + Decker" el "+" solo separa.
    texto = re.sub(r"(?<=[^\s+])\+", " plus ", " ".join(t for t in textos if t))
    texto = normalizar(texto)
    texto = re.sub(r"\b[2-5]g\b", " ", texto)  # "5G" es la red del celular, no 5 gramos
    capacidades = frozenset(f"{numero}{UNIDADES[unidad]}" for numero, unidad in _CAPACIDAD.findall(texto))
    palabras = set(_CAPACIDAD.sub(" ", texto).split()) - RELLENO
    colores = palabras & COLORES
    palabras -= colores
    return Rasgos(
        palabras=frozenset(palabras),
        capacidades=capacidades,
        colores=frozenset(colores),
        modificadores=frozenset(palabras & MODIFICADORES),
        numeros=frozenset(p for p in palabras if re.search(r"\d", p)),
    )


def _almacenamiento(capacidades):
    """La capacidad más grande en GB (en un celular, el almacenamiento; la otra es la RAM)."""
    gigas = [float(c[:-2]) * (1024 if c.endswith("tb") else 1) for c in capacidades if c.endswith(("gb", "tb"))]
    return max(gigas) if gigas else None


def comparar(tienda, catalogo, marca_tienda="", marca_catalogo=""):
    """(puntaje de 0 a 100, motivo) de que el producto de la tienda sea esa variante del catálogo."""
    marca_t, marca_c = normalizar(marca_tienda), normalizar(marca_catalogo)
    misma_marca = bool(marca_t) and (marca_t == marca_c or marca_t in catalogo.palabras)
    if marca_t and marca_c and not misma_marca:
        return 0, f"otra marca ({marca_tienda} / {marca_catalogo})"
    codigos = tienda.codigos & catalogo.codigos
    if codigos:
        return 100, f"mismo modelo {', '.join(sorted(codigos)).upper()}"
    if tienda.modificadores != catalogo.modificadores:
        distintos = sorted(tienda.modificadores ^ catalogo.modificadores)
        return 0, f"otro modelo ({', '.join(distintos)})"
    faltan = catalogo.numeros - tienda.palabras
    if faltan:
        return 0, f"no dice {', '.join(sorted(faltan))}"
    almacenamiento_t, almacenamiento_c = _almacenamiento(tienda.capacidades), _almacenamiento(catalogo.capacidades)
    if almacenamiento_t and almacenamiento_c and almacenamiento_t != almacenamiento_c:
        return 0, "otra capacidad"
    otras_t = {c for c in tienda.capacidades if not c.endswith(("gb", "tb"))}
    otras_c = {c for c in catalogo.capacidades if not c.endswith(("gb", "tb"))}
    if otras_t and otras_c and not otras_t & otras_c:
        return 0, "otro tamaño"
    if tienda.colores and catalogo.colores and not tienda.colores & catalogo.colores:
        return 0, "otro color"

    motivos = []
    cobertura = len(catalogo.palabras & tienda.palabras) / len(catalogo.palabras) if catalogo.palabras else 0
    puntaje = 50 * cobertura
    if misma_marca:
        puntaje += 20
        motivos.append(f"marca {marca_tienda}")
    if catalogo.palabras & tienda.palabras:
        motivos.append(" ".join(sorted(catalogo.palabras & tienda.palabras)))
    capacidades = tienda.capacidades & catalogo.capacidades
    if capacidades:
        puntaje += 15
        motivos.append(", ".join(sorted(c.upper() for c in capacidades)))
    colores = tienda.colores & catalogo.colores
    if colores:
        puntaje += 15
        motivos.append(", ".join(sorted(colores)))
    de_mas = tienda.numeros - tienda.codigos - catalogo.numeros  # un MPN de más (MG6J4BE) no es otro modelo
    if de_mas:
        puntaje -= CASTIGO_NUMERO_DE_MAS
        motivos.append(f"el catálogo no dice {', '.join(sorted(de_mas))}")
    return max(round(puntaje), 0), " · ".join(motivos)


@dataclass(frozen=True)
class Candidata:
    """Una variante del catálogo, con sus rasgos ya calculados."""

    variante: object
    rasgos: Rasgos
    marca: str


def candidatas(variantes):
    """Prepara las variantes (con product__brand cargado) para compararlas muchas veces."""
    return [Candidata(v, rasgos(v.name), v.product.brand.name) for v in variantes]


def mejor_coincidencia(ficha_rasgos, marca, candidatas_):
    """(candidata, puntaje, motivo) de la mejor coincidencia con puntaje suficiente, o None."""
    mejor = None
    for candidata in candidatas_:
        puntaje, motivo = comparar(ficha_rasgos, candidata.rasgos, marca, candidata.marca)
        if puntaje >= PUNTAJE_PARA_SUGERIR and (mejor is None or puntaje > mejor[1]):
            mejor = (candidata, puntaje, motivo)
    return mejor
