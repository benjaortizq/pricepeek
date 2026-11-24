from django import forms
from django.utils.functional import lazy

from core.translations import translate_text, translate_text_lazy

from .models import ReviewDeletion


def _star_label(value):
    singular = "estrella" if value == 1 else "estrellas"
    return translate_text(f"{value} {singular}")


star_label = lazy(_star_label, str)


class ReviewForm(forms.Form):
    rating = forms.IntegerField(
        label=translate_text_lazy("Calificación"),
        min_value=1,
        max_value=5,
        widget=forms.RadioSelect(
            choices=[(value, star_label(value)) for value in range(1, 6)]
        ),
    )
    content = forms.CharField(
        label=translate_text_lazy("Comentario"),
        min_length=1,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    photo = forms.ImageField(
        label=translate_text_lazy("Foto (opcional)"),
        required=False,
    )


class ReviewReportForm(forms.Form):
    reason = forms.CharField(
        label=translate_text_lazy("Motivo del reporte"),
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class ModerationForm(forms.Form):
    KEEP = "keep"
    DELETE = "delete"

    action = forms.ChoiceField(
        choices=[
            (KEEP, translate_text_lazy("Mantener")),
            (DELETE, translate_text_lazy("Eliminar")),
        ]
    )
    note = forms.CharField(
        label=translate_text_lazy("Motivo de la decisión"), required=False, max_length=500
    )
    # La política de uso que incumple: obligatoria para eliminar (issue «Eliminación de reseñas»).
    policy = forms.ChoiceField(
        label=translate_text_lazy("Política de uso que incumple"),
        choices=[("", "")] + ReviewDeletion.SELECTABLE,
        required=False,
        error_messages={"invalid_choice": "Elija la política de uso que incumple la reseña."},
    )
    suspend = forms.BooleanField(
        label=translate_text_lazy("Suspender al autor"), required=False
    )

    def clean(self):
        datos = super().clean()
        if datos.get("action") == self.DELETE:
            if not datos.get("policy"):
                self.add_error("policy", "Elija la política de uso que incumple la reseña.")
            if not datos.get("note"):
                self.add_error("note", "Indique el motivo de la eliminación.")
        else:
            datos["suspend"] = False  # solo se sanciona al autor cuando se elimina su reseña
        return datos


class EliminarResenaForm(forms.Form):
    """Eliminar una reseña desde «Todas las reseñas»: siempre con la política y la razón."""

    policy = forms.ChoiceField(
        label=translate_text_lazy("Política de uso que incumple"),
        choices=ReviewDeletion.SELECTABLE,
        error_messages={
            "required": "Elija la política de uso que incumple la reseña.",
            "invalid_choice": "Elija la política de uso que incumple la reseña.",
        },
    )
    note = forms.CharField(
        label=translate_text_lazy("Motivo de la eliminación"),
        max_length=500,
        error_messages={"required": "Indique el motivo de la eliminación."},
    )
    suspend = forms.BooleanField(label=translate_text_lazy("Suspender al autor"), required=False)
