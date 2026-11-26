"""Issue «Historial de precios»: vincular un producto de una tienda deja su
precio en el historial."""

from products.models import PriceHistory

from .productos_tienda import confirmar
from .test_productos_tienda import GTIN_IPHONE, ProductosDeTiendaTestCase


class VinculacionTests(ProductosDeTiendaTestCase):
    def test_vincular_queda_en_el_historial(self):
        producto = self.guardar()
        confirmar(producto)
        [registro] = PriceHistory.objects.filter(gtin_id=GTIN_IPHONE)
        self.assertEqual(
            (registro.price, registro.final_price, registro.source),
            (599900, 479920, PriceHistory.Source.VINCULACION),
        )

        # ₡450.000 es un 25 % de descuento: prices guarda el descuento con
        # dos decimales.
        producto.final_price = 450000
        confirmar(producto)
        ultimo = PriceHistory.objects.filter(gtin_id=GTIN_IPHONE).latest("id")
        self.assertEqual(
            (ultimo.previous_final_price, ultimo.final_price), (479920, 449925)
        )
