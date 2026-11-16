from django import forms


class ReviewForm(forms.Form):
    rating = forms.IntegerField(
        label="Calificación",
        min_value=1,
        max_value=5,
        widget=forms.RadioSelect(
            choices=[(value, f"{value} estrella{'s' if value != 1 else ''}") for value in range(1, 6)]
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