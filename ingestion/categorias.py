"""Equivalencias entre el tipo de producto que publica una tienda y las categorías del catálogo.

El catálogo tiene 4 categorías (tabla categories). Cada regla es cómo empieza el tipo de
producto de la tienda, sin mayúsculas ni tildes. Gana la regla más larga: "olla arrocera"
(Electrodomésticos) le gana a "olla" (Artículos para el hogar). Cada palabra de la regla
acepta también su plural y su femenino: "audifono" sirve para "Audífonos" y "freidor" para
"Freidora".

Si la tienda da una ruta ("Electrónica > Celulares > APPLE", como Walmart y Monge), gana la
parte más específica que tenga regla; pero si alguna parte es de las que no van (por ejemplo
"Mascota"), el producto no va.

Si el tipo de producto no tiene regla, se prueba con el nombre del producto ("Licuadora
Oster..."). Si tampoco, el producto no se crea en el catálogo y aparece en el resumen de
crear_productos como "sin categoría"; para incluirlo, se agrega aquí la regla.

Los celulares ya están en Electrodomésticos, así que la electrónica va ahí también.
"""

from .emparejamiento import normalizar

ABARROTES = "Abarrotes"
ELECTRODOMESTICOS = "Electrodomésticos"
HIGIENE = "Higiene"
HOGAR = "Artículos para el hogar"

REGLAS = {
    # Secciones de supermercado (Walmart, Maxipali)
    ABARROTES: (
        "abarrote",
        "lacteo",
        "jugos y bebidas",
        "bebida",
        "carnes",
        "embutido",
        "alimentos congelados",
        "frutas y verduras",
        "panaderia",
        "cervezas vinos y licores",
        "comida para bebe",
    ),
    HIGIENE: (
        "higiene",
        "cuidado bucal",
        "cuidado del cabello",
        "cuidado facial",
        "cuidado intimo",
        "cuidado corporal",
        "cosmetico",
        "panal",
        "toallitas humedas",
        "limpieza",
        "papel higienico",
        "detergente",
        "jabon",
    ),
    ELECTRODOMESTICOS: (
        "electronica",
        # cocina
        "licuadora",
        "cafetera",
        "arrocera",
        "olla arrocera",
        "olla electrica",
        "olla multiuso",
        "olla multifuncional",
        "olla de coccion lenta",
        "olla de cocimiento",
        "sarten electrico",
        "freidor",
        "air fryer",
        "horno",
        "tostadora",
        "sandwichera",
        "waflera",
        "batidora",
        "procesador de alimento",
        "procesador de comida",
        "extractor",
        "exprimidor",
        "hervidor",
        "moledor",
        "percolador",
        "calentador de agua",
        "maquina de coser",
        "maquina de palomitas",
        "maquina de sorbete",
        "maquina para helado",
        "maquina de bebidas",
        "combo",
        # casa y cuidado personal
        "plancha",
        "aspiradora",
        "ventilador",
        "hidrolavadora",
        "vaporizador",
        "garment care",
        "alisador",
        "rizador",
        "secador",
        "cepillo de aire",
        "cortadora",
        "kit cortadora",
        "recortador",
        "afeitadora",
        # electrónica
        "celular",
        "telefono",
        "televisor",
        "pantalla",
        "laptop",
        "tablet",
        "computadora",
        "monitor",
        "impresora",
        "proyector",
        "parlante",
        "mini parlante",
        "bocina",
        "barra de sonido",
        "audifono",
        "microfono",
        "sistema de microfono",
        "mouse",
        "teclado",
        "mini teclado",
        "consola",
        "videojuego",
        "control",
        "mando",
        "juego de mandos",
        "camara",
        "videocamara",
        "timbre",
        "smartwatch",
        "banda inteligente",
        "radio",
        "router",
        "antena",
        "switch",
        "hub",
        "disco duro",
        "memoria usb",
        "tarjeta de memoria",
        "lector de tarjetas",
        "cable",
        "adaptador",
        "adapatador",
        "convertidor",
        "cargador",
        "powerbank",
        "regleta",
        "extension electrica",
        "protector de voltaje",
        "inversor de corriente",
        "estacion de energia",
        "tocadiscos",
        "foco inteligente",
        "enchufe inteligente",
        "interruptor inteligente",
        "barra multicontacto",
        "detector",
    ),
    HOGAR: (
        "articulos para el hogar",
        # muebles
        "juego de comedor",
        "juego comedor",
        "juego de sala",
        "juego sala",
        "sala seccional",
        "sofa",
        "sillon",
        "silla",
        "butaca",
        "taburete",
        "banco",
        "ropero",
        "comoda",
        "gavetero",
        "tocador",
        "zapatero",
        "zapatera",
        "alacena",
        "aparador",
        "librera",
        "estante",
        "escritorio",
        "mesa",
        "rack",
        "mueble",
        "centro de entretenimiento",
        "cama",
        "base",
        "carrito bar",
        "aereo",
        "fregadero",
        "gregadero",
        # textiles
        "set de sabana",
        "ropa de cama",
        "cojin",
        "cushion",
        "manta",
        "cortina",
        "esteira de sofa",
        # cocina
        "sarten",
        "juego de sarten",
        "set de sarten",
        "olla",
        "juego de olla",
        "set de olla",
        "set de cazuela",
        "bateria de cocina",
        "set de vajilla",
        "juego de vajilla",
        "juego de vaso",
        "vaso",
        "cubierto",
        "juego de cubierto",
        "set de cubierto",
        "cuchillo",
        "utensilio",
        "juego de utensilio",
        "kit de cocina",
        "juego de tabla",
        "juego de contenedor",
        "frasco",
        "bandeja",
        "tetera",
        "prensa francesa",
        "hielera",
        "botella",
        "cesta",
        "organizador",
        "barbacoa",
        "asador",
        "accesorio parrilla",
        "pincho",
        # decoración
        "cuadro",
        "espejo",
        "lampara",
        "figura decorativa",
        "esfera decorativa",
        "decoracion",
        "portaretrato",
        "portavela",
    ),
    # No van en el catálogo (por ahora): secciones enteras de Walmart y cosas que se parecen a
    # una regla de arriba. En una ruta, basta con que una parte esté aquí para que no vaya.
    None: (
        "mouse pad",
        "autos",
        "mascota",
        "juguetes",
        "deportes",
        "ropa",
        "farmacia",
        "libros y revistas",
        "inactiva",
        "inactivo",
        "inactive",
    ),
}

