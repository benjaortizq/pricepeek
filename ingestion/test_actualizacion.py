"""Pruebas de la actualización de precios y del comando actualizar_precios."""

import re
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from products.models import AuditPriceChanges, Prices, ProductView, Stores
from products.tests import CatalogoTestCase, fechas

from .actualizacion import ACTUALIZADO, FALLO, NO_SOPORTADA, SIN_CAMBIOS, elegir_oferta, expandir_upc_e, revisar
from .models import Incident
from .scrapers import CodigoDistinto, ErrorDescarga, Oferta, PrecioNoEncontrado, ProductoNoEncontrado
from .test_scrapers import HttpFalso, muestra

GTIN_LECHE = "7441001234567"  # el de CatalogoTestCase.variante_leche
URL_LECHE = "https://www.walmart.co.cr/leche-entera-1l/p"
API_LECHE = "https://www.walmart.co.cr/api/catalog_system/pub/products/search/leche-entera-1l/p"


def respuesta_vtex(ean=GTIN_LECHE, lista=1760, final=1760, disponible=True):
    detalle = {"ListPrice": lista, "Price": final, "IsAvailable": disponible, "AvailableQuantity": 5}
    return [{"items": [{"ean": ean, "sellers": [{"sellerDefault": True, "commertialOffer": detalle}]}]}]


class ElegirOfertaTests(CatalogoTestCase):
    def test_elige_la_oferta_con_el_codigo_guardado_aunque_tenga_otro_largo(self):
        cara = Oferta(2000, 2000, True, ("07441001234574",))
        buscada = Oferta(1760, 1760, True, ("7441001234567",))
        self.assertIs(elegir_oferta([cara, buscada], "07441001234567"), buscada)

    def test_basta_con_uno_de_los_codigos_de_la_tienda(self):
        oferta = Oferta(6350, 6350, True, ("088169002950", GTIN_LECHE))
        self.assertIs(elegir_oferta([oferta], GTIN_LECHE), oferta)

    def test_codigo_distinto(self):
        with self.assertRaisesMessage(CodigoDistinto, "7401006400901"):
            elegir_oferta([Oferta(2042, 2042, True, ("7401006400901",))], "7441003500907")

    def test_reconoce_el_upc_e_como_el_mismo_codigo(self):
        # Caso real: Peri y Megasuper reportan la salsa Heinz como UPC-E 01307605 (= UPC-A 013000000765).
        oferta = Oferta(2380, 2380, True, ("01307605", "01364008"))
        self.assertIs(elegir_oferta([oferta], "0013000000765"), oferta)
        self.assertEqual(expandir_upc_e("01307605"), "013000000765")
        self.assertEqual(expandir_upc_e("04252614"), "042100005264")  # el ejemplo clásico de UPC-E
        self.assertIsNone(expandir_upc_e("01307606"))  # dígito verificador incorrecto
        self.assertIsNone(expandir_upc_e("74410012"))  # empieza con 7: es un EAN-8, no un UPC-E
        with self.assertRaises(CodigoDistinto):
            elegir_oferta([Oferta(2380, 2380, True, ("01307606",))], "0013000000765")

    def test_sin_codigos_se_confia_en_la_url_si_hay_una_sola_oferta(self):
        oferta = Oferta(3230, 2745, True)
        self.assertIs(elegir_oferta([oferta], GTIN_LECHE), oferta)
        with self.assertRaises(PrecioNoEncontrado):
            elegir_oferta([oferta, Oferta(100, 100, True)], GTIN_LECHE)


