"""Pruebas de la bitácora de auditoría (issue «Bitácora administrativa»).

Cada acción de administrador se prueba con los datos de las pruebas de su pantalla.
"""

from datetime import timedelta

from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import test_comercios, test_suspension
from accounts.models import AccountsUser, PrivacyConsent, User
from accounts.privacy import PRIVACY_POLICY_VERSION
from ingestion import test_ejecucion_manual, test_resolucion
from ingestion.models import ManualRun
from products import test_edicion
from products.models import Stores
from reviews import test_reportes, test_todas_las_resenas
from reviews.models import ReviewDeletion

from .models import RETENCION, AuditLog, RegistroProtegido
from .registro import Accion, registrar

CLAVE = "Clave2026segura"


class RevisaLaBitacora:
    """assertRegistro: la acción quedó anotada con el usuario, el elemento, los detalles y la hora."""

    def assertRegistro(
        self, accion, elemento_id, elemento, detalles=None, comercio=None
    ):
        registro = AuditLog.objects.get(action=accion)
        self.assertEqual(registro.user, self.admin)
        self.assertEqual(registro.tipo_de_elemento, accion.split(".")[0])
        self.assertEqual(registro.elemento_id, elemento_id)
        self.assertEqual(registro.target_name, elemento)
        self.assertEqual(registro.store, comercio)
        self.assertLess(
            timezone.now() - registro.created_at, timedelta(minutes=1)
        )
        for etiqueta, valor in (detalles or {}).items():
            self.assertEqual(registro.details[etiqueta], valor)
        return registro


