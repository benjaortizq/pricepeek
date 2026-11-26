"""Pasar al catálogo los productos de las tiendas que todavía no están en él (SCRUM-56).

python manage.py crear_productos lo hace con todos los que se puedan, y en el admin está la
acción «Crear en el catálogo» para hacerlo con los que se elijan. Por cada producto se crea:

    brands            la marca de la tienda, si no existe ya (se compara sin mayúsculas, tildes ni signos)
    products          un producto por cada uno (agrupar variantes de un mismo producto queda a mano)
    product_variants  con el código de barras de la tienda, en 13 dígitos como el resto del catálogo
    product_images    la imagen de la tienda, como principal
    prices            el precio de la tienda (lo mismo que hace «Confirmar»)

Solo se crean los que traen un código de barras válido: es la llave de product_variants y,
sin él, el producto no se puede comparar entre tiendas (RF-38). Los de Monge no lo traen.
Si el código ya está en el catálogo, no se crea nada: solo se vincula el precio de la tienda.
Con --confirmar-desde, también se vinculan los sugeridos por el nombre con ese puntaje o más,
salvo que la tienda publique otro código de barras (es otra versión del producto) o que dos
páginas de la misma tienda se parezcan igual a la misma variante (no se sabe cuál es).
Con --min-tiendas N, solo se crean los que tienen ese código de barras en al menos N tiendas
distintas (los que ya están en el catálogo se vinculan igual). Monge no trae código, así que no cuenta.
La categoría sale de ingestion/categorias.py; si no hay regla para el tipo de producto, el
producto no se crea y aparece en el resumen.
"""

from dataclasses import dataclass

from django.db import connection, transaction
from django.utils import timezone
from django.utils.text import slugify

from products.barcodes import validar_codigo_barras
from products.models import (
    Brands,
    Categories,
    Currencies,
    Prices,
    ProductImages,
    Products,
    ProductVariants,
    Stores,
)

from .actualizacion import formas_del_codigo
from .categorias import categoria_para
from .emparejamiento import normalizar
from .models import StoreProduct
from .productos_tienda import MOTIVO_MISMO_CODIGO, NoSePuedeVincular, confirmar

Status = StoreProduct.Status
# Los que se pueden pasar al catálogo: los que no coinciden con nada y los que tenían una
# sugerencia que alguien rechazó. Además se vinculan solos los sugeridos por código de barras,
# que es una coincidencia exacta; los sugeridos por nombre se revisan a mano con «Confirmar».
CREABLES = (Status.NO_MATCH, Status.REJECTED)
MOTIVO_CREADO = "creado en el catálogo con los datos de la tienda"
# Marcas que en realidad dicen "sin marca" (Gollo usa "Commodity" para los genéricos).
MARCAS_SIN_NOMBRE = {
    "",
    "commodity",
    "generico",
    "generica",
    "sinmarca",
    "varios",
    "otros",
    "otro",
}

# Sugeridos por nombre que no se vinculan solos (se revisan en el admin).
OTRO_CODIGO = "sugerido por nombre, pero con otro código de barras"
EMPATE = "sugerido por nombre, empatado con otra página de la tienda"
OTRA_SE_PARECE_MAS = (
    "sugerido por nombre, pero otra página de la tienda se parece más"
)
EN_POCAS_TIENDAS = "en pocas tiendas"

CREADO = "creado"
VINCULADO = "vinculado"
OMITIDO = "omitido"


@dataclass(frozen=True)
class Resultado:
    tipo: str  # CREADO, VINCULADO u OMITIDO
    motivo: str = ""  # por qué se omitió, o la categoría / el gtin
    grupo: str = (
        ""  # para el resumen: "sin código de barras", "sin categoría"...
    )
    tipo_en_tienda: str = ""  # el tipo de producto que no tiene categoría
    marca_nueva: bool = False
    por_nombre: bool = False  # vinculado por el parecido del nombre, no por el código de barras


def _clave(texto):
    """ "Black + Decker", "black-decker" y "BLACK+DECKER" -> "blackdecker"."""
    return normalizar(texto).replace(" ", "").replace(".", "")


def gtin_del_catalogo(codigo):
    """El código como lo guarda product_variants: 13 dígitos (a un UPC-A se le pone un 0 adelante).

    Un GTIN-14 que no empieza con 0 se queda con sus 14 dígitos.
    """
    gtin = str(codigo).strip().zfill(14)
    return gtin[1:] if gtin.startswith("0") else gtin


