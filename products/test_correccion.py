"""Pruebas automatizadas de test_correccion para la aplicación products."""

import random
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from .correccion import (
    VIGENCIA_DEL_VOCABULARIO,
    ArbolBK,
    Vocabulario,
    hay_extensiones,
    levenshtein,
    olvidar_vocabulario,
    similitud,
    trigramas,
    vocabulario_del_catalogo,
)
from .models import Brands
from .tests import CatalogoTestCase, fechas


class LevenshteinTests(SimpleTestCase):
    def test_cambios_de_una_letra(self):
        casos = {
            ("sansun", "samsung"): 2,  # la n por m y agregar la g
            ("chokolate", "chocolate"): 1,
            ("leche", "leche"): 0,
            ("", "sal"): 3,
            ("galleta", "galeta"): 1,
        }
        for (a, b), distancia in casos.items():
            with self.subTest(a=a, b=b):
                self.assertEqual(levenshtein(a, b), distancia)
                self.assertEqual(levenshtein(b, a), distancia)


def palabras_al_azar(cantidad, semilla=56):
    azar = random.Random(semilla)
    return [
        "".join(azar.choice("abcdefghij") for _ in range(azar.randint(4, 9)))
        for _ in range(cantidad)
    ]


class ArbolBKTests(SimpleTestCase):
    def test_encuentra_lo_mismo_que_comparar_contra_todas(self):
        palabras = palabras_al_azar(500)
        arbol = ArbolBK(palabras)
        for buscada in palabras_al_azar(30, semilla=7) + palabras[:5]:
            for tolerancia in (0, 1, 2):
                with self.subTest(buscada=buscada, tolerancia=tolerancia):
                    todas = sorted(
                        (levenshtein(buscada, p), p)
                        for p in set(palabras)
                        if levenshtein(buscada, p) <= tolerancia
                    )
                    self.assertEqual(
                        sorted(arbol.buscar(buscada, tolerancia)), todas
                    )

    def test_no_compara_contra_todo_el_vocabulario(self):
        palabras = palabras_al_azar(500)
        comparaciones = 0

        def contar(a, b):
            nonlocal comparaciones
            comparaciones += 1
            return levenshtein(a, b)

        arbol = ArbolBK(palabras, distancia=contar)
        comparaciones = 0
        arbol.buscar("abcdefg", 1)
        self.assertLess(comparaciones, len(arbol) / 2)

    def test_no_repite_palabras(self):
        self.assertEqual(len(ArbolBK(["samsung", "samsung", "xiaomi"])), 2)

    def test_arbol_vacio(self):
        self.assertEqual(ArbolBK().buscar("samsung", 2), [])


class VocabularioTests(SimpleTestCase):
    vocabulario = Vocabulario(
        [
            "Celular Samsung Galaxy A57",
            "Samsung",
            "Chocolate M&M's con maní",
            "Café molido",
            "Sal de mesa",
        ]
    )

    def test_corrige_cada_palabra_mal_escrita(self):
        self.assertEqual(self.vocabulario.corregir("sansun"), "samsung")
        self.assertEqual(
            self.vocabulario.corregir("celular sansun galaxi"),
            "celular samsung galaxy",
        )
        self.assertEqual(self.vocabulario.corregir("chokolate"), "chocolate")
        self.assertEqual(self.vocabulario.corregir("caffe"), "cafe")

    def test_si_no_cambia_nada_no_hay_correccion(self):
        self.assertIsNone(self.vocabulario.corregir("samsung galaxy"))
        self.assertIsNone(self.vocabulario.corregir("Café"))
        self.assertIsNone(
            self.vocabulario.corregir("televisor")
        )  # nada se le parece

    def test_cuantos_cambios_se_aceptan(self):
        self.assertIsNone(
            self.vocabulario.corregir("sol")
        )  # 3 letras: hay demasiadas parecidas
        self.assertEqual(
            self.vocabulario.corregir("mesas"), "mesa"
        )  # 5 letras: 1 cambio
        self.assertIsNone(
            self.vocabulario.corregir("mosas")
        )  # 5 letras: 2 cambios son demasiados
        self.assertIsNone(
            self.vocabulario.corregir("a58")
        )  # con números no se corrige

    def test_entre_dos_igual_de_parecidas_gana_la_que_mas_sale(self):
        vocabulario = Vocabulario(["cosa", "cosa", "cosa", "casa"])
        self.assertEqual(vocabulario.corregir("cusa"), "cosa")

    def test_a_la_misma_distancia_gana_la_que_comparte_mas_trigramas(self):
        # "telo" está a 1 cambio de las dos, pero con "tela" comparte el comienzo ("  t", " te", "tel").
        vocabulario = Vocabulario(["pelo"] * 5 + ["tela"])
        self.assertEqual(vocabulario.corregir("telo"), "tela")


