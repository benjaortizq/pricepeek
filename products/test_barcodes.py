from django.test import SimpleTestCase

from .barcodes import calcular_digito_verificador, validar_codigo_barras

# Códigos reales con su dígito verificador correcto.
EAN_13 = "4006381333931"
UPC_A = "036000291452"  # empieza con 0: no se puede tratar como número
EAN_8 = "96385074"


class ValidarCodigoBarrasTests(SimpleTestCase):
    def test_acepta_ean13_upca_y_ean8_validos(self):
        casos = {EAN_13: "EAN-13", UPC_A: "UPC-A", EAN_8: "EAN-8"}
        for codigo, formato in casos.items():
            with self.subTest(codigo=codigo):
                resultado = validar_codigo_barras(codigo)
                self.assertTrue(resultado.valido)
                self.assertEqual(resultado.formato, formato)
                self.assertEqual(resultado.motivo, "")

    def test_el_resultado_se_puede_usar_como_booleano(self):
        self.assertTrue(validar_codigo_barras(EAN_13))
        self.assertFalse(validar_codigo_barras("123"))

    def test_ignora_espacios_en_los_extremos(self):
        resultado = validar_codigo_barras(f"  {EAN_13}\n")
        self.assertTrue(resultado.valido)
        self.assertEqual(resultado.codigo, EAN_13)

    def test_rechaza_digito_verificador_incorrecto(self):
        resultado = validar_codigo_barras("4006381333932")
        self.assertFalse(resultado.valido)
        self.assertIn("dígito verificador", resultado.motivo)
        self.assertIn("1", resultado.motivo)  # indica el dígito esperado

    def test_rechaza_longitudes_que_no_son_8_12_ni_13(self):
        for codigo in ["1", "1234567", "123456789", "12345678901", "12345678901234"]:
            with self.subTest(codigo=codigo):
                resultado = validar_codigo_barras(codigo)
                self.assertFalse(resultado.valido)
                self.assertIn("8, 12 o 13", resultado.motivo)

    def test_rechaza_caracteres_que_no_son_digitos(self):
        for codigo in ["40063813339A1", "4006-3813-3393", "4006 3813 3393", "١٢٣٤٥٦٧٨"]:
            with self.subTest(codigo=codigo):
                resultado = validar_codigo_barras(codigo)
                self.assertFalse(resultado.valido)
                self.assertIn("solo puede tener dígitos", resultado.motivo)

    def test_rechaza_codigo_vacio_o_nulo(self):
        for codigo in [None, "", "   "]:
            with self.subTest(codigo=codigo):
                resultado = validar_codigo_barras(codigo)
                self.assertFalse(resultado.valido)
                self.assertIn("vacío", resultado.motivo)

    def test_un_numero_sin_ceros_a_la_izquierda_no_pasa_como_valido(self):
        # Si un CSV convierte "036000291452" en el número 36000291452, se pierde el 0.
        self.assertFalse(validar_codigo_barras(36000291452).valido)

    def test_todos_los_motivos_estan_en_espanol_y_dicen_como_corregir(self):
        for codigo in [None, "ABC", "123", "4006381333932"]:
            with self.subTest(codigo=codigo):
                self.assertTrue(validar_codigo_barras(codigo).motivo.endswith("."))


class DigitoVerificadorTests(SimpleTestCase):
    def test_calcula_el_digito_de_codigos_conocidos(self):
        self.assertEqual(calcular_digito_verificador(EAN_13[:-1]), 1)
        self.assertEqual(calcular_digito_verificador(UPC_A[:-1]), 2)
        self.assertEqual(calcular_digito_verificador(EAN_8[:-1]), 4)

    def test_el_resultado_es_cero_cuando_la_suma_es_multiplo_de_diez(self):
        # 1234567 suma 60, así que su dígito verificador es 0 (EAN-8: 12345670).
        self.assertEqual(calcular_digito_verificador("1234567"), 0)
        self.assertTrue(validar_codigo_barras("12345670").valido)
