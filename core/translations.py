"""Lógica de translations de la aplicación core."""

import json
import re
from functools import lru_cache
from pathlib import Path

from django.utils import translation
from django.utils.functional import lazy

CATALOG_PATH = Path(__file__).with_name("translations.json")
_PLACEHOLDER_PATTERN = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")


@lru_cache(maxsize=1)
def _catalog():
    with CATALOG_PATH.open(encoding="utf-8") as archivo:
        return json.load(archivo)


@lru_cache(maxsize=None)
def _dynamic_templates(language):
    """Compila las traducciones con variables para matching de mensajes completos."""
    catalog = _catalog()
    language_catalog = catalog.get(language, {})
    templates = []
    for source, translated in language_catalog.items():
        fields = list(_PLACEHOLDER_PATTERN.finditer(source))
        if not fields:
            continue
        names = [field.group(1) for field in fields]
        if len(names) != len(set(names)):
            continue
        parts = []
        position = 0
        for field in fields:
            parts.append(re.escape(source[position : field.start()]))
            parts.append(f"(?P<{field.group(1)}>.*)")
            position = field.end()
        parts.append(re.escape(source[position:]))
        templates.append(
            (len(source), re.compile("^" + "".join(parts) + "$"), translated)
        )
    return tuple(
        sorted(templates, key=lambda template: template[0], reverse=True)
    )


def _translate_dynamic(text, language):
    for _, pattern, translated in _dynamic_templates(language):
        match = pattern.fullmatch(text)
        if not match:
            continue
        try:
            return translated.format(**match.groupdict())
        except (KeyError, ValueError):
            continue
    return None


def translate_text(text, language=None, **values):
    """Traduce una cadena de interfaz y reemplaza sus valores dinámicos.

    También reconoce mensajes dinámicos cuyos valores ya fueron interpolados,
    para que puedan traducirse al mostrarse y no solo al crearse. El español es
    el idioma de origen: si no existe una traducción, se conserva el texto
    original. Las traducciones viven en ``core/translations.json``.
    """
    text = str(text)
    language = (language or translation.get_language() or "es").lower()
    catalog = _catalog()
    language_catalog = catalog.get(language)
    catalog_language = language
    if language_catalog is None:
        catalog_language = language.split("-", 1)[0]
        language_catalog = catalog.get(catalog_language, {})
    translated = language_catalog.get(text)
    if translated is None:
        translated = _translate_dynamic(text, catalog_language)
    if translated is None:
        translated = text
    if values:
        translated = translated.format(**values)
    return translated


translate_text_lazy = lazy(translate_text, str)
