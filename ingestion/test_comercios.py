"""Issue «Gestión de comercios asociados»: la obtención de datos respeta lo que definió el administrador.

Con web scraping y activo, se revisan sus precios; desactivado o con datos provistos por el
comercio, no.
"""

from io import StringIO
from unittest import mock

from django.core.management import call_command

from products.models import PartnerStore

from .ejecucion_manual import comercios_con_scraping
from .test_actualizacion import (
    API_LECHE,
    PrecioGuardadoTestCase,
    respuesta_vtex,
)
from .test_scrapers import HttpFalso

SCRAPING = PartnerStore.DataSource.SCRAPING
PROVISTOS = PartnerStore.DataSource.PROVIDED


class ObtencionSegunElComercioTests(PrecioGuardadoTestCase):
    def setUp(self):
        super().setUp()
        self.fila = self.guardado(precio=1760)

    def configurar(self, mecanismo, activo):
        PartnerStore.objects.create(
            store=self.walmart, data_source=mecanismo, is_active=activo
        )

    def correr(self):
        salida = StringIO()
        with mock.patch(
            "ingestion.management.commands.actualizar_precios.ClienteHttp",
            return_value=HttpFalso(
                {API_LECHE: respuesta_vtex(lista=1900, final=1900)}
            ),
        ):
            call_command("actualizar_precios", stdout=salida)
        return salida.getvalue()

    def test_con_web_scraping_y_activo_se_revisa(self):
        self.configurar(SCRAPING, True)
        self.assertIn("1 revisados · 1 actualizados", self.correr())
        self.assertEqual(self.recargar(self.fila).price, 1900)
        self.assertEqual(
            [comercio["nombre"] for comercio in comercios_con_scraping()],
            ["Walmart"],
        )

    def test_desactivado_no_se_revisa(self):
        self.configurar(SCRAPING, False)
        salida = self.correr()
        self.assertIn(
            "Se omiten (desactivados o con datos provistos por el comercio): Walmart.",
            salida,
        )
        self.assertIn("No hay precios pendientes", salida)
        self.assertEqual(self.recargar(self.fila).price, 1760)
        self.assertEqual(comercios_con_scraping(), [])

    def test_con_datos_provistos_por_el_comercio_no_se_revisa(self):
        self.configurar(PROVISTOS, True)
        self.assertIn("No hay precios pendientes", self.correr())
        self.assertEqual(self.recargar(self.fila).price, 1760)
        self.assertEqual(comercios_con_scraping(), [])

    def test_sin_configurar_sigue_como_antes(self):
        salida = self.correr()
        self.assertNotIn("Se omiten", salida)
        self.assertIn("1 revisados", salida)
