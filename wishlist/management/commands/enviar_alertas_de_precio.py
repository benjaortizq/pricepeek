"""Comando de administración enviar_alertas_de_precio para la aplicación wishlist."""

from django.core.management.base import BaseCommand

from wishlist.alertas import revisar_alertas_de_baja_de_precio


class Command(BaseCommand):
    help = "Revisa las listas de deseos y avisa por correo cuando baja el precio de un producto (RF-24)."

    def handle(self, *args, **options):
        resultado = revisar_alertas_de_baja_de_precio()
        self.stdout.write(
            f"Revisados: {resultado.revisados}. "
            f"Productos con baja: {resultado.productos_con_baja}. "
            f"Correos enviados: {resultado.correos_enviados}. "
            f"Errores: {resultado.errores}."
        )
        if resultado.errores:
            self.stderr.write(
                "Algunos correos no se pudieron enviar; se reintentarán en la próxima revisión."
            )
