"""python manage.py actualizar_precios: revisa en cada tienda los precios guardados (SCRUM-56).

Van primero los precios de los productos más vistos en los últimos días (products/popularidad.py)
y después los que llevan más tiempo sin revisarse. Con --minutos para cuando se acaba el tiempo:
lo que no alcanzó es lo menos importante y queda para la próxima vez (así corre cada hora en
.github/workflows/actualizar-precios.yml).
"""

import time
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ingestion.actualizacion import (
    ACTUALIZADO,
    FALLO,
    NO_SOPORTADA,
    SIN_CAMBIOS,
    revisar,
)
from ingestion.scrapers import ClienteHttp
from products.comercios import nombre_del_comercio, sin_obtencion_automatica
from products.models import PartnerStore, Prices
from products.popularidad import DIAS_DE_POPULARIDAD, popularidad_reciente
from products.templatetags.precios import miles

reloj = time.monotonic  # las pruebas lo reemplazan para no esperar de verdad
# Lo que suele tardar cada precio antes de medirlo: la pausa entre peticiones o, si la tienda
# responde más lento, lo que tarda ella.
SEGUNDOS_POR_PRECIO = 2
AVISAR_CADA = 50  # cada cuántos precios se dice cuánto falta


def duracion(segundos, aproximada=False):
    """130 -> "2 min", 4000 -> "1 h 7 min", 20 -> "menos de 1 min" ("~2 min" si es aproximada)."""
    minutos = round(segundos / 60)
    if minutos < 1:
        return "menos de 1 min"
    horas, minutos = divmod(minutos, 60)
    texto = f"{horas} h {minutos} min" if horas else f"{minutos} min"
    return f"~{texto}" if aproximada else texto


def plural(cantidad, palabra):
    return (
        f"{cantidad} {palabra}" if cantidad == 1 else f"{cantidad} {palabra}s"
    )


