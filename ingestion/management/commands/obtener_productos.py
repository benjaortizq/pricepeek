"""python manage.py obtener_productos --tienda monge: los productos que publica una tienda (SCRUM-56)."""

import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from ingestion.models import StoreProduct
from ingestion.productos_tienda import candidatas_del_catalogo, guardar_ficha, registrar_codigos_invalidos
from ingestion.scrapers import ClienteHttp, ErrorDescarga, ErrorExtraccion
from ingestion.tiendas import TIENDAS
from products.templatetags.precios import miles

Status = StoreProduct.Status
# Si la tienda responde 403/429 (nos limita o nos bloquea), se espera cada vez más antes de
# seguir: 30 s, 60 s, 90 s... Al quinto rechazo seguido se deja de insistir.
ESPERA_TRAS_RECHAZO = 30
RECHAZOS_PARA_DETENERSE = 5
PAUSA_POR_DEFECTO = 1.5
esperar = time.sleep


class Command(BaseCommand):
    help = (
        "Obtiene los productos que publica una tienda, los guarda en Ingestion › Productos de tiendas "
        "y sugiere con qué variante del catálogo coincide cada uno. Las sugerencias se confirman en el admin."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tienda", required=True, choices=sorted(TIENDAS), help="La tienda a revisar.")
        parser.add_argument(
            "--filtro",
            nargs="+",
            help="Solo las URLs que contienen alguno de estos textos (por ejemplo: --filtro iphone galaxy xiaomi).",
        )
        parser.add_argument(
            "--categoria",
            nargs="+",
            help="Walmart, Maxipali y Automercado: solo los productos de estas categorías, con la ruta que sale en "
            "la URL de la tienda (por ejemplo: --categoria electronica articulos-para-el-hogar/colchones-y-blancos). "
            "Es mucho más rápido que leer toda la lista: la búsqueda trae los productos completos.",
        )
        parser.add_argument("--limite", type=int, help="Revisar como máximo esta cantidad de páginas.")
        parser.add_argument(
            "--todos", action="store_true", help="Volver a revisar también los productos que ya se habían obtenido."
        )
        parser.add_argument("--dry-run", action="store_true", help="Mostrar lo que encontraría sin guardar nada.")
        parser.add_argument(
            "--pausa",
            type=float,
            help="Segundos entre peticiones a la tienda (por defecto, la recomendada para la tienda o 1.5).",
        )

    def handle(self, *args, **opciones):
        salida = getattr(self.stdout, "_out", None)
        if hasattr(salida, "reconfigure"):
            salida.reconfigure(encoding="utf-8", errors="replace")  # la consola de Windows no siempre acepta ₡

        tienda = TIENDAS[opciones["tienda"]]
        guardar = not opciones["dry_run"]
        pausa = opciones["pausa"] if opciones["pausa"] is not None else getattr(tienda, "PAUSA", PAUSA_POR_DEFECTO)
        http = ClienteHttp(pausa=pausa)
        categorias = opciones["categoria"]
        if categorias and not hasattr(tienda, "productos_de_categorias"):
            con_categorias = ", ".join(sorted(n for n, t in TIENDAS.items() if hasattr(t, "productos_de_categorias")))
            raise CommandError(f"--categoria solo sirve para {con_categorias}.")

        def avisar(texto):
            self.stdout.write(f"  {texto}")

        # Por categoría, la búsqueda ya trae cada producto completo: no se vuelven a pedir. Las
        # tiendas sin lista de páginas (Automercado) siempre se leen así.
        de_la_busqueda = {}
        por_busqueda = bool(categorias) or not hasattr(tienda, "listar_urls")
        try:
            if por_busqueda:
                donde = ", ".join(categorias) if categorias else "todas sus categorías"
                self.stdout.write(f"Buscando los productos de {tienda.NOMBRE} en: {donde}...")
                de_la_busqueda = tienda.productos_de_categorias(http, categorias or [], avisar=avisar)
                urls = list(de_la_busqueda)
            else:
                self.stdout.write(f"Leyendo la lista de productos de {tienda.NOMBRE}...")
                urls = tienda.listar_urls(http, avisar=avisar)
        except ErrorExtraccion as error:
            raise CommandError(f"No se pudo leer la lista de productos de {tienda.NOMBRE}: {error}") from error
        total_tienda = len(urls)
        if opciones["filtro"]:
            filtros = [f.lower() for f in opciones["filtro"]]
            urls = [u for u in urls if any(f in u.lower() for f in filtros)]
        if not opciones["todos"]:
            ya_obtenidas = set(StoreProduct.objects.filter(url__in=urls).values_list("url", flat=True))
            urls = [u for u in urls if u not in ya_obtenidas]
        if opciones["limite"]:
            urls = urls[: opciones["limite"]]

        origen = "productos en esas categorías" if categorias else "productos" if por_busqueda else "páginas en su lista"
        self.stdout.write(f"{tienda.NOMBRE}: {total_tienda} {origen}; se van a revisar {len(urls)}.")
        if not urls:
            self.stdout.write("No hay páginas nuevas. Use --todos para revisar otra vez las que ya se obtuvieron.")
            return
        if not guardar:
            self.stdout.write(self.style.WARNING("Modo de prueba (--dry-run): no se guardará nada."))

        candidatas = candidatas_del_catalogo()
        conteo = Counter()
        ancho = len(str(len(urls)))
        rechazos_seguidos = 0
        revisadas = 0
        for numero, url in enumerate(urls, 1):
            prefijo = f"[{numero:>{ancho}}/{len(urls)}]"
            revisadas = numero
            try:
                if url in de_la_busqueda:
                    ficha = tienda.ficha_de_la_busqueda(url, de_la_busqueda[url])
                else:
                    ficha = tienda.obtener_ficha(url, http)
            except Exception as error:  # una página rara no debe detener la revisión de las demás
                conteo["fallos"] += 1
                motivo = error if isinstance(error, ErrorExtraccion) else f"error inesperado ({error.__class__.__name__}: {error})"
                self.stdout.write(self.style.WARNING(f"{prefijo} {url}: {motivo}"))
                rechazos_seguidos = rechazos_seguidos + 1 if isinstance(error, ErrorDescarga) and error.es_rechazo else 0
                if rechazos_seguidos >= RECHAZOS_PARA_DETENERSE:
                    self.stdout.write(
                        self.style.ERROR(
                            f"{tienda.NOMBRE} rechazó {rechazos_seguidos} peticiones seguidas: se detiene para no insistir. "
                            "Espere unos minutos y vuelva a correrlo (sigue donde quedó), o use una --pausa más larga."
                        )
                    )
                    break
                if rechazos_seguidos:
                    espera = ESPERA_TRAS_RECHAZO * rechazos_seguidos
                    self.stdout.write(f"{prefijo}   {tienda.NOMBRE} está rechazando peticiones: se esperan {espera} s antes de seguir.")
                    esperar(espera)
                continue
            rechazos_seguidos = 0
            if ficha is None:
                conteo["no son productos"] += 1
                if opciones["verbosity"] > 1:
                    self.stdout.write(f"{prefijo} {url}: no es una página de producto.")
                continue
            producto = guardar_ficha(ficha, tienda.NOMBRE, candidatas, guardar=guardar)
            conteo["productos"] += 1
            conteo[producto.status] += 1
            self._mostrar(prefijo, producto)
            for incidencia in registrar_codigos_invalidos(ficha, tienda.NOMBRE, guardar=guardar):
                conteo["códigos inválidos"] += 1
                motivo = incidencia.reason.splitlines()[0]
                self.stdout.write(self.style.WARNING(f"{prefijo}   código de barras inválido ({incidencia.gtin}): {motivo}"))

        self.stdout.write("")
        resumen = (
            f"{revisadas} páginas · {conteo['productos']} productos · "
            f"{conteo[Status.SUGGESTED]} con coincidencia sugerida · "
            f"{conteo['no son productos']} no eran productos · {conteo['fallos']} fallos"
        )
        if conteo["códigos inválidos"]:
            resumen += f" · {conteo['códigos inválidos']} códigos de barras inválidos (quedan como incidencia)"
        self.stdout.write(self.style.SUCCESS(resumen))
        if guardar and conteo[Status.SUGGESTED]:
            self.stdout.write("Revise las sugerencias en el admin de Django: Ingestion › Productos de tiendas.")

    def _mostrar(self, prefijo, producto):
        precio = f"₡{miles(producto.final_price)}" if producto.final_price is not None else "sin precio"
        linea = f"{prefijo} {producto.name} · {precio}"
        if not producto.is_available:
            linea += " (no disponible)"
        if producto.status == Status.SUGGESTED:
            variante = producto.suggested_variant
            nombre = variante.name if variante else producto.suggested_gtin
            self.stdout.write(
                self.style.SUCCESS(f"{linea} → {nombre} (puntaje {producto.score}: {producto.match_reason})")
            )
        elif producto.status in (Status.CONFIRMED, Status.REJECTED):
            self.stdout.write(f"{linea} ({producto.get_status_display().lower()})")
        else:
            self.stdout.write(linea)
