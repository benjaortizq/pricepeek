from django.test import TestCase

from .models import Incident
from .services import filtrar_productos_con_codigo_valido

EAN_13 = "4006381333931"
UPC_A = "036000291452"


class FiltrarProductosConCodigoValidoTests(TestCase):
    def setUp(self):
        self.productos = [
            {"name": "Leche", "gtin": EAN_13, "price": 1500},
            {"name": "Arroz", "gtin": "4006381333932", "price": 900},
            {"name": "Sin código", "gtin": ""},
            {"name": "Atún", "gtin": UPC_A, "price": 1200},
        ]

    def test_deja_pasar_los_validos_y_registra_los_invalidos(self):
        validos = filtrar_productos_con_codigo_valido(self.productos, tienda="Automercado")
        self.assertEqual([p["name"] for p in validos], ["Leche", "Atún"])
        self.assertEqual(Incident.objects.count(), 2)

    def test_los_validos_salen_con_el_codigo_normalizado_y_conservan_sus_datos(self):
        validos = filtrar_productos_con_codigo_valido(self.productos)
        self.assertEqual(validos[0]["gtin"], "04006381333931")
        self.assertEqual(validos[1]["gtin"], "00036000291452")  # UPC-A de 12 dígitos
        self.assertEqual(validos[1]["price"], 1200)

    def test_no_modifica_los_productos_recibidos(self):
        filtrar_productos_con_codigo_valido(self.productos)
        self.assertEqual(self.productos[3]["gtin"], UPC_A)

    def test_la_incidencia_guarda_comercio_producto_codigo_y_motivo(self):
        filtrar_productos_con_codigo_valido(self.productos, tienda="Automercado")
        incidencia = Incident.objects.get(product_name="Arroz")
        self.assertEqual(incidencia.kind, Incident.Kind.INVALID_BARCODE)
        self.assertEqual(incidencia.store_name, "Automercado")
        self.assertEqual(incidencia.gtin, "4006381333932")
        self.assertIn("dígito verificador", incidencia.reason)

    def test_producto_sin_codigo_o_sin_la_clave_gtin_se_registra_como_vacio(self):
        filtrar_productos_con_codigo_valido([{"name": "Sin clave"}, {"name": "Nulo", "gtin": None}])
        self.assertEqual(Incident.objects.count(), 2)
        for incidencia in Incident.objects.all():
            self.assertEqual(incidencia.gtin, "")
            self.assertIn("vacío", incidencia.reason)

    def test_un_codigo_demasiado_largo_se_recorta_y_no_falla(self):
        filtrar_productos_con_codigo_valido([{"name": "Raro", "gtin": "1" * 100}])
        self.assertEqual(len(Incident.objects.get().gtin), Incident.GTIN_MAX_LENGTH)

    def test_si_todos_son_validos_no_registra_incidencias(self):
        validos = filtrar_productos_con_codigo_valido(self.productos[:1] + self.productos[3:])
        self.assertEqual(len(validos), 2)
        self.assertEqual(Incident.objects.count(), 0)

    def test_acepta_una_lista_vacia_y_cualquier_iterable(self):
        self.assertEqual(filtrar_productos_con_codigo_valido([]), [])
        validos = filtrar_productos_con_codigo_valido(p for p in self.productos[:1])
        self.assertEqual(len(validos), 1)
        self.assertEqual(Incident.objects.count(), 0)