class TrigramasTests(SimpleTestCase):
    def test_como_los_arma_pg_trgm(self):
        self.assertEqual(trigramas("sal"), {"  s", " sa", "sal", "al "})

    def test_similitud(self):
        # sansun y samsung comparten "  s", " sa" y "sun": 3 de 12 trigramas distintos.
        self.assertEqual(similitud("sansun", "samsung"), 3 / 12)
        self.assertEqual(similitud("leche", "leche"), 1)
        self.assertEqual(similitud("leche", "xyz"), 0)


class CorreccionEnLaBusquedaTests(CatalogoTestCase):
    def setUp(self):
        olvidar_vocabulario()
        samsung = Brands.objects.create(
            name="Samsung", slug="samsung", **fechas()
        )
        self.celular = self.producto(
            "Celular Galaxy A57", samsung, self.lacteos
        )
        self.variante_celular = self.variante(
            self.celular, "8806094000017"
        )  # la búsqueda muestra variantes

    def buscar(self, palabra):
        return self.client.get(reverse("buscar_productos"), {"q": palabra})

    def test_en_sqlite_usa_el_arbol_bk(self):
        self.assertFalse(hay_extensiones())

    def test_muestra_los_resultados_de_la_palabra_corregida(self):
        respuesta = self.buscar("sansun")
        self.assertContains(respuesta, "Mostrando resultados para «samsung»")
        self.assertContains(respuesta, "Usted escribió «sansun»")
        self.assertEqual(
            list(respuesta.context["variantes"]), [self.variante_celular]
        )

    def test_si_encuentra_algo_no_corrige(self):
        respuesta = self.buscar("samsung")
        self.assertIsNone(respuesta.context["corregida"])
        self.assertNotContains(respuesta, "Usted escribió")

    def test_si_no_hay_nada_parecido_dice_que_no_encontro(self):
        respuesta = self.buscar("televisor")
        self.assertContains(
            respuesta, "No encontramos productos con «televisor»"
        )
        self.assertNotContains(respuesta, "Mostrando resultados")

    def test_el_vocabulario_se_vuelve_a_armar_cada_dia(self):
        with mock.patch(
            "products.correccion.time.monotonic", return_value=1000.0
        ):
            primero = vocabulario_del_catalogo()
        self.assertNotIn("xiaomi", primero.frecuencia)
        self.producto("Celular Xiaomi Redmi", self.dos_pinos, self.lacteos)
        with mock.patch(
            "products.correccion.time.monotonic",
            return_value=1000.0 + VIGENCIA_DEL_VOCABULARIO - 1,
        ):
            self.assertIs(
                vocabulario_del_catalogo(), primero
            )  # todavía no ha pasado un día
        with mock.patch(
            "products.correccion.time.monotonic",
            return_value=1000.0 + VIGENCIA_DEL_VOCABULARIO + 1,
        ):
            self.assertIn("xiaomi", vocabulario_del_catalogo().frecuencia)
