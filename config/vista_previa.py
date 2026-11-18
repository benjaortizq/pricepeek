"""Vista previa de las pantallas de diseño en frontend/html (solo con DEBUG=True).

Sirve los HTML tal cual, cambiando las rutas relativas ../css y ../js por las de
archivos estáticos de Django y los enlaces entre pantallas por /diseno/<nombre>/.
"""

import re

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static

CARPETA = settings.BASE_DIR / "frontend" / "html"


def lista(request):
    pantallas = sorted(archivo.stem for archivo in CARPETA.glob("*.html"))
    return render(request, "vista_previa.html", {"pantallas": pantallas})


def pantalla(request, nombre):
    archivo = CARPETA / f"{nombre}.html"
    if not re.fullmatch(r"[a-z0-9-]+", nombre) or not archivo.is_file():
        raise Http404("No existe esa pantalla de diseño.")
    html = archivo.read_text(encoding="utf-8")
    html = html.replace('"../css/', f'"{static("css/")}').replace('"../js/', f'"{static("js/")}')
    html = re.sub(r'href="([a-z0-9-]+)\.html"', r'href="/diseno/\1/"', html)
    return HttpResponse(html)
