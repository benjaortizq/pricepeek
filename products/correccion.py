"""«¿Quiso decir…?»: corregir lo que se escribió mal en la búsqueda («sansun» -> «samsung»).

Si la búsqueda no encuentra nada, cada palabra se cambia por la más parecida del vocabulario
del catálogo (las palabras de los nombres y las marcas). "Parecida" se mide con la distancia
de Levenshtein: cuántos cambios de una letra (cambiar, agregar o quitar) hay que hacer para
pasar de una palabra a la otra. «sansun» -> «samsung» son 2: la n por m y agregar la g. Si
hay varias igual de cerca, gana la que más se parece por trigramas (pedazos de 3 letras, como
pg_trgm) y, si siguen empatadas, la que más sale en el catálogo.

Se hace de una de dos formas, con las mismas reglas:
- En Postgres con las extensiones fuzzystrmatch (levenshtein) y pg_trgm (similarity), que
  activa la migración products/0002: la base arma el vocabulario y lo compara, siempre al día.
- Si no están (las pruebas usan SQLite, o la migración no se ha corrido), en memoria con un
  árbol BK (ver ArbolBK). Ese vocabulario se arma la primera vez que hace falta y se vuelve a
  armar una vez al día, porque el catálogo cambia cuando se corre crear_productos.
"""

import threading
import time
from collections import Counter

from django.db import connection

from .busqueda import palabra_normalizada
from .models import Brands, Products

VIGENCIA_DEL_VOCABULARIO = 24 * 60 * 60  # segundos: un día


def levenshtein(a, b):
    """Cuántos cambios de una letra (cambiar, agregar o quitar) hay entre a y b."""
    if len(a) < len(b):
        a, b = b, a
    anterior = list(range(len(b) + 1))  # de "" a cada prefijo de b
    for i, letra_a in enumerate(a, 1):
        actual = [i]
        for j, letra_b in enumerate(b, 1):
            actual.append(
                min(
                    anterior[j] + 1,  # quitar letra_a
                    actual[j - 1] + 1,  # agregar letra_b
                    anterior[j - 1]
                    + (
                        letra_a != letra_b
                    ),  # cambiar (o dejar, si son iguales)
                )
            )
        anterior = actual
    return anterior[-1]


def trigramas(palabra):
    """Los pedazos de 3 letras de la palabra, como los arma pg_trgm: "sal" -> {"  s", " sa", "sal", "al "}."""
    relleno = f"  {palabra} "
    return {relleno[i : i + 3] for i in range(len(relleno) - 2)}


def similitud(a, b):
    """Qué fracción de los trigramas comparten (de 0 a 1), como similarity() de pg_trgm."""
    de_a, de_b = trigramas(a), trigramas(b)
    return len(de_a & de_b) / len(de_a | de_b)


class _Nodo:
    __slots__ = ("palabra", "hijos")

    def __init__(self, palabra):
        self.palabra = palabra
        self.hijos = {}  # distancia a esta palabra -> nodo


class ArbolBK:
    """Árbol BK (Burkhard-Keller): encuentra rápido las palabras a pocos cambios de otra.

    Cada hijo cuelga de su padre según la distancia entre los dos. Al buscar con tolerancia t,
    si la palabra buscada está a distancia d de un nodo, por la desigualdad triangular solo
    pueden servir los hijos colgados entre d - t y d + t: las otras ramas se descartan enteras
    sin mirarlas. Por eso la distancia tiene que ser una métrica, como la de Levenshtein.
    """

    def __init__(self, palabras=(), distancia=levenshtein):
        self.distancia = distancia
        self.raiz = None
        self.cantidad = 0
        for palabra in palabras:
            self.agregar(palabra)

    def __len__(self):
        return self.cantidad

    def agregar(self, palabra):
        if self.raiz is None:
            self.raiz, self.cantidad = _Nodo(palabra), 1
            return
        nodo = self.raiz
        while True:
            distancia = self.distancia(palabra, nodo.palabra)
            if distancia == 0:
                return  # ya estaba
            if distancia not in nodo.hijos:
                nodo.hijos[distancia] = _Nodo(palabra)
                self.cantidad += 1
                return
            nodo = nodo.hijos[distancia]

    def buscar(self, palabra, tolerancia):
        """[(distancia, palabra)] de las que están a tolerancia cambios o menos."""
        encontradas = []
        pendientes = [self.raiz] if self.raiz else []
        while pendientes:
            nodo = pendientes.pop()
            distancia = self.distancia(palabra, nodo.palabra)
            if distancia <= tolerancia:
                encontradas.append((distancia, nodo.palabra))
            pendientes.extend(
                hijo
                for colgado, hijo in nodo.hijos.items()
                if distancia - tolerancia <= colgado <= distancia + tolerancia
            )
        return encontradas


def tolerancia_para(palabra):
    """Cuántos cambios se aceptan: ninguno en palabras de 3 letras o menos (hay demasiadas
    parecidas) ni en las que tienen números (256GB no es un error), 1 hasta 5 letras y 2 desde 6."""
    if len(palabra) <= 3 or not palabra.isalpha():
        return 0
    return 1 if len(palabra) <= 5 else 2