_TERMINACIONES = ("s", "es", "a", "as")


def _misma_palabra(de_la_regla, de_la_tienda):
    return de_la_tienda == de_la_regla or de_la_tienda in (
        de_la_regla + t for t in _TERMINACIONES
    )


def _coincide(regla, palabras):
    return len(regla) <= len(palabras) and all(
        map(_misma_palabra, regla, palabras)
    )


_REGLAS = sorted(
    (
        (tuple(normalizar(tipo).split()), categoria)
        for categoria, tipos in REGLAS.items()
        for tipo in tipos
    ),
    key=lambda regla: -len(regla[0]),
)


def _regla_para(texto):
    """(True, categoría) de la regla más larga que coincide con el texto, o (False, None)."""
    palabras = normalizar(texto).split()
    for regla, categoria in _REGLAS:
        if _coincide(regla, palabras):
            return True, categoria
    return False, None


def categoria_para(*textos):
    """El nombre de la categoría del catálogo según el primer texto que tenga regla, o None.

    Se le pasa el tipo de producto de la tienda y, por si acaso, el nombre del producto. Si el
    tipo es una ruta ("Hogar > Cocina > Licuadoras"), gana la parte más específica con regla,
    salvo que alguna parte sea de las que no van.
    """
    for texto in textos:
        encontradas = [
            categoria
            for hay, categoria in map(_regla_para, str(texto or "").split(">"))
            if hay
        ]
        if encontradas:
            return None if None in encontradas else encontradas[-1]
    return None
