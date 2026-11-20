"""python manage.py crear_productos: pasa al catálogo los productos de tiendas que no están en él (SCRUM-56)."""

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.db.models import Q

from ingestion.catalogo import (
    CREABLES,
    CREADO,
    VINCULADO,
    MOTIVO_MISMO_CODIGO,
    Catalogo,
    arreglar_secuencias,
    crear_en_catalogo,
    secuencias_atrasadas,
    sugerido_por_nombre,
)
from ingestion.models import StoreProduct
from ingestion.tiendas import TIENDAS

TIPOS_SIN_CATEGORIA_A_MOSTRAR = 25


class Command(BaseCommand):
    help = (
        "Crea en el catálogo (marca, producto, variante, imagen y precio) los productos de tiendas que traen "
        "un código de barras válido y todavía no coinciden con nada. Si el código ya está en el catálogo, "
        "solo le agrega el precio de la tienda (también a los sugeridos por código de barras). Las sugerencias "
"por nombre se revisan en el admin, o se vinculan con --confirmar-desde."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tienda", choices=sorted(TIENDAS), help="Solo los productos de esta tienda.")
        parser.add_argument(
            "--filtro", nargs="+", help="Solo los que tienen alguno de estos textos en el nombre o en el tipo de producto."
        )
        parser.add_argument(
            "--confirmar-desde",
            type=int,
            metavar="PUNTAJE",
            help="Además, vincular los sugeridos por el nombre con este puntaje o más (las sugerencias empiezan "
            "en 70). No vincula los que traen otro código de barras que la variante sugerida, ni dos páginas de "
            "la misma tienda que se parecen igual a la misma variante: esos se revisan en el admin.",
        )
        parser.add_argument(
            "--min-tiendas",
            type=int,
            default=1,
            metavar="N",
            help="Solo crear los productos nuevos cuyo código de barras está en al menos N tiendas distintas "
            "(por ejemplo, --min-tiendas 2). Los que ya están en el catálogo se vinculan igual.",
        )
        parser.add_argument("--limite", type=int, help="Revisar como máximo esta cantidad de productos.")
        parser.add_argument("--dry-run", action="store_true", help="Mostrar lo que haría sin guardar nada.")
        parser.add_argument(
            "--arreglar-secuencias",
            action="store_true",
            help="Si el contador de ids de alguna tabla del catálogo está atrasado, ponerlo en el id más alto "
            "(no cambia ninguna fila).",
        )

    def handle(self, *args, **opciones):
        salida = getattr(self.stdout, "_out", None)
        if hasattr(salida, "reconfigure"):
            salida.reconfigure(encoding="utf-8", errors="replace")  # la consola de Windows no siempre acepta ₡

        guardar = not opciones["dry_run"]
        min_tiendas = opciones["min_tiendas"]
        if min_tiendas < 1:
            raise CommandError("--min-tiendas tiene que ser 1 o más.")
        desde = opciones["confirmar_desde"]
        sugeridos = Q(status=StoreProduct.Status.SUGGESTED, match_reason=MOTIVO_MISMO_CODIGO)
        if desde is not None:
            sugeridos |= Q(status=StoreProduct.Status.SUGGESTED, score__gte=desde)
        productos = StoreProduct.objects.filter(Q(status__in=CREABLES) | sugeridos)
        if opciones["tienda"]:
            productos = productos.filter(store_name=TIENDAS[opciones["tienda"]].NOMBRE)
        if opciones["filtro"]:
            textos = Q()
            for texto in opciones["filtro"]:
                textos |= Q(name__icontains=texto) | Q(category__icontains=texto)
            productos = productos.filter(textos)
        if opciones["limite"]:
            productos = productos[: opciones["limite"]]
        productos = list(productos)
        if desde is not None:
            # Primero los que tienen código de barras: si una página coincide por código con una
            # variante, gana ella y no la que solo se le parece por el nombre.
            productos.sort(key=lambda producto: sugerido_por_nombre(producto, desde))

        self.stdout.write(f"Se van a revisar {len(productos)} productos de tiendas sin vincular al catálogo.")
        if not productos:
            return
        if not guardar:
            self.stdout.write(self.style.WARNING("Modo de prueba (--dry-run): no se guardará nada."))
        self._revisar_secuencias(guardar, opciones["arreglar_secuencias"])

        catalogo = Catalogo()
        if desde is not None:
            catalogo.anotar_sugerencias(productos, desde)
        if min_tiendas > 1:
            catalogo.contar_tiendas()
        conteo = Counter()
        omitidos = Counter()
        sin_categoria = Counter()
        ancho = len(str(len(productos)))
        for numero, producto in enumerate(productos, 1):
            prefijo = f"[{numero:>{ancho}}/{len(productos)}]"
            try:
                resultado = crear_en_catalogo(
                    producto, catalogo, guardar=guardar, confirmar_desde=desde, min_tiendas=min_tiendas
                )
            except DatabaseError as error:
                # Un error de la base casi siempre se repite con los siguientes: mejor detenerse.
                raise CommandError(
                    f"La base rechazó «{producto.name}»: {error}\n"
                    f"Ese producto no quedó a medias (se deshizo). Los {conteo[CREADO]} creados y "
                    f"{conteo[VINCULADO]} vinculados antes de él sí quedaron guardados."
                ) from error
            conteo[resultado.tipo] += 1
            if resultado.tipo == CREADO:
                conteo["marcas nuevas"] += resultado.marca_nueva
                marca = f" · marca nueva: {producto.brand}" if resultado.marca_nueva else ""
                self.stdout.write(self.style.SUCCESS(f"{prefijo} creado: {producto.name} ({resultado.motivo}){marca}"))
            elif resultado.tipo == VINCULADO and resultado.por_nombre:
                conteo["por nombre"] += 1
                variante = producto.suggested_variant
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{prefijo} vinculado por nombre: {producto.name} → {variante.name if variante else resultado.motivo} "
                        f"(puntaje {producto.score})"
                    )
                )
            elif resultado.tipo == VINCULADO:
                self.stdout.write(self.style.SUCCESS(f"{prefijo} vinculado: {producto.name} → código {resultado.motivo}"))
            else:
                omitidos[resultado.grupo] += 1
                if resultado.tipo_en_tienda:
                    sin_categoria[resultado.tipo_en_tienda] += 1
                por_nombre = desde is not None and sugerido_por_nombre(producto, desde)
                if opciones["verbosity"] > 1 or resultado.grupo == "no se pudo vincular" or por_nombre:
                    self.stdout.write(self.style.WARNING(f"{prefijo} omitido: {producto.name}: {resultado.motivo}"))

        self.stdout.write("")
        de_ellos = f" ({conteo['por nombre']} por nombre)" if desde is not None else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(productos)} revisados · {conteo[CREADO]} creados en el catálogo "
                f"({conteo['marcas nuevas']} marcas nuevas) · {conteo[VINCULADO]} vinculados a variantes que ya "
                f"existían{de_ellos} · {sum(omitidos.values())} omitidos"
            )
        )
        if omitidos:
            self.stdout.write("Omitidos: " + " · ".join(f"{grupo} ({n})" for grupo, n in omitidos.most_common()))
        if sin_categoria:
            tipos = ", ".join(f"{tipo} ({n})" for tipo, n in sin_categoria.most_common(TIPOS_SIN_CATEGORIA_A_MOSTRAR))
            resto = len(sin_categoria) - TIPOS_SIN_CATEGORIA_A_MOSTRAR
            if resto > 0:
                tipos += f" y {resto} tipos más"
            self.stdout.write(f"Tipos de producto sin categoría (se agregan en ingestion/categorias.py): {tipos}")
        if opciones["verbosity"] < 2 and omitidos:
            self.stdout.write("Use -v 2 para ver cada producto omitido y por qué.")

    def _revisar_secuencias(self, guardar, arreglar):
        atrasadas = secuencias_atrasadas()
        if not atrasadas:
            return
        tablas = ", ".join(f"{tabla} (el id más alto es {maximo})" for tabla, _, maximo in atrasadas)
        if arreglar and guardar:
            arreglar_secuencias(atrasadas)
            self.stdout.write(self.style.SUCCESS(f"Contador de ids corregido en: {tablas}."))
            return
        mensaje = (
            f"El contador de ids está atrasado en: {tablas}. Alguien insertó filas con el id escrito a mano, "
            "y la próxima fila nueva chocaría con una que ya existe. Corra el comando con --arreglar-secuencias: "
            "pone cada contador en el id más alto y no cambia ninguna fila."
        )
        if guardar:
            raise CommandError(mensaje)
        self.stdout.write(self.style.WARNING(mensaje))
