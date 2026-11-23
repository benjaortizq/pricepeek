from django import forms
from django.utils.functional import lazy

from core.translations import translate_text, translate_text_lazy


def _star_label(value):
    singular = "estrella" if value == 1 else "estrellas"
    return translate_text(f"{value} {singular}")


star_label = lazy(_star_label, str)


class ReviewForm(forms.Form):
    rating = forms.IntegerField(
        label="Calificación",
        min_value=1,
        max_value=5,
        widget=forms.RadioSelect(
            choices=[(value, star_label(value)) for value in range(1, 6)]
        ),
    )
    content = forms.CharField(
        label="Comentario",
        min_length=1,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    photo = forms.ImageField(
        label="Foto (opcional)",
        required=False,
    )


class ReviewReportForm(forms.Form):
    reason = forms.CharField(
        label="Motivo del reporte",
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
    note = forms.CharField(label="Motivo de la decisión", required=False, max_length=500)
    suspend = forms.BooleanField(label="Suspender al autor", required=False)

    def clean(self):
        datos = super().clean()
        if datos.get("action") == self.DELETE and not datos.get("note"):
            self.add_error("note", "Indique el motivo de la eliminación.")
        if datos.get("action") != self.DELETE:
            datos["suspend"] = False  # solo se sanciona al autor cuando se elimina su reseña
        return datos
