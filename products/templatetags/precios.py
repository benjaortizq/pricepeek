from django import template

register = template.Library()


@register.filter
def miles(valor):
    """1940 -> "1.940" (separador de miles con punto, como se escriben los colones)."""
    if valor is None:
        return ""
    return f"{int(round(valor)):,}".replace(",", ".")
