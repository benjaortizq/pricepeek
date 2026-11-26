"""Issue «Gestión de comercios asociados»: los precios de un comercio desactivado no se muestran."""

from types import SimpleNamespace

from django.urls import reverse

from accounts.models import AccountsUser, User
from enterprise.selectors import catalogo_base
from wishlist.alertas import mejores_precios
from wishlist.totales import totales_por_tienda

from .models import PartnerStore, Prices, Stores
from .ofertas import mejores_ofertas
from .precios import con_precio_minimo, precios_por_gtin
from .tests import CatalogoTestCase, fechas


class ComercioDesactivadoTests(CatalogoTestCase):
    """La leche cuesta menos en Walmart, pero Walmart está desactivado; Gollo sigue activo."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.walmart = Stores.objects.create(name="Walmart\n", **fechas())
        cls.gollo = Stores.objects.create(name="Gollo", **fechas())
        cls.barato = cls.precio(cls.variante_leche, cls.walmart, 1000)
        cls.caro = cls.precio(cls.variante_leche, cls.gollo, 1200)
        cls.perfil = PartnerStore.objects.create(
            store=cls.walmart,
            data_source=PartnerStore.DataSource.SCRAPING,
            is_active=False,
        )

    def item(self):
        return SimpleNamespace(
            variant=self.variante_leche,
            currency_id=self.caro.currency_id,
            currency=self.caro.currency,
        )

    def test_solo_se_ven_los_precios_de_los_comercios_activos(self):
        self.assertEqual(list(Prices.visibles.all()), [self.caro])
        self.assertEqual(
            Prices.objects.count(), 2
        )  # siguen guardados: solo no se muestran

    def test_el_detalle_del_producto_no_los_muestra(self):
        respuesta = self.client.get(
            reverse("detalle_producto", args=[self.leche.pk])
        )
        self.assertContains(respuesta, "Gollo")
        self.assertNotContains(respuesta, "Walmart")

    def test_la_comparacion_y_la_busqueda_usan_solo_los_activos(self):
        self.assertEqual(
            [
                precio.id_store_id
                for precio in precios_por_gtin(self.variante_leche.gtin)
            ],
            [self.gollo.pk],
        )
        variante = con_precio_minimo([self.variante_leche])[0]
        self.assertEqual(variante.precio_minimo.id_store_id, self.gollo.pk)

    def test_no_cuenta_para_las_ofertas_del_inicio(self):
        # Con un solo comercio activo ya no hay diferencia de precio que mostrar.
        self.assertEqual(mejores_ofertas(), [])

    def test_la_lista_de_deseos_no_lo_usa(self):
        self.assertEqual(
            mejores_precios([self.item()]),
            {
                (self.variante_leche.gtin, self.caro.currency_id): (
                    1200,
                    "Gollo",
                )
            },
        )
        [comparacion] = totales_por_tienda([self.item()])
        self.assertNotIn("Walmart", str(comparacion))

    def test_no_cuenta_como_competidor_en_el_portal_de_empresas(self):
        precio = catalogo_base(self.gollo).get()
        self.assertIsNone(precio.competitor_price)

    def test_al_reactivarlo_sus_precios_vuelven(self):
        PartnerStore.objects.filter(pk=self.perfil.pk).update(is_active=True)
        self.assertContains(
            self.client.get(reverse("detalle_producto", args=[self.leche.pk])),
            "Walmart",
        )
        self.assertEqual(
            con_precio_minimo([self.variante_leche])[
                0
            ].precio_minimo.id_store_id,
            self.walmart.pk,
        )

    def test_un_comercio_sin_configurar_sigue_activo(self):
        self.perfil.delete()
        self.assertEqual(Prices.visibles.count(), 2)

    def test_el_portal_le_avisa_a_la_empresa_y_le_sigue_mostrando_sus_precios(
        self,
    ):
        empresa = User.objects.create_user(
            email="empresa@walmart.test",
            password="Clave2026segura",
            role="enterprise",
        )
        AccountsUser.objects.filter(pk=empresa.pk).update(
            from_store_id=self.walmart.pk
        )
        self.client.force_login(empresa)
        respuesta = self.client.get(reverse("enterprise:catalogo"))
        self.assertContains(
            respuesta, "Su comercio está desactivado en PricePeek"
        )
        self.assertContains(respuesta, "Leche entera 1L")
        # Gollo (activo) no ve el aviso.
        otra = User.objects.create_user(
            email="empresa@gollo.test",
            password="Clave2026segura",
            role="enterprise",
        )
        AccountsUser.objects.filter(pk=otra.pk).update(
            from_store_id=self.gollo.pk
        )
        self.client.force_login(otra)
        self.assertNotContains(
            self.client.get(reverse("enterprise:catalogo")),
            "Su comercio está desactivado",
        )