class Catalogo:
    """Las categorías, marcas y códigos de barras del catálogo, para no consultarlos por cada producto."""

    def __init__(self):
        self.categorias = {_clave(c.name): c for c in Categories.objects.all()}
        self.marcas = {}
        self.slugs = set()
        for marca in Brands.objects.order_by("id"):
            self.anotar_marca(marca)
        self.codigos = {}  # cada forma del código (14 dígitos) -> el gtin de la variante
        for gtin in ProductVariants.objects.values_list("gtin", flat=True):
            self.anotar_codigo(gtin)
        self.paginas = {}  # (tienda, gtin) -> la página de esa tienda que ya se vinculó en esta corrida
        self.por_nombre = {}  # (tienda, gtin) -> la página que más se le parece, o None si hay empate
        self.tiendas = None  # cada forma del código (14 dígitos) -> las tiendas que lo publican

    def contar_tiendas(self):
        """Anota en qué tiendas aparece cada código de barras (en cualquier estado), para --min-tiendas."""
        self.tiendas = {}
        for tienda, codigos in StoreProduct.objects.values_list(
            "store_name", "barcodes"
        ):
            for codigo in codigos or ():
                if validar_codigo_barras(codigo):
                    for forma in formas_del_codigo(codigo):
                        self.tiendas.setdefault(forma, set()).add(tienda)

    def tiendas_con_codigo(self, codigos):
        """Las tiendas que publican alguno de esos códigos (hay que llamar antes a contar_tiendas)."""
        if self.tiendas is None:
            self.contar_tiendas()
        return set().union(
            *(
                self.tiendas.get(forma, set())
                for c in codigos
                for forma in formas_del_codigo(c)
            )
        )

    def anotar_marca(self, marca):
        self.marcas.setdefault(_clave(marca.name), marca)
        self.marcas.setdefault(_clave(marca.slug), marca)
        self.slugs.add(marca.slug)

    def anotar_codigo(self, gtin):
        for forma in formas_del_codigo(gtin):
            self.codigos.setdefault(forma, gtin)

    def variante_con_codigo(self, codigos):
        """El gtin de la variante del catálogo que tiene alguno de esos códigos, o None."""
        for codigo in codigos:
            for forma in formas_del_codigo(codigo):
                if forma in self.codigos:
                    return self.codigos[forma]
        return None

    def anotar_sugerencias(self, productos, desde):
        """Por cada variante, la página de cada tienda que más se le parece por el nombre.

        Si dos páginas empatan (la licuadora roja y la blanca del mismo modelo), no se sabe cuál
        es la de la variante: queda None y no se vincula ninguna.
        """
        puntajes = {}
        for producto in productos:
            if sugerido_por_nombre(producto, desde) and not _codigos_validos(
                producto
            ):
                clave = (producto.store_name, producto.suggested_gtin)
                puntajes.setdefault(clave, []).append(
                    (producto.score, producto.url)
                )
        for clave, opciones in puntajes.items():
            opciones.sort(reverse=True)
            empate = len(opciones) > 1 and opciones[0][0] == opciones[1][0]
            self.por_nombre[clave] = None if empate else opciones[0][1]

    def marca(self, nombre):
        """(marca, es_nueva). La nueva todavía no se guarda: se guarda junto con el producto."""
        clave = _clave(nombre)
        if clave in self.marcas:
            return self.marcas[clave], False
        base = slugify(nombre) or clave
        slug, numero = base, 2
        while slug in self.slugs:
            slug, numero = f"{base}-{numero}", numero + 1
        ahora = timezone.now()
        return Brands(
            name=nombre.strip(), slug=slug, created_at=ahora, updated_at=ahora
        ), True


TABLAS_DEL_CATALOGO = (
    Brands,
    Categories,
    Currencies,
    Stores,
    Products,
    ProductVariants,
    ProductImages,
    Prices,
)