class Vocabulario:
    """Las palabras de unos textos (nombres y marcas), cuántas veces sale cada una y su árbol BK."""

    def __init__(self, textos):
        self.frecuencia = Counter(
            palabra
            for texto in textos
            for palabra in map(palabra_normalizada, str(texto or "").split())
            if len(palabra) >= 3 and palabra.isalpha()
        )
        self.arbol = ArbolBK(
            palabra for palabra, _ in self.frecuencia.most_common()
        )

    def mas_parecidas(self, buscadas):
        """{palabra buscada: la más parecida del vocabulario} para {palabra: tolerancia}."""
        mejores = {}
        for palabra, tolerancia in buscadas.items():
            candidatas = self.arbol.buscar(palabra, tolerancia)
            if candidatas:
                _, mejores[palabra] = min(
                    candidatas,
                    key=lambda c: (
                        c[0],
                        -similitud(c[1], palabra),
                        -self.frecuencia[c[1]],
                        c[1],
                    ),
                )
        return mejores

    def corregir(self, texto):
        """El texto con cada palabra mal escrita cambiada por la más parecida, o None si no cambia nada."""
        return corregir_texto(texto, self.mas_parecidas)


def corregir_texto(texto, mas_parecidas):
    """El texto con cada palabra cambiada por la más parecida del catálogo, o None si no cambia nada.

    mas_parecidas({palabra normalizada: tolerancia}) -> {palabra: la más parecida}; la que ya
    está en el catálogo es la más parecida a sí misma (distancia 0), y no se cambia.
    """
    palabras = texto.split()
    buscadas = {}
    for palabra in map(palabra_normalizada, palabras):
        if tolerancia := tolerancia_para(palabra):
            buscadas[palabra] = tolerancia
    mejores = mas_parecidas(buscadas) if buscadas else {}
    corregidas = [
        mejores.get(palabra_normalizada(palabra), palabra)
        for palabra in palabras
    ]
    corregidas = [
        c if c != palabra_normalizada(p) else p
        for c, p in zip(corregidas, palabras)
    ]
    return " ".join(corregidas) if corregidas != palabras else None


# El vocabulario y la comparación hechos por Postgres. Las palabras se normalizan como
# palabra_normalizada: en minúscula, sin tildes, solo letras y números, de 3 letras o más.
_TILDES, _SIN_TILDES = "áàäâãéèëêíìïîóòöôõúùüûñç", "aaaaaeeeeiiiiooooouuuunc"
_SQL_MAS_PARECIDAS = """
WITH textos AS (
    SELECT p.name AS texto FROM {productos} p
    UNION ALL
    SELECT b.name FROM {productos} p JOIN {marcas} b ON b.id = p.{marca}
),
vocabulario AS (
    SELECT palabra, count(*) AS veces
    FROM textos,
        LATERAL regexp_split_to_table(translate(lower(texto), %s, %s), '[\\s\\u00a0]+') AS crudo,
        LATERAL (SELECT regexp_replace(crudo, '[^a-z0-9]', '', 'g') AS palabra) AS limpia
    WHERE palabra ~ '^[a-z]{{3,}}$'
    GROUP BY palabra
)
SELECT DISTINCT ON (buscada.palabra) buscada.palabra, v.palabra
FROM unnest(%s::text[], %s::int[]) AS buscada(palabra, tolerancia)
JOIN vocabulario v
    ON levenshtein_less_equal(v.palabra, buscada.palabra, buscada.tolerancia) <= buscada.tolerancia
ORDER BY buscada.palabra, levenshtein(v.palabra, buscada.palabra),
    similarity(v.palabra, buscada.palabra) DESC, v.veces DESC, v.palabra
"""


def mas_parecidas_en_postgres(buscadas):
    """Lo mismo que Vocabulario.mas_parecidas, pero lo calcula Postgres (fuzzystrmatch y pg_trgm)."""
    sql = _SQL_MAS_PARECIDAS.format(
        productos=connection.ops.quote_name(Products._meta.db_table),
        marcas=connection.ops.quote_name(Brands._meta.db_table),
        marca=connection.ops.quote_name(
            Products._meta.get_field("brand").column
        ),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [_TILDES, _SIN_TILDES, list(buscadas), list(buscadas.values())],
        )
        return dict(cursor.fetchall())


_con_extensiones = None


def hay_extensiones():
    """Si la base es Postgres y tiene fuzzystrmatch y pg_trgm (se revisa una vez)."""
    global _con_extensiones
    if _con_extensiones is None:
        _con_extensiones = False
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_extension WHERE extname IN ('fuzzystrmatch', 'pg_trgm')"
                )
                _con_extensiones = cursor.fetchone()[0] == 2
    return _con_extensiones


_vocabulario = None
_armado_en = 0.0
_candado = threading.Lock()


def vocabulario_del_catalogo():
    """El vocabulario de los nombres y las marcas del catálogo; se vuelve a armar una vez al día."""
    global _vocabulario, _armado_en
    with _candado:
        if (
            _vocabulario is None
            or time.monotonic() - _armado_en > VIGENCIA_DEL_VOCABULARIO
        ):
            textos = Products.objects.values_list("name", "brand__name")
            _vocabulario = Vocabulario(
                texto for fila in textos for texto in fila
            )
            _armado_en = time.monotonic()
        return _vocabulario


def olvidar_vocabulario():
    """Para que la próxima corrección lo vuelva a armar y vuelva a revisar las extensiones (lo usan las pruebas)."""
    global _vocabulario, _con_extensiones
    with _candado:
        _vocabulario = None
        _con_extensiones = None


def corregir_busqueda(texto):
    """«sansun» -> «samsung», según el catálogo; None si no hay nada que corregir."""
    if hay_extensiones():
        return corregir_texto(texto, mas_parecidas_en_postgres)
    return vocabulario_del_catalogo().corregir(texto)
