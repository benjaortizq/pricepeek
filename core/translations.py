import json
from functools import lru_cache
from pathlib import Path

from django.utils import translation
from django.utils.functional import lazy

CATALOG_PATH = Path(__file__).with_name("translations.json")


@lru_cache(maxsize=1)
def _catalog():
    with CATALOG_PATH.open(encoding="utf-8") as archivo:
        return json.load(archivo)


def translate_text(text, language=None, **values):
    """Traduce una cadena de interfaz y reemplaza sus valores dinámicos.

    El español es el idioma de origen: si no existe una traducción, se conserva
    el texto original. Las traducciones de la interfaz viven en
    ``core/translations.json`` para no depender de herramientas de gettext.
    """
    text = str(text)
    language = (language or translation.get_language() or "es").lower()
    catalog = _catalog()
    language_catalog = catalog.get(language)
    if language_catalog is None:
        language_catalog = catalog.get(language.split("-", 1)[0], {})
    translated = language_catalog.get(text, text)
    if values:
        translated = translated.format(**values)
    return translated


translate_text_lazy = lazy(translate_text, str)