class ClientesTests(RevisaLaBitacora, test_suspension.SuspensionBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def suspender(self, motivo="Reseñas ofensivas reiteradas."):
        return self.client.post(
            reverse("suspender_cliente", args=[self.cliente.pk]),
            {"motivo": motivo},
        )

    def test_suspender_una_cuenta(self):
        self.suspender()
        self.assertRegistro(
            Accion.CLIENT_SUSPEND,
            self.cliente.pk,
            "infractor@example.com",
            {"Motivo": "Reseñas ofensivas reiteradas."},
        )

    def test_reactivar_una_cuenta(self):
        User.objects.suspender_cliente(self.cliente.pk, self.admin, "Spam.")
        self.client.post(reverse("reactivar_cliente", args=[self.cliente.pk]))
        self.assertRegistro(
            Accion.CLIENT_REACTIVATE, self.cliente.pk, "infractor@example.com"
        )

    def test_si_no_cambia_nada_no_se_registra(self):
        self.suspender(motivo="")  # el motivo es obligatorio
        self.client.post(reverse("reactivar_cliente", args=[self.cliente.pk]))
        self.assertFalse(AuditLog.objects.exists())
        self.suspender()
        self.suspender()  # ya estaba suspendida
        self.assertEqual(AuditLog.objects.count(), 1)


class ComerciosTests(RevisaLaBitacora, test_comercios.ComerciosTestCase):
    def detalle(self):
        return reverse("detalle_comercio", args=[self.walmart.pk])

    def test_registrar_un_comercio_anota_el_comercio_y_su_cuenta(self):
        self.registrar()
        tienda = Stores.objects.get(name="Super La Esquina")
        cuenta = AccountsUser.objects.get(from_store_id=tienda.pk)
        self.assertRegistro(
            Accion.STORE_REGISTER,
            tienda.pk,
            "Super La Esquina",
            {
                "Obtención de datos": "Datos provistos por el comercio",
                "Activo": True,
            },
            comercio=tienda,
        )
        self.assertRegistro(
            Accion.ACCOUNT_CREATE,
            cuenta.pk,
            cuenta.email,
            {"Comercio": "Super La Esquina"},
            comercio=tienda,
        )

    def test_editar_sus_datos(self):
        self.client.post(
            self.detalle(),
            {
                "name": "Walmart Costa Rica",
                "description": "Hipermercado.",
                "data_source": test_comercios.PROVISTOS,
            },
        )
        self.assertRegistro(
            Accion.STORE_EDIT,
            self.walmart.pk,
            "Walmart Costa Rica",
            {
                "Nombre": "Walmart Costa Rica",
                "Descripción": "Hipermercado.",
                "Obtención de datos": "Datos provistos por el comercio",
            },
            comercio=self.walmart,
        )

    def test_guardar_sin_cambios_no_se_registra(self):
        self.client.post(
            self.detalle(),
            {
                "name": "Walmart",
                "description": "",
                "data_source": test_comercios.SCRAPING,
            },
        )
        self.assertFalse(AuditLog.objects.exists())

    def test_desactivar_y_activar(self):
        url = reverse("estado_comercio", args=[self.walmart.pk])
        self.client.post(url, {"activo": "0"})
        self.assertRegistro(
            Accion.STORE_DEACTIVATE,
            self.walmart.pk,
            "Walmart",
            comercio=self.walmart,
        )
        self.client.post(url, {"activo": "1"})
        self.assertRegistro(
            Accion.STORE_ACTIVATE,
            self.walmart.pk,
            "Walmart",
            comercio=self.walmart,
        )
        self.client.post(url, {"activo": "1"})  # ya estaba activo
        self.assertEqual(AuditLog.objects.count(), 2)

    def test_crear_una_cuenta_de_empresa(self):
        self.client.post(
            reverse("crear_cuenta_comercio", args=[self.walmart.pk]),
            {"email": "precios@walmart.test"},
        )
        cuenta = User.objects.get(email="precios@walmart.test")
        self.assertRegistro(
            Accion.ACCOUNT_CREATE,
            cuenta.pk,
            "precios@walmart.test",
            {"Comercio": "Walmart"},
            comercio=self.walmart,
        )

    def test_reenviar_el_acceso(self):
        self.client.post(
            reverse(
                "reenviar_acceso_comercio",
                args=[self.walmart.pk, self.empresa.pk],
            )
        )
        self.assertRegistro(
            Accion.ACCOUNT_SEND_ACCESS,
            self.empresa.pk,
            "empresa@walmart.test",
            {"Comercio": "Walmart", "Correo enviado": True},
            comercio=self.walmart,
        )

    def test_no_se_borra_la_cuenta_de_un_administrador_con_acciones(self):
        self.client.post(
            reverse("estado_comercio", args=[self.walmart.pk]), {"activo": "0"}
        )
        with self.assertRaises(ProtectedError):
            self.admin.delete()
        self.assertEqual(AuditLog.objects.get().user, self.admin)


class ProductosTests(RevisaLaBitacora, test_edicion.EdicionBase):
    def test_editar_un_producto(self):
        self.guardar(name="Leche descremada 1L", brand="Marca Nueva")
        registro = self.assertRegistro(
            Accion.PRODUCT_EDIT,
            self.leche.pk,
            "Leche descremada 1L",
            {"Marca nueva": "Marca Nueva"},
        )
        self.assertIn("el nombre", registro.details["Cambios"])
        self.assertIn("la marca", registro.details["Cambios"])

    def test_guardar_sin_cambios_no_se_registra(self):
        self.guardar()
        self.assertFalse(AuditLog.objects.exists())


class ResenasReportadasTests(RevisaLaBitacora, test_reportes.ReportesBase):
    def setUp(self):
        self.crear_reporte()
        self.client.force_login(self.admin)
        self.url = reverse(
            "moderar_resena", kwargs={"review_id": self.resena.pk}
        )

    def test_mantener_la_resena(self):
        self.client.post(
            self.url, {"action": "keep", "note": "No incumple las políticas."}
        )
        self.assertRegistro(
            Accion.REVIEW_KEEP,
            self.resena.pk,
            "Producto — autor@example.com",
            {"Nota": "No incumple las políticas.", "Reportes resueltos": 1},
        )

    def test_eliminarla_y_suspender_al_autor_anota_las_dos_acciones(self):
        self.client.post(
            self.url,
            {
                "action": "delete",
                "note": "Lenguaje ofensivo.",
                "policy": ReviewDeletion.Policy.DISRESPECTFUL,
                "suspend": "on",
            },
        )
        self.assertRegistro(
            Accion.REVIEW_DELETE,
            self.resena.pk,
            "Producto — autor@example.com",
            {
                "Razón": "Lenguaje ofensivo.",
                "Reportes resueltos": 1,
                "Autor suspendido": True,
            },
        )
        self.assertRegistro(
            Accion.CLIENT_SUSPEND,
            self.autor.pk,
            "autor@example.com",
            {"Motivo": "Lenguaje ofensivo."},
        )


class TodasLasResenasTests(
    RevisaLaBitacora, test_todas_las_resenas.TodasLasResenasBase
):
    def test_eliminar_por_incumplimiento(self):
        self.eliminar()
        registro = self.assertRegistro(
            Accion.REVIEW_DELETE,
            self.resena.pk,
            "Producto — autor@example.com",
            {"Razón": "Insulta a otros usuarios.", "Autor suspendido": False},
        )
        self.assertEqual(
            registro.details["Política incumplida"],
            ReviewDeletion.objects.get().get_policy_display(),
        )
        self.assertFalse(
            AuditLog.objects.filter(action=Accion.CLIENT_SUSPEND).exists()
        )


class IncidenciasTests(RevisaLaBitacora, test_resolucion.ResolucionTestCase):
    def setUp(self):
        super().setUp()
        self.incidencia = self.incidencia_de(
            test_resolucion.respuesta_vtex(lista=5000, final=4000)
        )

    def test_resolver_una_incidencia(self):
        self.resolver(self.incidencia, "descartar")
        registro = self.assertRegistro(
            Accion.INCIDENT_RESOLVE,
            self.incidencia.pk,
            f"{self.incidencia.product_name} — {self.incidencia.store_name}",
            {
                "Tipo": "Cambio de precio sospechoso",
                "Acción elegida": "Descartar",
            },
        )
        self.assertIn(
            "Se mantuvo el precio guardado", registro.details["Resultado"]
        )

    def test_una_accion_que_no_aplica_no_se_registra(self):
        self.resolver(self.incidencia, "aceptar_codigo")
        self.assertFalse(AuditLog.objects.exists())


class ObtencionDeDatosTests(
    RevisaLaBitacora, test_ejecucion_manual.EjecucionManualTestCase
):
    def test_pedir_una_obtencion_de_datos(self):
        self.pedir_en_el_servidor()
        ejecucion = ManualRun.objects.get()
        self.assertRegistro(
            Accion.DATA_RUN_REQUEST,
            ejecucion.pk,
            ejecucion.store_name,
            {
                "Dónde": "Servidor de PricePeek",
                "Minutos como máximo": 20,
                "Todos los precios": True,
                "Modo de prueba": False,
            },
            comercio=self.walmart,
        )


class ConservacionTests(TestCase):
    """La bitácora no se modifica y se conserva al menos 12 meses."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )

    def anotar(self, **cambios):
        registro = registrar(
            self.admin, Accion.CLIENT_REACTIVATE, 7, "ana@example.com"
        )
        if cambios:
            AuditLog._base_manager.filter(pk=registro.pk).update(**cambios)
            registro = AuditLog.objects.get(pk=registro.pk)
        return registro

    def test_cada_accion_dice_que_tipo_de_elemento_afecta(self):
        for accion in Accion:
            with self.subTest(accion=accion):
                self.assertIn(accion.split(".")[0], AuditLog.Target.values)

    def test_usa_la_tabla_audit_admin_changes_de_supabase(self):
        registro = registrar(
            self.admin,
            Accion.CLIENT_SUSPEND,
            7,
            "ana@example.com",
            {"Motivo": "Spam."},
        )
        self.assertEqual(AuditLog._meta.db_table, "audit_admin_changes")
        columnas = {
            campo.column: getattr(registro, campo.attname)
            for campo in AuditLog._meta.concrete_fields
        }
        self.assertEqual(
            set(columnas),
            {
                "id",
                "id_requested_by",
                "id_store",
                "action",
                "element_affected",
                "details",
                "created_at",
            },
        )
        self.assertEqual(columnas["id_requested_by"], self.admin.pk)
        self.assertIsNone(columnas["id_store"])
        self.assertEqual(columnas["action"], "cliente.suspender")
        self.assertEqual(columnas["element_affected"], "ana@example.com")
        self.assertEqual(columnas["details"], {"ID": 7, "Motivo": "Spam."})

    def test_los_registros_no_se_modifican(self):
        registro = self.anotar()
        registro.target_name = "otra@example.com"
        with self.assertRaises(RegistroProtegido):
            registro.save()
        with self.assertRaises(RegistroProtegido):
            AuditLog.objects.update(target_name="otra@example.com")
        self.assertEqual(AuditLog.objects.get().target_name, "ana@example.com")

    def test_no_se_borran_antes_de_12_meses(self):
        registro = self.anotar(
            created_at=timezone.now() - RETENCION + timedelta(days=1)
        )
        with self.assertRaises(RegistroProtegido):
            registro.delete()
        with self.assertRaises(RegistroProtegido):
            AuditLog.objects.all().delete()
        self.assertTrue(AuditLog.objects.exists())

    def test_despues_de_12_meses_ya_se_pueden_borrar(self):
        self.assertGreaterEqual(RETENCION, timedelta(days=365))
        self.anotar(created_at=timezone.now() - RETENCION - timedelta(days=1))
        AuditLog.objects.all().delete()
        self.assertFalse(AuditLog.objects.exists())


class PantallaDeLaBitacoraTests(TestCase):
    url = reverse("bitacora")

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="admin@example.com", password=CLAVE, role="admin"
        )
        cls.otro_admin = User.objects.create_user(
            email="moderador@example.com", password=CLAVE, role="admin"
        )
        registrar(
            cls.admin,
            Accion.CLIENT_SUSPEND,
            7,
            "ana@example.com",
            {"Motivo": "Spam en las reseñas."},
        )
        registrar(cls.otro_admin, Accion.STORE_DEACTIVATE, 3, "Walmart")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_muestra_usuario_accion_elemento_detalles_y_fecha(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        registro = AuditLog.objects.get(action=Accion.CLIENT_SUSPEND)
        hora = timezone.localtime(registro.created_at)
        for texto in (
            "admin@example.com",
            "Suspendió la cuenta",
            "Cuenta de cliente",
            "ana@example.com",
            "Motivo:",
            "Spam en las reseñas.",
            f"{hora:%d/%m/%Y}",
            f"{hora:%H:%M:%S}",
            "moderador@example.com",
            "Desactivó el comercio",
        ):
            self.assertContains(respuesta, texto)
        self.assertContains(
            respuesta, f'href="{reverse("detalle_cliente", args=[7])}"'
        )

    def test_la_mas_reciente_primero(self):
        registros = list(self.client.get(self.url).context["pagina"])
        self.assertEqual(
            [registro.action for registro in registros],
            [Accion.STORE_DEACTIVATE, Accion.CLIENT_SUSPEND],
        )

    def test_filtra_por_tipo_de_elemento_y_busca(self):
        respuesta = self.client.get(self.url, {"tipo": "comercio"})
        self.assertEqual(
            [r.target_name for r in respuesta.context["pagina"]], ["Walmart"]
        )
        respuesta = self.client.get(self.url, {"q": "moderador"})
        self.assertEqual(
            [r.target_name for r in respuesta.context["pagina"]], ["Walmart"]
        )

    def test_esta_en_el_menu_del_panel(self):
        # En la barra lateral y, en pantallas angostas, en la barra superior.
        respuesta = self.client.get(reverse("clientes"))
        self.assertContains(respuesta, f'href="{self.url}"', count=2)

    def test_solo_la_ven_los_administradores(self):
        for rol in (User.Role.CLIENT, User.Role.ENTERPRISE):
            with self.subTest(rol=rol):
                usuario = User.objects.create_user(
                    email=f"{rol}@example.com", password=CLAVE, role=rol
                )
                # Sin aceptar la política de privacidad, al cliente lo desvía el middleware.
                PrivacyConsent.objects.create(
                    user=usuario, policy_version=PRIVACY_POLICY_VERSION
                )
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.url),
            f"{reverse('login')}?next={self.url}",
            fetch_redirect_response=False,
        )

    def test_se_traduce_al_ingles(self):
        self.client.cookies["django_language"] = "en"
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Audit log")
        self.assertContains(respuesta, "Suspended the account")
        self.assertContains(respuesta, "Reason:")
