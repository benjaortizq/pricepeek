"""Pruebas de las sugerencias de coincidencia por marca, modelo, capacidad y color."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from .emparejamiento import PUNTAJE_PARA_SUGERIR, candidatas, comparar, mejor_coincidencia, normalizar, rasgos

MONGE_IPHONE = rasgos("Celular 5G Apple iPhone 17 Negro 8GB RAM 256GB", "iPhone 17", "Negro")


def variante(nombre, marca, gtin="0000000000000"):
    return SimpleNamespace(name=nombre, gtin=gtin, product=SimpleNamespace(brand=SimpleNamespace(name=marca)))


class RasgosTests(SimpleTestCase):
    def test_separa_capacidades_colores_y_numeros_del_modelo(self):
        self.assertEqual(MONGE_IPHONE.capacidades, {"8gb", "256gb"})
        self.assertEqual(MONGE_IPHONE.colores, {"negro"})
        self.assertEqual(MONGE_IPHONE.palabras, {"apple", "iphone", "17"})
        self.assertEqual(MONGE_IPHONE.numeros, {"17"})

    def test_5g_es_la_red_no_gramos_y_los_decimales_se_respetan(self):
        self.assertEqual(rasgos("Celular 5G").capacidades, set())
        self.assertEqual(rasgos("Coca-Cola Original 2,5 Litros").capacidades, {"2.5l"})
        self.assertEqual(rasgos("Refrigeradora 27CP").capacidades, {"27cp"})

    def test_un_codigo_de_modelo_no_se_confunde_con_capacidades(self):
        r = rasgos("Refrigeradora Samsung RS27T5200S9/ED")
        self.assertEqual(r.codigos, {"rs27t5200s9"})
        self.assertEqual(r.capacidades, set())

    def test_normalizar(self):
        self.assertEqual(normalizar("Línea Blanca: Árbol—Ñandú 2.5 L."), "linea blanca arbol nandu 2.5 l")

    def test_el_apostrofo_no_separa(self):
        for marca in ("Kellogg's", "Kellogg´s", "Kellogg’s", "KELLOGGS"):
            with self.subTest(marca=marca):
                self.assertEqual(normalizar(marca), "kelloggs")


class CompararTests(SimpleTestCase):
    def comparar(self, nombre_catalogo, marca_catalogo="Apple", tienda=MONGE_IPHONE, marca_tienda="Apple"):
        return comparar(tienda, rasgos(nombre_catalogo), marca_tienda, marca_catalogo)

    def test_el_mismo_producto(self):
        puntaje, motivo = self.comparar("iPhone 17- 256GB Negro")
        self.assertEqual(puntaje, 100)
        self.assertEqual(motivo, "marca Apple · 17 iphone · 256GB · negro")

    def test_otro_color(self):
        self.assertEqual(self.comparar("iPhone 17- 256GB Blanco"), (0, "otro color"))

    def test_otro_modelo_de_la_misma_linea(self):
        self.assertEqual(self.comparar("iPhone 17 Pro - 256GB Negro"), (0, "otro modelo (pro)"))
        air = rasgos("Celular 5G Apple iPhone 17 Air Negro 8GB RAM 256GB")
        self.assertEqual(self.comparar("iPhone 17- 256GB Negro", tienda=air), (0, "otro modelo (air)"))

    def test_otro_numero_de_modelo(self):
        self.assertEqual(self.comparar("iPhone 16- 256GB Negro"), (0, "no dice 16"))

    def test_un_nombre_del_catalogo_sin_numero_de_modelo_baja_el_puntaje(self):
        # Caso real: en el catálogo está "Xiaomi Redmi Note - 256GB Negro", sin decir cuál Redmi Note.
        monge = rasgos("Celular 5G Xiaomi Redmi Note 17 Negro 6GB RAM 256GB", "", "Negro")
        puntaje, motivo = comparar(monge, rasgos("Xiaomi Redmi Note - 256GB Negro"), "Xiaomi", "Xiaomi")
        self.assertEqual(puntaje, 85)
        self.assertIn("el catálogo no dice 17", motivo)

    def test_combos_y_pro_plus_son_otros_productos(self):
        combo = rasgos("Celular 5G Samsung S26 Ultra Negro 12GB RAM 256GB + Monitor | Combo")
        self.assertEqual(comparar(combo, rasgos("Galaxy S26 Ultra - 256GB Negro"), "Samsung", "Samsung")[0], 0)
        pro_plus = rasgos("Celular 5G Xiaomi Redmi Note 15 Pro+ Negro 12GB RAM 512GB")
        self.assertEqual(comparar(pro_plus, rasgos("Redmi Note 15 Pro - 512GB Negro"), "Xiaomi", "Xiaomi"), (0, "otro modelo (plus)"))

    def test_otra_capacidad(self):
        self.assertEqual(self.comparar("iPhone 17- 512GB Negro"), (0, "otra capacidad"))

    def test_otra_marca(self):
        self.assertEqual(self.comparar("Galaxy 17 Negro", marca_catalogo="Samsung"), (0, "otra marca (Apple / Samsung)"))

    def test_la_marca_sin_importar_apostrofos_ni_espacios(self):
        # Automercado escribe las marcas en mayúscula y sin signos.
        zucaritas = rasgos("CEREAL ENDULZADO ZUCARITAS KELLOGGS caja 490 g")
        puntaje, _ = comparar(zucaritas, rasgos("Zucaritas Kellogg's 490g"), "KELLOGGS", "Kellogg's")
        self.assertGreaterEqual(puntaje, PUNTAJE_PARA_SUGERIR)
        licuadora = rasgos("Licuadora BLACK+DECKER BL1840MS")
        puntaje, _ = comparar(licuadora, rasgos("Licuadora Black + Decker BL1840MS"), "BLACKDECKER", "Black + Decker")
        self.assertEqual(puntaje, 100)

    def test_la_marca_puede_venir_en_el_nombre(self):
        # En el catálogo Gatorade está con la marca PepsiCo, pero el nombre dice Gatorade.
        gatorade = rasgos("Bebida Energética Gatorade Fruit Punch 600ml")
        puntaje, _ = comparar(gatorade, rasgos("Bebida Energética Gatorade Fruit Punch - 600ml"), "Gatorade", "PepsiCo")
        self.assertGreaterEqual(puntaje, PUNTAJE_PARA_SUGERIR)

    def test_mismo_codigo_de_modelo(self):
        monge = rasgos("Refrigeradora Side by Side Inverter Samsung 27CP RS27T5200S9 Dispensador", "RS27T5200S9/ED", "Silver")
        catalogo = rasgos("Refrigeradora Samsung RS27T5200S9 Side by Side 27 pies")
        self.assertEqual(comparar(monge, catalogo, "Samsung", "Samsung"), (100, "mismo modelo RS27T5200S9"))

    def test_productos_distintos_no_llegan_al_puntaje(self):
        puntaje, _ = self.comparar("Pantalla Apple Studio Display 27", tienda=rasgos("Celular Apple iPhone 27"))
        self.assertLess(puntaje, PUNTAJE_PARA_SUGERIR)


class MejorCoincidenciaTests(SimpleTestCase):
    def test_elige_la_variante_con_mejor_puntaje(self):
        opciones = candidatas([
            variante("iPhone 17 Pro - 256GB Azul", "Apple"),
            variante("iPhone 17- 256GB Negro", "Apple", gtin="0195950643411"),
            variante("Leche entera 1L", "Dos Pinos"),
        ])
        candidata, puntaje, _ = mejor_coincidencia(MONGE_IPHONE, "Apple", opciones)
        self.assertEqual((candidata.variante.gtin, puntaje), ("0195950643411", 100))

    def test_sin_coincidencia(self):
        opciones = candidatas([variante("iPhone 17 Pro - 256GB Azul", "Apple"), variante("Leche entera 1L", "Dos Pinos")])
        self.assertIsNone(mejor_coincidencia(MONGE_IPHONE, "Apple", opciones))
