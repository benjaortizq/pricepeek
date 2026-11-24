from django.shortcuts import redirect
from django.urls import reverse

from .models import PrivacyConsent, User
from .privacy import PRIVACY_POLICY_VERSION


class PrivacyConsentMiddleware:
    """Requires clients to accept the current privacy notice before using account features."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_accept_current_policy(request):
            return redirect("consentimiento_privacidad")
        return self.get_response(request)

    @staticmethod
    def _must_accept_current_policy(request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or user.role != User.Role.CLIENT:
            return False

        path = request.path_info
        if path.startswith(("/static/", "/media/", "/i18n/")):
            return False

        allowed_paths = {
            reverse("privacidad"),
            reverse("consentimiento_privacidad"),
            reverse("logout"),
            reverse("eliminar_cuenta"),
            reverse("descargar_datos_personales"),
            reverse("editar_perfil"),
        }
        if path in allowed_paths:
            return False

        return not PrivacyConsent.objects.filter(
            user=user,
            policy_version=PRIVACY_POLICY_VERSION,
            revoked_at__isnull=True,
        ).exists()