class Command(BaseCommand):
    help = (
        "Revisa en la página de cada tienda los precios guardados y los actualiza. "
        "Si algo falla, no toca el precio y registra una incidencia."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tienda",
            help="Solo las tiendas cuyo nombre contiene este texto (por ejemplo: walmart).",
        )
        parser.add_argument(
            "--limite",
            type=int,
            help="Revisar como máximo esta cantidad de precios.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar lo que cambiaría sin guardar nada (ni precios ni incidencias).",
        )
        parser.add_argument(
            "--todos",
            action="store_true",
            help="Revisar también los precios verificados hace menos de PRECIOS_FRECUENCIA_HORAS.",
        )
        parser.add_argument(
            "--pausa",
            type=float,
            default=1.5,
            help="Segundos entre peticiones a las tiendas (por defecto 1.5).",
        )
        parser.add_argument(
            "--minutos",
            type=float,
            help="Revisar hasta que pase este tiempo y parar ahí (por ejemplo: --minutos 20). Como van primero "
            "los productos más vistos y después los que llevan más tiempo sin revisarse, lo que no alcanza es "
            "lo menos importante y queda para la próxima vez.",
        )

    def handle(self, *args, **opciones):
        salida = getattr(self.stdout, "_out", None)
        if hasattr(salida, "reconfigure"):
            salida.reconfigure(
                encoding="utf-8", errors="replace"
            )  # la consola de Windows no siempre acepta ₡

        minutos = opciones["minutos"]
        if minutos is not None and minutos <= 0:
            raise CommandError("--minutos tiene que ser mayor que 0.")
        guardar = not opciones["dry_run"]
        omitidos = sorted(
            nombre_del_comercio(perfil.store)
            for perfil in PartnerStore.objects.filter(store_id__in=sin_obtencion_automatica()).select_related("store")
        )
        if omitidos:
            self.stdout.write(
                "Se omiten (desactivados o con datos provistos por el comercio): " + ", ".join(omitidos) + "."
            )
        precios = (
            # Los comercios desactivados o que proveen sus datos no se revisan (products/comercios.py).
            Prices.objects.exclude(id_store_id__in=sin_obtencion_automatica())
            .select_related("id_store", "gtin")
            .annotate(popularidad=popularidad_reciente("gtin__product_id"))
            # Primero lo que la gente está viendo; después, lo que lleva más tiempo sin revisarse.
            .order_by("-popularidad", "updated_at", "id")
        )
        if not opciones["todos"]:
            horas = settings.PRECIOS_FRECUENCIA_HORAS
            precios = precios.filter(
                updated_at__lt=timezone.now() - timedelta(hours=horas)
            )
        if opciones["tienda"]:
            precios = precios.filter(
                id_store__name__icontains=opciones["tienda"]
            )
        if opciones["limite"]:
            precios = precios[: opciones["limite"]]
        precios = list(precios)

        if not precios:
            self.stdout.write(
                "No hay precios pendientes de revisar. Use --todos para revisarlos igual."
            )
            return
        if not guardar:
            self.stdout.write(
                self.style.WARNING(
                    "Modo de prueba (--dry-run): no se guardará nada."
                )
            )
        self._presentar(precios, opciones["pausa"], minutos)

        http = ClienteHttp(pausa=opciones["pausa"])
        conteo = Counter()
        ancho = len(str(len(precios)))
        inicio = reloj()
        hasta = inicio + minutos * 60 if minutos else None
        revisados = 0
        for numero, precio in enumerate(precios, 1):
            if hasta is not None and reloj() >= hasta:
                break
            revision = revisar(precio, http, guardar=guardar)
            revisados = numero
            conteo[revision.resultado] += 1
            conteo["incidencias"] += revision.incidencia is not None
            self._mostrar(f"[{numero:>{ancho}}/{len(precios)}]", revision)
            if numero % AVISAR_CADA == 0 and numero < len(precios):
                self._avance(numero, len(precios), reloj() - inicio, hasta)

        self.stdout.write("")
        resumen = (
            f"{revisados} revisados · {conteo[ACTUALIZADO]} actualizados · {conteo[SIN_CAMBIOS]} sin cambios · "
            f"{conteo[FALLO]} con fallo · {conteo['incidencias']} incidencias"
        )
        if conteo[NO_SOPORTADA]:
            resumen += f" · {conteo[NO_SOPORTADA]} de tiendas no soportadas"
        self.stdout.write(
            self.style.SUCCESS(resumen)
            if not conteo[FALLO]
            else self.style.WARNING(resumen)
        )
        self.stdout.write(f"Tardó {duracion(reloj() - inicio)}.")
        if revisados < len(precios):
            faltan = len(precios) - revisados
            self.stdout.write(
                f"Se acabó el tiempo (--minutos {minutos:g}): {'queda' if faltan == 1 else 'quedan'} "
                f"{plural(faltan, 'precio')} para la próxima vez, los menos vistos y revisados hace menos."
            )
        if conteo["incidencias"] and guardar:
            self.stdout.write(
                "Las incidencias se revisan y resuelven en el panel de administración, en «Incidencias de datos»."
            )

    def _presentar(self, precios, pausa, minutos):
        """Cuántos precios se van a revisar, de qué tiendas, en qué orden y cuánto se tardaría."""
        por_tienda = Counter(
            precio.id_store.name.strip() for precio in precios
        )
        detalle = " · ".join(
            f"{tienda} {cantidad}"
            for tienda, cantidad in por_tienda.most_common()
        )
        self.stdout.write(
            f"Se van a revisar {plural(len(precios), 'precio')}: {detalle}"
        )
        vistos = sum(1 for precio in precios if precio.popularidad)
        if vistos:
            self.stdout.write(
                f"Primero {plural(vistos, 'precio')} de productos vistos en los últimos {DIAS_DE_POPULARIDAD} días; "
                "después, los que llevan más tiempo sin revisarse."
            )
        por_precio = max(pausa, SEGUNDOS_POR_PRECIO)
        estimado = len(precios) * por_precio
        linea = f"Tiempo estimado: {duracion(estimado, aproximada=True)} (unos {por_precio:g} s por precio)."
        if minutos and estimado > minutos * 60:
            alcanzan = int(minutos * 60 // por_precio)
            linea += f" Con --minutos {minutos:g} alcanza para unos {alcanzan}; los demás quedan para la próxima vez."
        self.stdout.write(linea)

    def _avance(self, hechos, total, transcurrido, hasta):
        """Cuánto falta, según lo que han tardado los precios revisados hasta ahora."""
        falta = (total - hechos) * transcurrido / hechos
        if hasta is not None:
            falta = min(falta, max(0, hasta - reloj()))
        self.stdout.write(
            f"  … {hechos}/{total} en {duracion(transcurrido)}; faltan {duracion(falta, aproximada=True)}"
        )

    def _mostrar(self, prefijo, revision):
        precio = revision.precio
        linea = (
            f"{prefijo} {precio.id_store.name.strip()} · {precio.gtin.name}: "
        )
        if revision.resultado == NO_SOPORTADA:
            self.stdout.write(linea + "tienda no soportada, se omite.")
            return
        if revision.cambios:
            cambios = ", ".join(
                self._cambio(campo, antes, despues)
                for campo, (antes, despues) in revision.cambios.items()
            )
            self.stdout.write(self.style.SUCCESS(linea + cambios))
        elif revision.resultado == SIN_CAMBIOS:
            self.stdout.write(linea + "sin cambios.")
        if revision.incidencia is not None:
            motivo = revision.incidencia.reason.splitlines()[0]
            self.stdout.write(
                self.style.WARNING(
                    f"{linea}{revision.incidencia.get_kind_display()}. {motivo}"
                )
            )

    @staticmethod
    def _cambio(campo, antes, despues):
        if campo == "price":
            return f"precio ₡{miles(antes) if antes is not None else '—'} → ₡{miles(despues)}"
        if campo == "discount":
            return f"descuento {antes * 100:.0f} % → {despues * 100:.0f} %"
        return "ahora disponible" if despues else "ahora no disponible"
