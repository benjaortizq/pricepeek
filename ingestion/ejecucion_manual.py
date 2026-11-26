"""Ejecución manual de la obtención de datos de un comercio, desde el panel de administración.

El administrador elige un comercio que usa web scraping y dónde correr la actualización:

* En el servidor de PricePeek: actualizar_precios --tienda <comercio> corre en un hilo aparte
  de este mismo proceso y va guardando su salida, para verla mientras avanza.
* En GitHub Actions: se pide una corrida del workflow de cada hora (actualizar-precios.yml) por
  su API. La corrida lleva el número de la solicitud en el nombre y así se encuentra después.

En los dos casos, después de actualizar se revisan las alertas de baja de precio, igual que en
la corrida de cada hora.
"""

import io
import threading
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections, connections, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from products.comercios import sin_obtencion_automatica
from products.models import Prices, Stores

from .models import Incident, ManualRun
from .resolucion import EXTRACCION_FALLIDA
from .scrapers import extractor_para

Status = ManualRun.Status
Runner = ManualRun.Runner

MINUTOS = (10, 20, 30, 45)  # lo que se puede elegir; GitHub corta el trabajo a los 55 minutos
MINUTOS_POR_DEFECTO = 20
HORAS_DESACTUALIZADO = 48  # como el aviso de precios desactualizados del detalle del producto
SALIDA_MAXIMA = 60_000  # caracteres de la salida que se guardan (los últimos)
GUARDAR_SALIDA_CADA = 3  # segundos
# Una ejecución en el servidor escribe una línea por precio; si se queda callada tanto tiempo,
# el proceso que la corría ya no existe (se reinició el servidor).
SIN_NOTICIAS = timedelta(minutes=10)
GITHUB_API = "https://api.github.com"
GITHUB_TIEMPO_DE_ESPERA = 10  # segundos


class NoSePuedeEjecutar(Exception):
    pass


# --- Comercios ---


def comercios_con_scraping():
    """Los comercios con al menos un precio cuya página PricePeek sabe leer, con lo que conviene
    saber antes de actualizarlos."""
    limite = timezone.now() - timedelta(hours=HORAS_DESACTUALIZADO)
    filas = {}
    for tienda_id, url, revisado in Prices.objects.values_list("id_store_id", "product_web_url", "updated_at"):
        if extractor_para(url) is None:
            continue
        fila = filas.setdefault(tienda_id, {"precios": 0, "desactualizados": 0, "ultima_revision": None})
        fila["precios"] += 1
        fila["desactualizados"] += revisado < limite
        if fila["ultima_revision"] is None or revisado > fila["ultima_revision"]:
            fila["ultima_revision"] = revisado
    incidencias = dict(
        Incident.objects.filter(kind__in=EXTRACCION_FALLIDA, status=Incident.Status.PENDING)
        .order_by()
        .values_list("store_name")
        .annotate(total=Count("pk"))
    )
    comercios = []
    # Los desactivados y los que proveen sus propios datos no se obtienen por web scraping (products/comercios.py).
    for tienda in Stores.objects.filter(pk__in=list(filas)).exclude(pk__in=sin_obtencion_automatica()):
        nombre = tienda.name.strip()
        comercios.append({"id": tienda.pk, "nombre": nombre, "incidencias": incidencias.get(nombre, 0), **filas[tienda.pk]})
    return sorted(comercios, key=lambda comercio: comercio["nombre"].casefold())


def comercio_con_scraping(tienda_id):
    return next((comercio for comercio in comercios_con_scraping() if str(comercio["id"]) == str(tienda_id)), None)


# --- Estado de las ejecuciones ---


def marcar_interrumpidas():
    """Las del servidor que dejaron de dar noticias: el proceso que las corría ya no existe."""
    return ManualRun.objects.filter(
        runner=Runner.SERVER, status__in=ManualRun.ACTIVE, updated_at__lt=timezone.now() - SIN_NOTICIAS
    ).update(
        status=Status.INTERRUPTED,
        finished_at=timezone.now(),
        summary="Se interrumpió: el servidor se reinició antes de que terminara.",
    )


def en_curso_para(nombre):
    """La ejecución de ese comercio que todavía no termina, si hay una."""
    # Las de GitHub que nunca se encontraron no se esperan para siempre.
    reciente = timezone.now() - timedelta(minutes=max(MINUTOS) + 15)
    return (
        ManualRun.objects.filter(store_name=nombre, status__in=ManualRun.ACTIVE)
        .filter(Q(runner=Runner.SERVER) | Q(created_at__gte=reciente))
        .first()
    )


def github_configurado():
    return bool(settings.GITHUB_ACTIONS_TOKEN and settings.GITHUB_REPOSITORIO)


def opciones_disponibles():
    return {Runner.SERVER: settings.OBTENCION_EN_EL_SERVIDOR, Runner.GITHUB: github_configurado()}


# --- Pedir una ejecución ---


