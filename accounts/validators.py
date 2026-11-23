from django.core.exceptions import ValidationError


class LetraYNumeroValidator:
    """RNF-07: la contraseña debe incluir al menos una letra y un número."""

    def validate(self, password, user=None):
        if not any(c.isalpha() for c in password):
            raise ValidationError(
                "La contraseña debe incluir al menos una letra.",
                code="password_sin_letra",
            )
        if not any(c.isdigit() for c in password):
            raise ValidationError(
                "La contraseña debe incluir al menos un número.",
                code="password_sin_numero",
            )

    def get_help_text(self):
        return "Su contraseña debe incluir al menos una letra y un número."