class PrecioGuardadoTestCase(CatalogoTestCase):
    """Un precio de la leche en Walmart, revisado por última vez hace tres días."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.walmart = Stores.objects.create(name="Walmart\n", **fechas())
        cls.hace_tres_dias = timezone.now() - timedelta(days=3)

    def guardado(self, url=URL_LECHE, precio=1760, descuento="0", disponible=True):
        fila = self.precio(self.variante_leche, self.walmart, precio, descuento, disponible)
        Prices.objects.filter(pk=fila.pk).update(product_web_url=url, updated_at=self.hace_tres_dias)
        return self.recargar(fila)

    def recargar(self, fila):
        return Prices.objects.select_related("id_store", "gtin").get(pk=fila.pk)


class RevisarTests(PrecioGuardadoTestCase):
    def revisar(self, fila, respuesta, guardar=True):
        return revisar(fila, HttpFalso({API_LECHE: respuesta}), guardar=guardar)

    def test_actualiza_precio_descuento_y_disponibilidad(self):
        fila = self.guardado(precio=1760, disponible=False)
        revision = self.revisar(fila, respuesta_vtex(lista=2000, final=1500))
        self.assertEqual(revision.resultado, ACTUALIZADO)
        fila = self.recargar(fila)
        self.assertEqual((fila.price, fila.discount, fila.is_available), (2000, Decimal("0.25"), True))
        self.assertGreater(fila.updated_at, self.hace_tres_dias)
        self.assertEqual(Incident.objects.count(), 0)

        auditoria = AuditPriceChanges.objects.get()
        self.assertEqual((auditoria.old_price, auditoria.new_price), (1760, 2000))
        self.assertEqual(auditoria.old_discount, Decimal("0.00"))
        self.assertEqual(auditoria.new_discount, Decimal("0.25"))
        self.assertTrue(auditoria.is_active)
        self.assertIsNone(auditoria.id_requested_by)
        self.assertEqual(auditoria.id_store_id, self.walmart.pk)
        self.assertEqual(auditoria.gtin_id, self.variante_leche.gtin)

    def test_sin_cambios_igual_marca_la_fecha_de_verificacion(self):
        fila = self.guardado(precio=1760)
        revision = self.revisar(fila, respuesta_vtex(lista=1760, final=1760))
        self.assertEqual((revision.resultado, revision.cambios), (SIN_CAMBIOS, {}))
        self.assertGreater(self.recargar(fila).updated_at, self.hace_tres_dias)
        self.assertFalse(AuditPriceChanges.objects.exists())

    def test_dry_run_no_guarda_nada(self):
        fila = self.guardado(precio=1760)
        revision = self.revisar(fila, respuesta_vtex(lista=1800, final=1800), guardar=False)
        self.assertEqual(revision.cambios, {"price": (1760, 1800)})
        fila = self.recargar(fila)
        self.assertEqual((fila.price, fila.updated_at), (1760, self.hace_tres_dias))

        revision = self.revisar(fila, respuesta_vtex(ean="7401006400901"), guardar=False)
        self.assertIsNotNone(revision.incidencia)
        self.assertEqual(Incident.objects.count(), 0)

    def test_agotado_conserva_el_ultimo_precio(self):
        fila = self.guardado(precio=1760)
        self.revisar(fila, respuesta_vtex(lista=0, final=0, disponible=False))
        fila = self.recargar(fila)
        self.assertEqual((fila.price, fila.is_available), (1760, False))

    def test_no_audita_un_precio_que_antes_era_null(self):
        fila = self.guardado(precio=None, disponible=False)

        self.revisar(fila, respuesta_vtex(lista=1800, final=1800))

        fila = self.recargar(fila)
        self.assertEqual((fila.price, fila.is_available), (1800, True))
        self.assertFalse(AuditPriceChanges.objects.exists())

    def test_producto_que_ya_no_existe_queda_no_disponible_con_incidencia(self):
        fila = self.guardado(precio=1760)
        revision = self.revisar(fila, ProductoNoEncontrado("404"))
        self.assertEqual(revision.cambios, {"is_available": (True, False)})
        self.assertFalse(self.recargar(fila).is_available)
        auditoria = AuditPriceChanges.objects.get()
        self.assertEqual((auditoria.old_price, auditoria.new_price), (1760, 1760))
        self.assertFalse(auditoria.is_active)
        self.assertIsNone(auditoria.id_requested_by)
        incidencia = Incident.objects.get()
        self.assertEqual(incidencia.kind, Incident.Kind.PRODUCT_NOT_FOUND)
        self.assertEqual((incidencia.store_name, incidencia.gtin), ("Walmart", GTIN_LECHE))
        self.assertIn(URL_LECHE, incidencia.reason)

    def test_si_falla_la_descarga_no_toca_el_precio(self):
        fila = self.guardado(precio=1760)
        revision = self.revisar(fila, ErrorDescarga("Timeout"))
        self.assertEqual(revision.resultado, FALLO)
        fila = self.recargar(fila)
        self.assertEqual((fila.price, fila.is_available, fila.updated_at), (1760, True, self.hace_tres_dias))
        self.assertEqual(Incident.objects.get().kind, Incident.Kind.DOWNLOAD_FAILED)

    def test_codigo_de_barras_distinto_no_actualiza(self):
        fila = self.guardado(precio=1760)
        revision = self.revisar(fila, respuesta_vtex(ean="7401006400901", lista=900, final=900))
        self.assertEqual(revision.resultado, FALLO)
        self.assertEqual(self.recargar(fila).price, 1760)
        self.assertEqual(Incident.objects.get().kind, Incident.Kind.BARCODE_MISMATCH)

    def test_cambio_sospechoso_no_se_guarda(self):
        fila = self.guardado(precio=2000, descuento="0.25")  # se muestra a ₡1.500
        revision = self.revisar(fila, respuesta_vtex(lista=150, final=150))
        self.assertEqual(revision.resultado, FALLO)
        self.assertEqual(self.recargar(fila).price, 2000)
        incidencia = Incident.objects.get()
        self.assertEqual(incidencia.kind, Incident.Kind.SUSPICIOUS_PRICE)
        self.assertIn("1500 a 150", incidencia.reason)

    def test_un_cambio_normal_no_es_sospechoso(self):
        fila = self.guardado(precio=2000, descuento="0.25")
        self.assertEqual(self.revisar(fila, respuesta_vtex(lista=2000, final=2000)).resultado, ACTUALIZADO)

    def test_un_error_inesperado_del_extractor_queda_como_incidencia(self):
        fila = self.guardado()
        revision = self.revisar(fila, [{"items": "esto no es una lista"}])
        self.assertEqual(revision.resultado, FALLO)
        self.assertIn("Error inesperado", Incident.objects.get().reason)

    def test_tienda_no_soportada(self):
        fila = self.guardado(url="https://www.pequeno-mundo.com/producto/1")
        revision = revisar(fila, HttpFalso())
        self.assertEqual(revision.resultado, NO_SOPORTADA)
        self.assertEqual(Incident.objects.count(), 0)

    def test_caso_real_de_megasuper_con_otro_codigo(self):
        url = "https://www.megasuper.com/p/refresco-gaseoso-envase-desechable-coca-cola-25ml-7401006400901"
        fila = self.guardado(url=url)
        revision = revisar(fila, HttpFalso({url: muestra("megasuper_coca_cola.html")}))
        self.assertEqual(revision.incidencia.kind, Incident.Kind.BARCODE_MISMATCH)


@override_settings(PRECIOS_FRECUENCIA_HORAS=24)
class ComandoActualizarPreciosTests(PrecioGuardadoTestCase):
    def correr(self, respuestas, *argumentos):
        salida = StringIO()
        with mock.patch(
            "ingestion.management.commands.actualizar_precios.ClienteHttp",
            return_value=HttpFalso(respuestas),
        ):
            call_command("actualizar_precios", *argumentos, stdout=salida)
        return salida.getvalue()

    def test_actualiza_y_resume(self):
        fila = self.guardado(precio=1760)
        salida = self.correr({API_LECHE: respuesta_vtex(lista=1900, final=1900)})
        self.assertIn("Walmart · Leche entera 1L: precio ₡1.760 → ₡1.900", salida)
        self.assertIn("1 revisados · 1 actualizados · 0 sin cambios · 0 con fallo · 0 incidencias", salida)
        self.assertEqual(self.recargar(fila).price, 1900)

    def test_se_salta_los_revisados_hace_menos_de_la_frecuencia(self):
        fila = self.guardado(precio=1760)
        Prices.objects.filter(pk=fila.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        self.assertIn("No hay precios pendientes", self.correr({}))
        salida = self.correr({API_LECHE: respuesta_vtex()}, "--todos")
        self.assertIn("1 revisados", salida)

    def test_dry_run(self):
        fila = self.guardado(precio=1760)
        salida = self.correr({API_LECHE: respuesta_vtex(lista=1900, final=1900)}, "--dry-run")
        self.assertIn("no se guardará nada", salida)
        self.assertIn("₡1.760 → ₡1.900", salida)
        self.assertEqual(self.recargar(fila).price, 1760)

    def test_filtra_por_tienda_y_limite(self):
        self.guardado()
        self.assertIn("No hay precios pendientes", self.correr({}, "--tienda", "automercado"))
        self.assertIn("1 revisados", self.correr({API_LECHE: respuesta_vtex()}, "--tienda", "WAL", "--limite", "1"))

    def test_muestra_las_incidencias(self):
        self.guardado()
        salida = self.correr({API_LECHE: ErrorDescarga("La tienda respondió con el código 503.")})
        self.assertIn("No se pudo descargar la página. La tienda respondió con el código 503.", salida)
        self.assertIn("1 con fallo · 1 incidencias", salida)


COMANDO = "ingestion.management.commands.actualizar_precios"


class RelojFalso:
    """Reemplaza a time.monotonic: el tiempo solo pasa cuando se revisa un precio."""

    def __init__(self):
        self.ahora = 0.0

    def __call__(self):
        return self.ahora


class PrioridadYTiempoTests(PrecioGuardadoTestCase):
    """El orden en que se revisan los precios, el tiempo estimado y --minutos."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.variante_yogur = cls.variante(cls.producto("Yogur natural", cls.dos_pinos, cls.lacteos), "7441001234598")

    def pendiente(self, variante, dias):
        """Un precio revisado hace `dias` días, de una URL que no es de una tienda soportada (no hace peticiones)."""
        fila = self.precio(variante, self.walmart, 1000)
        Prices.objects.filter(pk=fila.pk).update(updated_at=timezone.now() - timedelta(days=dias))

    def tres_pendientes(self):
        self.pendiente(self.variante_leche, dias=2)
        self.pendiente(self.variante_ketchup, dias=5)
        self.pendiente(self.variante_yogur, dias=3)

    def correr(self, *argumentos, segundos_por_precio=0):
        reloj = RelojFalso()

        def revisar_y_tardar(precio, http, guardar=True):
            reloj.ahora += segundos_por_precio
            return revisar(precio, http, guardar=guardar)

        salida = StringIO()
        with (
            mock.patch(f"{COMANDO}.ClienteHttp", return_value=HttpFalso()),
            mock.patch(f"{COMANDO}.reloj", reloj),
            mock.patch(f"{COMANDO}.revisar", side_effect=revisar_y_tardar),
        ):
            call_command("actualizar_precios", *argumentos, stdout=salida)
        return salida.getvalue()

    def orden(self, salida):
        return re.findall(r"\] Walmart · (.+?): tienda no soportada", salida)

    def test_primero_los_mas_vistos_y_despues_los_que_llevan_mas_sin_revisarse(self):
        self.tres_pendientes()
        ProductView.objects.create(product_id=self.leche.pk, visitor="u1", hour=timezone.now())
        salida = self.correr()
        # La leche es la que se revisó hace menos, pero es la única que alguien vio esta semana.
        self.assertEqual(self.orden(salida), ["Leche entera 1L", "Salsa de tomate", "Yogur natural"])
        self.assertIn("Primero 1 precio de productos vistos en los últimos 7 días", salida)

    def test_dice_cuantos_hay_de_cada_tienda_y_cuanto_se_tardaria(self):
        self.tres_pendientes()
        salida = self.correr()
        self.assertIn("Se van a revisar 3 precios: Walmart 3", salida)
        self.assertIn("Tiempo estimado: menos de 1 min (unos 2 s por precio).", salida)
        self.assertNotIn("Primero", salida)  # nadie ha visto nada todavía
        self.assertEqual(self.orden(salida), ["Salsa de tomate", "Yogur natural", "Leche entera 1L"])

    def test_si_no_alcanza_el_tiempo_dice_cuantos_caben(self):
        self.tres_pendientes()
        salida = self.correr("--minutos", "1", "--pausa", "30")
        self.assertIn(
            "Tiempo estimado: ~2 min (unos 30 s por precio). Con --minutos 1 alcanza para unos 2; "
            "los demás quedan para la próxima vez.",
            salida,
        )

    def test_con_minutos_para_cuando_se_acaba_el_tiempo(self):
        self.tres_pendientes()
        salida = self.correr("--minutos", "1", segundos_por_precio=40)
        # A los 40 s empieza el segundo; a los 80 s ya pasó el minuto y el tercero no se revisa.
        self.assertEqual(self.orden(salida), ["Salsa de tomate", "Yogur natural"])
        self.assertIn("2 revisados", salida)
        self.assertIn("Tardó 1 min.", salida)
        self.assertIn(
            "Se acabó el tiempo (--minutos 1): queda 1 precio para la próxima vez, los menos vistos y revisados hace menos.",
            salida,
        )

    @mock.patch(f"{COMANDO}.AVISAR_CADA", 1)
    def test_avisa_cuanto_falta_segun_lo_que_ha_tardado(self):
        self.tres_pendientes()
        salida = self.correr(segundos_por_precio=120)
        self.assertIn("  … 1/3 en 2 min; faltan ~4 min", salida)
        self.assertIn("  … 2/3 en 4 min; faltan ~2 min", salida)
        self.assertNotIn("3/3 en", salida)  # al terminar ya no hace falta

    def test_minutos_tiene_que_ser_mayor_que_cero(self):
        with self.assertRaisesMessage(CommandError, "--minutos tiene que ser mayor que 0."):
            call_command("actualizar_precios", "--minutos", "0", stdout=StringIO())