def secuencias_atrasadas(modelos=TABLAS_DEL_CATALOGO):
    """[(tabla, secuencia, id más alto)] de las tablas cuyo contador de ids va por detrás de sus filas.

    Pasa cuando alguien inserta filas escribiendo el id a mano: Postgres no mueve el contador
    y la próxima fila nueva recibe un id que ya existe ("duplicate key ... _pkey"). Solo aplica
    a Postgres (las pruebas usan SQLite).
    """
    if connection.vendor != "postgresql":
        return []
    atrasadas = []
    with connection.cursor() as cursor:
        for modelo in modelos:
            tabla = modelo._meta.db_table
            cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [tabla])
            secuencia = cursor.fetchone()[0]
            if not secuencia:
                continue
            # ``secuencia`` viene de pg_get_serial_sequence, pero se cita como
            # identificador en vez de interpolarla directamente en SQL.
            partes_secuencia = secuencia.split(".")
            secuencia_citada = ".".join(
                connection.ops.quote_name(parte.strip('"'))
                for parte in partes_secuencia
            )
            cursor.execute(
                f"SELECT last_value, is_called FROM {secuencia_citada}"
            )
            ultimo, usado = cursor.fetchone()
            tabla_citada = connection.ops.quote_name(tabla)
            cursor.execute(f"SELECT MAX(id) FROM {tabla_citada}")
            maximo = cursor.fetchone()[0] or 0
            siguiente = ultimo + 1 if usado else ultimo
            if siguiente <= maximo:
                atrasadas.append((tabla, secuencia, maximo))
    return atrasadas


def arreglar_secuencias(atrasadas):
    """Pone cada contador en el id más alto de su tabla: no cambia ninguna fila."""
    with connection.cursor() as cursor:
        for _, secuencia, maximo in atrasadas:
            cursor.execute("SELECT setval(%s, %s)", [secuencia, maximo])


def sugerido_por_codigo(producto):
    return (
        producto.status == Status.SUGGESTED
        and producto.match_reason == MOTIVO_MISMO_CODIGO
    )


def sugerido_por_nombre(producto, desde):
    """Sugerido por el parecido del nombre (no por el código de barras) con al menos ese puntaje."""
    return (
        producto.status == Status.SUGGESTED
        and producto.match_reason != MOTIVO_MISMO_CODIGO
        and producto.score is not None
        and producto.score >= desde
    )


def _codigos_validos(producto):
    return [c for c in producto.barcodes if validar_codigo_barras(c)]


def crear_en_catalogo(
    producto, catalogo, guardar=True, confirmar_desde=None, min_tiendas=1
):
    """Pasa un producto de tienda al catálogo (o lo vincula, si su código ya está) y dice qué pasó.

    Con confirmar_desde, también vincula los sugeridos por nombre con al menos ese puntaje (para
    los empates, antes hay que llamar a catalogo.anotar_sugerencias). Con min_tiendas, solo crea
    los que tienen el código de barras en al menos esa cantidad de tiendas distintas.
    """
    por_nombre = confirmar_desde is not None and sugerido_por_nombre(
        producto, confirmar_desde
    )
    if (
        producto.status not in CREABLES
        and not sugerido_por_codigo(producto)
        and not por_nombre
    ):
        estado = producto.get_status_display().lower()
        return Resultado(
            OMITIDO,
            f"está como «{estado}»: se revisa a mano en el admin",
            "ya revisado o con sugerencia",
        )
    codigos = _codigos_validos(producto)
    if por_nombre and not codigos:
        return _confirmar_por_nombre(producto, catalogo, guardar)
    if not codigos:
        return Resultado(
            OMITIDO,
            "no tiene un código de barras válido",
            "sin código de barras",
        )

    existente = catalogo.variante_con_codigo(codigos)
    if existente is not None:
        return _vincular(producto, existente, catalogo, guardar)
    if por_nombre:
        return Resultado(
            OMITIDO,
            f"la tienda publica otro código de barras ({codigos[0]}) que la variante sugerida "
            f"({producto.suggested_gtin}): puede ser otra versión (otro color, otro tamaño)",
            OTRO_CODIGO,
        )

    if producto.final_price is None:
        return Resultado(OMITIDO, "la tienda no muestra precio", "sin precio")
    nombre_categoria = categoria_para(producto.category, producto.name)
    if nombre_categoria is None:
        tipo = producto.category or producto.name
        return Resultado(
            OMITIDO,
            f"no hay categoría para «{tipo}»",
            "sin categoría",
            tipo_en_tienda=tipo,
        )
    categoria = catalogo.categorias.get(_clave(nombre_categoria))
    if categoria is None:
        return Resultado(
            OMITIDO,
            f"no existe la categoría «{nombre_categoria}» en el catálogo",
            "sin categoría",
        )
    if _clave(producto.brand) in MARCAS_SIN_NOMBRE:
        return Resultado(
            OMITIDO, f"no tiene marca («{producto.brand}»)", "sin marca"
        )
    if min_tiendas > 1:
        tiendas = catalogo.tiendas_con_codigo(codigos)
        if len(tiendas) < min_tiendas:
            donde = ", ".join(sorted(tiendas))
            return Resultado(
                OMITIDO,
                f"solo está en {len(tiendas)} tienda(s) ({donde}): se piden {min_tiendas}",
                EN_POCAS_TIENDAS,
            )

    marca, marca_nueva = catalogo.marca(producto.brand)
    gtin = gtin_del_catalogo(codigos[0])
    if guardar:
        try:
            _crear(producto, gtin, marca, marca_nueva, categoria)
        except NoSePuedeVincular as error:
            return Resultado(OMITIDO, str(error), "no se pudo vincular")
    catalogo.anotar_marca(marca)
    catalogo.anotar_codigo(gtin)
    catalogo.paginas[(producto.store_name, gtin)] = producto.url
    return Resultado(CREADO, categoria.name, marca_nueva=marca_nueva)


