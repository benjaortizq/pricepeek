from django import template
from django.utils import translation

from core.translations import translate_text

register = template.Library()


@register.simple_tag
def t(text, **values):
    """Traduce una cadena de la interfaz al idioma activo."""
    return translate_text(text, **values)


@register.simple_tag
def idioma_actual():
    """Devuelve el código del idioma activo (por ejemplo, «es» o «en»)."""
    language = (translation.get_language() or "es").lower().split("-", 1)[0]
    return language if language in {"es", "en"} else "es"
