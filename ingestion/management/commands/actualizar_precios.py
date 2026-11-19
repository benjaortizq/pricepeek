"""python manage.py actualizar_precios: revisa en cada tienda los precios guardados (SCRUM-56)."""

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ingestion.actualizacion import ACTUALIZADO, FALLO, NO_SOPORTADA, SIN_CAMBIOS, revisar
from ingestion.scrapers import ClienteHttp
from products.models import Prices
from products.templatetags.precios import miles


class Command(BaseCommand):
    help = (
        "Revisa en la página de cada tienda los precios guardados y los actualiza. "
        "Si algo falla, no toca el precio y registra una incidencia."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tienda", help="Solo las tiendas cuyo nombre contiene este texto (por ejemplo: walmart).")
        parser.add_argument("--limite", type=int, help="Revisar como máximo esta cantidad de precios.")
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
            "--pausa", type=float, default=1.5, help="Segundos entre peticiones a las tiendas (por defecto 1.5)."
        )

    def handle(self, *args, **opciones):
        salida = getattr(self.stdout, "_out", None)
        if hasattr(salida, "reconfigure"):
            salida.reconfigure(encoding="utf-8", errors="replace")  # la consola de Windows no siempre acepta ₡

        guardar = not opciones["dry_run"]
        precios = Prices.objects.select_related("id_store", "gtin").order_by("id_store__name", "id")
        if not opciones["todos"]:
            horas = settings.PRECIOS_FRECUENCIA_HORAS
            precios = precios.filter(updated_at__lt=timezone.now() - timedelta(hours=horas))
        if opciones["tienda"]:
            precios = precios.filter(id_store__name__icontains=opciones["tienda"])
        if opciones["limite"]:
            precios = precios[: opciones["limite"]]
        precios = list(precios)

        if not precios:
            self.stdout.write("No hay precios pendientes de revisar. Use --todos para revisarlos igual.")
            return
        if not guardar:
            self.stdout.write(self.style.WARNING("Modo de prueba (--dry-run): no se guardará nada."))

        http = ClienteHttp(pausa=opciones["pausa"])
        conteo = Counter()
        ancho = len(str(len(precios)))
        for numero, precio in enumerate(precios, 1):
            revision = revisar(precio, http, guardar=guardar)
            conteo[revision.resultado] += 1
            conteo["incidencias"] += revision.incidencia is not None
            self._mostrar(f"[{numero:>{ancho}}/{len(precios)}]", revision)

        self.stdout.write("")
        resumen = (
            f"{len(precios)} revisados · {conteo[ACTUALIZADO]} actualizados · {conteo[SIN_CAMBIOS]} sin cambios · "
            f"{conteo[FALLO]} con fallo · {conteo['incidencias']} incidencias"
        )
        if conteo[NO_SOPORTADA]:
            resumen += f" · {conteo[NO_SOPORTADA]} de tiendas no soportadas"
        self.stdout.write(self.style.SUCCESS(resumen) if not conteo[FALLO] else self.style.WARNING(resumen))
        if conteo["incidencias"] and guardar:
            self.stdout.write("Las incidencias se pueden ver en el admin de Django, en Ingestion › Incidencias.")

    def _mostrar(self, prefijo, revision):
        precio = revision.precio
        linea = f"{prefijo} {precio.id_store.name.strip()} · {precio.gtin.name}: "
        if revision.resultado == NO_SOPORTADA:
            self.stdout.write(linea + "tienda no soportada, se omite.")
            return
        if revision.cambios:
            cambios = ", ".join(self._cambio(campo, antes, despues) for campo, (antes, despues) in revision.cambios.items())
            self.stdout.write(self.style.SUCCESS(linea + cambios))
        elif revision.resultado == SIN_CAMBIOS:
            self.stdout.write(linea + "sin cambios.")
        if revision.incidencia is not None:
            motivo = revision.incidencia.reason.splitlines()[0]
            self.stdout.write(self.style.WARNING(f"{linea}{revision.incidencia.get_kind_display()}. {motivo}"))

    @staticmethod
    def _cambio(campo, antes, despues):
        if campo == "price":
            return f"precio ₡{miles(antes) if antes is not None else '—'} → ₡{miles(despues)}"
        if campo == "discount":
            return f"descuento {antes * 100:.0f} % → {despues * 100:.0f} %"
        return "ahora disponible" if despues else "ahora no disponible"