def solicitar(tienda_id, runner, usuario, minutos=MINUTOS_POR_DEFECTO, todos=True, prueba=False):
    """Registra la ejecución y la pone a correr donde se pidió."""
    comercio = comercio_con_scraping(tienda_id)
    if comercio is None:
        raise NoSePuedeEjecutar("Ese comercio no tiene precios que se obtengan por web scraping.")
    if runner not in Runner.values:
        raise NoSePuedeEjecutar("Elija dónde ejecutar la obtención de datos.")
    if not opciones_disponibles()[runner]:
        if runner == Runner.GITHUB:
            raise NoSePuedeEjecutar("GitHub Actions no está configurado en este servidor.")
        raise NoSePuedeEjecutar("La ejecución en el servidor está desactivada.")
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        minutos = MINUTOS_POR_DEFECTO
    if minutos not in MINUTOS:
        minutos = MINUTOS_POR_DEFECTO

    marcar_interrumpidas()
    actual = en_curso_para(comercio["nombre"])
    if actual is not None:
        raise NoSePuedeEjecutar(f"Ya hay una ejecución en curso para {comercio['nombre']}; espere a que termine.")

    ejecucion = ManualRun.objects.create(
        store_name=comercio["nombre"],
        store_id=comercio["id"],
        runner=runner,
        minutes=minutos,
        all_prices=todos,
        dry_run=prueba,
        requested_by=usuario,
    )
    if runner == Runner.SERVER:
        # Se lanza al confirmar la transacción, para que el hilo ya encuentre la fila.
        transaction.on_commit(lambda: iniciar_en_el_servidor(ejecucion.pk))
    else:
        pedir_a_github(ejecucion)
    return ejecucion


# --- En el servidor ---


def iniciar_en_el_servidor(ejecucion_id):
    threading.Thread(
        target=correr_en_el_servidor, args=(ejecucion_id,), kwargs={"en_hilo": True},
        name=f"obtencion-manual-{ejecucion_id}", daemon=True,
    ).start()


class SalidaEnVivo(io.TextIOBase):
    """Recibe lo que escribe el comando y lo guarda cada pocos segundos en la ejecución."""

    def __init__(self, ejecucion_id):
        super().__init__()
        self.ejecucion_id = ejecucion_id
        self.texto = ""
        self._guardada = time.monotonic()

    def writable(self):
        return True

    def write(self, texto):
        self.texto = (self.texto + texto)[-SALIDA_MAXIMA:]
        if time.monotonic() - self._guardada >= GUARDAR_SALIDA_CADA:
            self.guardar()
        return len(texto)

    def guardar(self):
        ManualRun.objects.filter(pk=self.ejecucion_id).update(output=self.texto, updated_at=timezone.now())
        self._guardada = time.monotonic()

    def flush(self):
        # No escribe en la base: io.TextIOBase llama a flush() al cerrarse o al recolectarse el
        # objeto, a veces ya sin base; correr_en_el_servidor guarda la salida final.
        pass


def resumen_de_la_salida(texto):
    """La línea final de actualizar_precios: «120 revisados · 3 actualizados · …»."""
    for linea in reversed(texto.splitlines()):
        if " revisados · " in linea or linea.startswith("No hay precios pendientes"):
            return linea.strip()[: ManualRun.SUMMARY_MAX_LENGTH]
    return ""


def correr_en_el_servidor(ejecucion_id, en_hilo=False):
    if en_hilo:
        close_old_connections()
    try:
        ejecucion = ManualRun.objects.get(pk=ejecucion_id)
        ahora = timezone.now()
        ManualRun.objects.filter(pk=ejecucion_id).update(status=Status.RUNNING, started_at=ahora, updated_at=ahora)
        salida = SalidaEnVivo(ejecucion_id)
        opciones = {"tienda": ejecucion.store_name, "minutos": ejecucion.minutes, "todos": ejecucion.all_prices}
        estado = Status.FINISHED
        try:
            call_command("actualizar_precios", dry_run=ejecucion.dry_run, stdout=salida, stderr=salida, **opciones)
            if not ejecucion.dry_run:
                salida.write("\nRevisando las alertas de baja de precio…\n")
                call_command("enviar_alertas_de_precio", stdout=salida, stderr=salida)
        except Exception as error:  # que la ejecución quede marcada como fallida, no «en curso»
            salida.write(f"\nError: {error.__class__.__name__}: {error}\n")
            estado = Status.FAILED
        resumen = resumen_de_la_salida(salida.texto)
        if estado == Status.FAILED:
            resumen = f"Falló: {salida.texto.strip().splitlines()[-1]}"[: ManualRun.SUMMARY_MAX_LENGTH]
        ManualRun.objects.filter(pk=ejecucion_id).update(
            status=estado, finished_at=timezone.now(), output=salida.texto, summary=resumen
        )
    finally:
        if en_hilo:
            connections.close_all()  # las conexiones de este hilo no las cierra nadie más


# --- En GitHub Actions ---