@transaction.atomic
def _crear(producto, gtin, marca, marca_nueva, categoria):
    ahora = timezone.now()
    fechas = {"created_at": ahora, "updated_at": ahora}
    if marca_nueva:
        marca.save()
    nuevo = Products.objects.create(
        name=producto.name,
        description=None,
        brand=marca,
        category=categoria,
        **fechas,
    )
    variante = ProductVariants.objects.create(
        product=nuevo,
        gtin=gtin,
        name=producto.name,
        attributes={"color": producto.color} if producto.color else None,
        **fechas,
    )
    if producto.image_url:
        ProductImages.objects.create(
            variant=variante,
            image_url=producto.image_url,
            is_main=True,
            number_image=1,
            **fechas,
        )
    producto.suggested_gtin, producto.score, producto.match_reason = (
        gtin,
        100,
        MOTIVO_CREADO,
    )
    producto.save(
        update_fields=["suggested_gtin", "score", "match_reason", "updated_at"]
    )
    confirmar(producto)  # crea su fila en prices y lo deja como vinculado


def _confirmar_por_nombre(producto, catalogo, guardar):
    elegida = catalogo.por_nombre.get(
        (producto.store_name, producto.suggested_gtin), producto.url
    )
    if elegida is None:
        return Resultado(
            OMITIDO,
            "otra página de la tienda se parece igual a esa variante: no se sabe cuál es",
            EMPATE,
        )
    if elegida != producto.url:
        return Resultado(
            OMITIDO,
            f"otra página de la tienda se parece más a esa variante: {elegida}",
            OTRA_SE_PARECE_MAS,
        )
    return _vincular(
        producto, producto.suggested_gtin, catalogo, guardar, por_nombre=True
    )


def _vincular(producto, gtin, catalogo, guardar, por_nombre=False):
    if producto.status == Status.REJECTED and producto.suggested_gtin == gtin:
        return Resultado(
            OMITIDO,
            "alguien rechazó a mano esa variante del catálogo",
            "rechazado a mano",
        )
    otra = catalogo.paginas.get((producto.store_name, gtin))
    if otra and otra != producto.url:
        motivo = (
            "ya quedó vinculada a esa variante"
            if por_nombre
            else "tiene el mismo código"
        )
        return Resultado(
            OMITIDO,
            f"otra página de la tienda {motivo}: {otra}",
            "código repetido en la tienda",
        )
    if guardar:
        try:
            with transaction.atomic():
                if not por_nombre:  # el sugerido por nombre ya tiene su variante, puntaje y motivo
                    (
                        producto.suggested_gtin,
                        producto.score,
                        producto.match_reason,
                    ) = gtin, 100, MOTIVO_MISMO_CODIGO
                    producto.save(
                        update_fields=[
                            "suggested_gtin",
                            "score",
                            "match_reason",
                            "updated_at",
                        ]
                    )
                confirmar(producto)
        except NoSePuedeVincular as error:
            return Resultado(OMITIDO, str(error), "no se pudo vincular")
    catalogo.paginas[(producto.store_name, gtin)] = producto.url
    return Resultado(VINCULADO, gtin, por_nombre=por_nombre)
