"""Extensiones de Postgres para el «¿quiso decir…?» de la búsqueda (ver products/correccion.py).

- fuzzystrmatch: levenshtein(), cuántos cambios de una letra hay entre dos palabras.
- pg_trgm: similarity(), qué tanto se parecen dos palabras por sus pedazos de 3 letras.

Solo se activan (CREATE EXTENSION IF NOT EXISTS): no cambian ninguna tabla. En SQLite (las
pruebas) Django no hace nada.
"""

from django.contrib.postgres.operations import (
    CreateExtension,
    TrigramExtension,
)
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("products", "0001_initial")]

    operations = [
        TrigramExtension(),
        CreateExtension("fuzzystrmatch"),
    ]