def _github(metodo, ruta, **opciones):
    respuesta = requests.request(
        metodo,
        f"{GITHUB_API}/repos/{settings.GITHUB_REPOSITORIO}{ruta}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.GITHUB_ACTIONS_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=GITHUB_TIEMPO_DE_ESPERA,
        **opciones,
    )
    return respuesta


def _mensaje_de_github(respuesta):
    try:
        return respuesta.json().get("message", "")
    except ValueError:
        return respuesta.text[:200]


def pedir_a_github(ejecucion):
    ruta = f"/actions/workflows/{settings.GITHUB_WORKFLOW_PRECIOS}/dispatches"
    entradas = {
        "tienda": ejecucion.store_name,
        "minutos": str(ejecucion.minutes),
        "dry_run": "true" if ejecucion.dry_run else "false",
        "todos": "true" if ejecucion.all_prices else "false",
        "solicitud": str(ejecucion.pk),
    }
    try:
        respuesta = _github("POST", ruta, json={"ref": settings.GITHUB_RAMA, "inputs": entradas})
    except requests.RequestException as error:
        motivo = f"No se pudo conectar con GitHub ({error.__class__.__name__})."
    else:
        if respuesta.status_code in (200, 201, 204):
            ManualRun.objects.filter(pk=ejecucion.pk).update(
                github_url=f"https://github.com/{settings.GITHUB_REPOSITORIO}/actions/workflows/{settings.GITHUB_WORKFLOW_PRECIOS}"
            )
            return
        motivo = f"GitHub rechazó la solicitud ({respuesta.status_code}): {_mensaje_de_github(respuesta)}"
    ManualRun.objects.filter(pk=ejecucion.pk).update(
        status=Status.FAILED, finished_at=timezone.now(), summary=motivo[: ManualRun.SUMMARY_MAX_LENGTH]
    )
    raise NoSePuedeEjecutar(motivo)


ESTADOS_DE_GITHUB = {"in_progress": Status.RUNNING, "completed": Status.FINISHED}


def sincronizar_con_github():
    """Busca en GitHub las corridas de las ejecuciones que todavía no terminan y copia su estado.

    Devuelve False si no se pudo consultar GitHub (el panel lo avisa sin romperse).
    """
    pendientes = {
        ejecucion.pk: ejecucion
        for ejecucion in ManualRun.objects.filter(
            runner=Runner.GITHUB, status__in=ManualRun.ACTIVE, created_at__gte=timezone.now() - timedelta(days=2)
        )
    }
    if not pendientes or not github_configurado():
        return True
    try:
        respuesta = _github(
            "GET",
            f"/actions/workflows/{settings.GITHUB_WORKFLOW_PRECIOS}/runs",
            params={"event": "workflow_dispatch", "per_page": 30},
        )
        respuesta.raise_for_status()
        corridas = respuesta.json().get("workflow_runs", [])
    except (requests.RequestException, ValueError):
        return False
    encontradas = set()
    for corrida in corridas:
        titulo = corrida.get("display_title") or ""
        ejecucion = next((e for pk, e in pendientes.items() if f"#{pk}:" in titulo), None)
        if ejecucion is None:
            continue
        encontradas.add(ejecucion.pk)
        estado = ESTADOS_DE_GITHUB.get(corrida.get("status"), Status.PENDING)
        cambios = {"github_run_id": corrida.get("id"), "github_url": corrida.get("html_url") or ejecucion.github_url, "status": estado}
        if corrida.get("run_started_at"):
            cambios["started_at"] = parse_datetime(corrida["run_started_at"])
        if estado == Status.FINISHED:
            conclusion = corrida.get("conclusion") or ""
            if conclusion != "success":
                cambios["status"] = Status.FAILED
            cambios["finished_at"] = parse_datetime(corrida.get("updated_at") or "") or timezone.now()
            cambios["summary"] = {
                "success": "Terminó bien en GitHub Actions. El detalle está en la corrida.",
                "cancelled": "Se canceló en GitHub Actions.",
            }.get(conclusion, f"Falló en GitHub Actions ({conclusion or 'sin conclusión'}).")
        ManualRun.objects.filter(pk=ejecucion.pk).update(**cambios)

    # Si GitHub nunca creó la corrida (o ya no aparece entre las últimas), no se espera para siempre.
    perdidas = [
        pk for pk, ejecucion in pendientes.items()
        if pk not in encontradas and not ejecucion.github_run_id
        and ejecucion.created_at < timezone.now() - timedelta(minutes=max(MINUTOS) + 15)
    ]
    ManualRun.objects.filter(pk__in=perdidas).update(
        status=Status.INTERRUPTED, finished_at=timezone.now(), summary="No se encontró la corrida en GitHub Actions."
    )
    return True


def ultimas_ejecuciones(cantidad=20):
    return ManualRun.objects.select_related("requested_by")[:cantidad]


def ultima_revision_automatica():
    return Prices.objects.aggregate(ultima=Max("updated_at"))["ultima"]
