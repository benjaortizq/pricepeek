"""Pruebas de la ejecución manual de la obtención de datos desde el panel de administración."""

import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests
from django.conf import settings
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from products.models import Prices, Stores
from products.tests import fechas

from . import ejecucion_manual
from .ejecucion_manual import (
    SalidaEnVivo,
    correr_en_el_servidor,
    resumen_de_la_salida,
)
from .models import ManualRun
from .test_actualizacion import (
    API_LECHE,
    URL_LECHE,
    PrecioGuardadoTestCase,
    respuesta_vtex,
)
from .test_scrapers import HttpFalso

CLAVE = "Clave2026segura"
CON_GITHUB = override_settings(
    GITHUB_ACTIONS_TOKEN="token-de-prueba",
    GITHUB_REPOSITORIO="dueno/pricepeek",
)
RESUMEN = "1 revisados · 1 actualizados · 0 sin cambios · 0 con fallo · 0 incidencias"


def respuesta_http(codigo, datos=None):
    return SimpleNamespace(
        status_code=codigo,
        json=lambda: datos or {},
        text="",
        raise_for_status=lambda: None,
    )


class EjecucionManualTestCase(PrecioGuardadoTestCase):
    """Walmart (con web scraping) y una tienda física cuyos precios no se leen de ninguna página."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )
        cls.cliente = User.objects.create_user(
            email="cliente@example.com", password=CLAVE
        )
        cls.fisica = Stores.objects.create(name="Tienda física", **fechas())
        cls.precio(
            cls.variante_ketchup, cls.fisica, 1500
        )  # su enlace es de tienda.test: sin extractor

    def setUp(self):
        super().setUp()
        self.fila = self.guardado(url=URL_LECHE, precio=1760)
        self.client.force_login(self.admin)
        self.llamadas = []

    def pedir(self, donde="server", **datos):
        datos = {
            "comercio": self.walmart.pk,
            "donde": donde,
            "minutos": "20",
            "todos": "on",
            **datos,
        }
        return self.client.post(
            reverse("ejecutar_obtencion"), datos, follow=True
        )

    def pedir_en_el_servidor(self, comando=None, **datos):
        """Pide la ejecución y la corre aquí mismo, como lo haría el hilo."""

        def correr(pk):
            correr_en_el_servidor(pk)

        with (
            mock.patch.object(
                ejecucion_manual, "iniciar_en_el_servidor", side_effect=correr
            ),
            mock.patch.object(
                ejecucion_manual,
                "call_command",
                side_effect=comando or self.comando_falso,
            ),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                respuesta = self.pedir(**datos)
        return respuesta

    def comando_falso(self, nombre, stdout=None, stderr=None, **opciones):
        """Reemplaza a call_command: anota qué se pidió y escribe una salida como la real."""
        self.llamadas.append((nombre, opciones))
        stdout.write(
            f"Revisando {opciones.get('tienda', '')}…\n{RESUMEN}\n"
            if nombre == "actualizar_precios"
            else "Revisados: 0.\n"
        )


class AccesoTests(EjecucionManualTestCase):
    def test_solo_el_administrador(self):
        self.client.logout()
        self.assertIn(
            reverse("login"),
            self.client.get(reverse("obtencion_de_datos")).url,
        )
        self.client.force_login(self.cliente)
        self.assertEqual(
            self.client.get(reverse("obtencion_de_datos")).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("ejecutar_obtencion"), {"comercio": self.walmart.pk}
            ).status_code,
            403,
        )
        self.assertFalse(ManualRun.objects.exists())

    def test_solo_por_post(self):
        self.assertEqual(
            self.client.get(reverse("ejecutar_obtencion")).status_code, 405
        )


class ComerciosTests(EjecucionManualTestCase):
    def test_muestra_solo_los_comercios_con_web_scraping(self):
        respuesta = self.client.get(reverse("obtencion_de_datos"))
        nombres = [
            comercio["nombre"] for comercio in respuesta.context["comercios"]
        ]
        self.assertEqual(nombres, ["Walmart"])
        self.assertNotContains(respuesta, "Tienda física")
        self.assertContains(respuesta, f'href="#ejecutar-{self.walmart.pk}"')
        self.assertContains(respuesta, f'id="ejecutar-{self.walmart.pk}"')

    def test_cuenta_los_precios_y_los_desactualizados(self):
        comercio = ejecucion_manual.comercio_con_scraping(self.walmart.pk)
        self.assertEqual(
            (comercio["precios"], comercio["desactualizados"]), (1, 1)
        )  # revisado hace tres días

    def test_se_llega_desde_la_barra_lateral(self):
        self.assertContains(
            self.client.get(reverse("inicio_administrador")),
            f'href="{reverse("obtencion_de_datos")}"',
        )

    @override_settings(GITHUB_ACTIONS_TOKEN="", GITHUB_REPOSITORIO="")
    def test_sin_configurar_github_la_opcion_aparece_desactivada(self):
        respuesta = self.client.get(reverse("obtencion_de_datos"))
        self.assertContains(
            respuesta,
            "Falta configurar GITHUB_ACTIONS_TOKEN y GITHUB_REPOSITORIO en el servidor.",
        )
        self.assertContains(respuesta, 'value="github" disabled')


class EnElServidorTests(EjecucionManualTestCase):
    def test_corre_la_actualizacion_del_comercio_y_despues_las_alertas(self):
        respuesta = self.pedir_en_el_servidor()
        self.assertContains(
            respuesta,
            "Empezó la obtención de datos de Walmart en el servidor.",
        )
        self.assertEqual(
            self.llamadas,
            [
                (
                    "actualizar_precios",
                    {
                        "tienda": "Walmart",
                        "minutos": 20,
                        "todos": True,
                        "dry_run": False,
                    },
                ),
                ("enviar_alertas_de_precio", {}),
            ],
        )
        ejecucion = ManualRun.objects.get()
        self.assertEqual(
            (ejecucion.status, ejecucion.runner, ejecucion.requested_by),
            (ManualRun.Status.FINISHED, "server", self.admin),
        )
        self.assertEqual(ejecucion.summary, RESUMEN)
        self.assertIn("Revisando Walmart", ejecucion.output)
        self.assertIsNotNone(ejecucion.started_at)
        self.assertIsNotNone(ejecucion.finished_at)

    def test_en_modo_de_prueba_no_revisa_las_alertas(self):
        self.pedir_en_el_servidor(prueba="on", todos="", minutos="45")
        self.assertEqual(
            self.llamadas,
            [
                (
                    "actualizar_precios",
                    {
                        "tienda": "Walmart",
                        "minutos": 45,
                        "todos": False,
                        "dry_run": True,
                    },
                )
            ],
        )

    def test_si_el_comando_falla_queda_marcada_como_fallida(self):
        def falla(nombre, stdout=None, stderr=None, **opciones):
            raise CommandError("--minutos tiene que ser mayor que 0.")

        self.pedir_en_el_servidor(comando=falla)
        ejecucion = ManualRun.objects.get()
        self.assertEqual(ejecucion.status, ManualRun.Status.FAILED)
        self.assertIn(
            "CommandError: --minutos tiene que ser mayor que 0.",
            ejecucion.summary,
        )

    def test_no_deja_correr_dos_a_la_vez_para_el_mismo_comercio(self):
        ManualRun.objects.create(
            store_name="Walmart",
            runner="server",
            status=ManualRun.Status.RUNNING,
        )
        respuesta = self.pedir()
        self.assertContains(
            respuesta,
            "Ya hay una ejecución en curso para Walmart; espere a que termine.",
        )
        self.assertEqual(ManualRun.objects.count(), 1)

    def test_una_que_dejo_de_dar_noticias_se_marca_como_interrumpida(self):
        vieja = ManualRun.objects.create(
            store_name="Walmart",
            runner="server",
            status=ManualRun.Status.RUNNING,
        )
        ManualRun.objects.filter(pk=vieja.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30)
        )
        self.client.get(reverse("obtencion_de_datos"))
        vieja.refresh_from_db()
        self.assertEqual(vieja.status, ManualRun.Status.INTERRUPTED)
        self.pedir_en_el_servidor()  # ya no bloquea una nueva
        self.assertEqual(
            ManualRun.objects.filter(status=ManualRun.Status.FINISHED).count(),
            1,
        )

    def test_rechaza_comercios_sin_web_scraping_y_opciones_desconocidas(self):
        self.assertContains(
            self.pedir(comercio=self.fisica.pk),
            "Ese comercio no tiene precios que se obtengan por web scraping.",
        )
        self.assertContains(
            self.pedir(donde="otro"),
            "Elija dónde ejecutar la obtención de datos.",
        )
        self.assertFalse(ManualRun.objects.exists())

    @override_settings(OBTENCION_EN_EL_SERVIDOR=False)
    def test_se_puede_desactivar_en_el_servidor(self):
        self.assertContains(
            self.pedir(), "La ejecución en el servidor está desactivada."
        )

    def test_de_punta_a_punta_actualiza_el_precio_en_su_tienda(self):
        """Sin reemplazar el comando: actualizar_precios revisa la página (falsa) de Walmart."""
        http = HttpFalso({API_LECHE: respuesta_vtex(lista=1900, final=1900)})
        sin_alertas = SimpleNamespace(
            revisados=0, productos_con_baja=0, correos_enviados=0, errores=0
        )
        with (
            mock.patch(
                "ingestion.management.commands.actualizar_precios.ClienteHttp",
                return_value=http,
            ),
            mock.patch(
                "wishlist.management.commands.enviar_alertas_de_precio.revisar_alertas_de_baja_de_precio",
                return_value=sin_alertas,
            ),
            mock.patch.object(
                ejecucion_manual,
                "iniciar_en_el_servidor",
                side_effect=correr_en_el_servidor,
            ),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.pedir()
        self.assertEqual(Prices.objects.get(pk=self.fila.pk).price, 1900)
        ejecucion = ManualRun.objects.get()
        self.assertEqual(ejecucion.status, ManualRun.Status.FINISHED)
        self.assertTrue(
            ejecucion.summary.startswith("1 revisados · 1 actualizados")
        )
        self.assertIn("Correos enviados: 0.", ejecucion.output)

    def test_la_salida_se_guarda_mientras_avanza(self):
        ejecucion = ManualRun.objects.create(
            store_name="Walmart", runner="server"
        )
        salida = SalidaEnVivo(ejecucion.pk)
        salida.write("Primera línea\n")
        salida.guardar()
        ejecucion.refresh_from_db()
        self.assertEqual(ejecucion.output, "Primera línea\n")
        self.assertEqual(
            resumen_de_la_salida(f"algo\n{RESUMEN}\nTardó 2 min.\n"), RESUMEN
        )


@CON_GITHUB
class EnGitHubTests(EjecucionManualTestCase):
    def test_pide_la_corrida_del_workflow_con_el_comercio_y_la_solicitud(self):
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            return_value=respuesta_http(204),
        ) as peticion:
            respuesta = self.pedir("github")
        self.assertContains(
            respuesta,
            "Se pidió a GitHub Actions la obtención de datos de Walmart",
        )
        ejecucion = ManualRun.objects.get()
        self.assertEqual(
            (ejecucion.status, ejecucion.runner),
            (ManualRun.Status.PENDING, "github"),
        )
        pedido = peticion.call_args_list[
            0
        ]  # después, la página consulta el estado de la corrida
        metodo, url = pedido.args
        self.assertEqual(metodo, "POST")
        self.assertEqual(
            url,
            "https://api.github.com/repos/dueno/pricepeek/actions/workflows/actualizar-precios.yml/dispatches",
        )
        self.assertEqual(
            pedido.kwargs["headers"]["Authorization"], "Bearer token-de-prueba"
        )
        self.assertEqual(
            pedido.kwargs["json"],
            {
                "ref": "main",
                "inputs": {
                    "tienda": "Walmart",
                    "minutos": "20",
                    "dry_run": "false",
                    "todos": "true",
                    "solicitud": str(ejecucion.pk),
                },
            },
        )
        self.assertIn(
            "github.com/dueno/pricepeek/actions", ejecucion.github_url
        )

    def test_si_github_la_rechaza_lo_avisa(self):
        rechazo = respuesta_http(
            422, {"message": "Unexpected inputs provided"}
        )
        with mock.patch.object(
            ejecucion_manual.requests, "request", return_value=rechazo
        ):
            respuesta = self.pedir("github")
        self.assertContains(
            respuesta,
            "GitHub rechazó la solicitud (422): Unexpected inputs provided",
        )
        self.assertEqual(
            ManualRun.objects.get().status, ManualRun.Status.FAILED
        )

    def test_sin_conexion_con_github(self):
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            side_effect=requests.ConnectionError(),
        ):
            respuesta = self.pedir("github")
        self.assertContains(
            respuesta, "No se pudo conectar con GitHub (ConnectionError)."
        )

    @override_settings(GITHUB_ACTIONS_TOKEN="")
    def test_sin_token_no_se_puede(self):
        self.assertContains(
            self.pedir("github"),
            "GitHub Actions no está configurado en este servidor.",
        )
        self.assertFalse(ManualRun.objects.exists())

    def test_copia_el_estado_de_la_corrida_en_github(self):
        ejecucion = ManualRun.objects.create(
            store_name="Walmart", runner="github"
        )
        corridas = {
            "workflow_runs": [
                {
                    "id": 1,
                    "display_title": "Ejecución manual #999: Gollo",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 77,
                    "display_title": f"Ejecución manual #{ejecucion.pk}: Walmart",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/dueno/pricepeek/actions/runs/77",
                    "run_started_at": "2026-11-24T10:00:00Z",
                    "updated_at": "2026-11-24T10:12:00Z",
                },
            ]
        }
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            return_value=respuesta_http(200, corridas),
        ) as peticion:
            respuesta = self.client.get(reverse("obtencion_de_datos"))
        self.assertEqual(
            peticion.call_args.kwargs["params"],
            {"event": "workflow_dispatch", "per_page": 30},
        )
        ejecucion.refresh_from_db()
        self.assertEqual(
            (ejecucion.status, ejecucion.github_run_id),
            (ManualRun.Status.FINISHED, 77),
        )
        self.assertEqual(
            ejecucion.github_url,
            "https://github.com/dueno/pricepeek/actions/runs/77",
        )
        self.assertContains(respuesta, "Terminó bien en GitHub Actions.")

    def test_una_corrida_fallida_en_github(self):
        ejecucion = ManualRun.objects.create(
            store_name="Walmart", runner="github"
        )
        corridas = {
            "workflow_runs": [
                {
                    "id": 5,
                    "display_title": f"Ejecución manual #{ejecucion.pk}: Walmart",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        }
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            return_value=respuesta_http(200, corridas),
        ):
            self.client.get(reverse("obtencion_de_datos"))
        ejecucion.refresh_from_db()
        self.assertEqual(
            (ejecucion.status, ejecucion.summary),
            (ManualRun.Status.FAILED, "Falló en GitHub Actions (failure)."),
        )

    def test_si_no_se_puede_consultar_github_la_pagina_lo_avisa(self):
        ManualRun.objects.create(store_name="Walmart", runner="github")
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            side_effect=requests.Timeout(),
        ):
            respuesta = self.client.get(reverse("obtencion_de_datos"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            "No se pudo consultar el estado de las corridas en GitHub",
        )

    def test_una_corrida_que_github_nunca_creo_no_queda_en_cola_para_siempre(
        self,
    ):
        perdida = ManualRun.objects.create(
            store_name="Walmart", runner="github"
        )
        ManualRun.objects.filter(pk=perdida.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )
        with mock.patch.object(
            ejecucion_manual.requests,
            "request",
            return_value=respuesta_http(200, {"workflow_runs": []}),
        ):
            self.client.get(reverse("obtencion_de_datos"))
        perdida.refresh_from_db()
        self.assertEqual(perdida.status, ManualRun.Status.INTERRUPTED)


class WorkflowTests(EjecucionManualTestCase):
    def test_el_workflow_acepta_lo_que_le_pide_el_panel(self):
        workflow = (
            Path(settings.BASE_DIR)
            / ".github"
            / "workflows"
            / "actualizar-precios.yml"
        ).read_text(encoding="utf-8")
        for entrada in (
            "tienda:",
            "minutos:",
            "dry_run:",
            "todos:",
            "solicitud:",
        ):
            self.assertIn(f"      {entrada}", workflow)
        # El panel encuentra la corrida por «#<número>:» en su nombre.
        self.assertIn("format('Ejecución manual #{0}: {1}'", workflow)
        self.assertIn("$TODOS", workflow)


class HiloDelServidorTests(SimpleTestCase):
    """El hilo de verdad (la base de pruebas no se comparte entre hilos: aquí no se toca)."""

    def test_la_ejecucion_corre_en_un_hilo_aparte_que_cierra_sus_conexiones(
        self,
    ):
        corrio = threading.Event()
        visto = {}

        def correr(ejecucion_id, en_hilo=False):
            hilo = threading.current_thread()
            visto.update(
                id=ejecucion_id,
                en_hilo=en_hilo,
                nombre=hilo.name,
                aparte=hilo is not threading.main_thread(),
                daemon=hilo.daemon,
            )
            corrio.set()

        with mock.patch.object(
            ejecucion_manual, "correr_en_el_servidor", side_effect=correr
        ):
            ejecucion_manual.iniciar_en_el_servidor(7)
            self.assertTrue(corrio.wait(timeout=10))
        self.assertEqual(
            visto,
            {
                "id": 7,
                "en_hilo": True,
                "nombre": "obtencion-manual-7",
                "aparte": True,
                "daemon": True,
            },
        )

    def test_la_salida_no_se_guarda_al_cerrarse(self):
        salida = SalidaEnVivo(1)
        salida.write(
            "texto"
        )  # menos de GUARDAR_SALIDA_CADA segundos: todavía no la guarda
        salida.close()  # ni al cerrarse (correr_en_el_servidor guarda la final); sin base, fallaría
        self.assertEqual(salida.texto, "texto")
