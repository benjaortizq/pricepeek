"""Generación del reporte PDF de competitividad para empresas."""

from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.conf import settings
from django.utils import timezone, translation
from django.utils.formats import date_format
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.translations import translate_text

from .selectors import (
    COMPETITIVIDAD_ROJO,
    catalogo_base,
    estadisticas_catalogo,
    limite_precio_desactualizado,
    _anotar_competitividad,
)

COLOR_TEXTO = colors.HexColor("#272727")
COLOR_SUAVE = colors.HexColor("#666666")
COLOR_BORDE = colors.HexColor("#E5DFD4")
COLOR_ENCABEZADO = colors.HexColor("#F2F0ED")
COLOR_ACENTO = colors.HexColor("#F5B82E")
COLOR_FONDO_NOTA = colors.HexColor("#F7F4EE")
COLOR_VERDE = colors.HexColor("#006E2D")
COLOR_AMARILLO = colors.HexColor("#7B5800")
COLOR_ROJO = colors.HexColor("#BA1A1A")
COLOR_NEUTRO = colors.HexColor("#5F5E5E")

MARGEN_HORIZONTAL = 14 * mm
MARGEN_SUPERIOR = 31 * mm
MARGEN_INFERIOR = 19 * mm
ANCHO_UTIL = A4[0] - (2 * MARGEN_HORIZONTAL)


def _configurar_fuentes():
    """Registra las fuentes Unicode incluidas dentro del propio ReportLab.

    Bitstream Vera forma parte de la distribución de ReportLab, por lo que no
    depende de fuentes instaladas en el sistema. La variante regular se usa
    para el texto y la negrita para los títulos.
    """
    directorio = Path(reportlab.__file__).resolve().parent / "fonts"
    archivos = {
        "PricePeekSans": directorio / "Vera.ttf",
        "PricePeekSans-Bold": directorio / "VeraBd.ttf",
    }
    if all(ruta.is_file() for ruta in archivos.values()):
        registrados = set(pdfmetrics.getRegisteredFontNames())
        for nombre, ruta in archivos.items():
            if nombre not in registrados:
                pdfmetrics.registerFont(TTFont(nombre, str(ruta)))
        pdfmetrics.registerFontFamily(
            "PricePeekSans",
            normal="PricePeekSans",
            bold="PricePeekSans-Bold",
            italic="PricePeekSans",
            boldItalic="PricePeekSans-Bold",
        )
        return "PricePeekSans", "PricePeekSans-Bold"

    # Helvetica forma parte de los tipos base de PDF y también cubre el
    # español latino si una instalación inusual no incluye Vera.
    return "Helvetica", "Helvetica-Bold"


FUENTE_REGULAR, FUENTE_GRUESA = _configurar_fuentes()


def _traducir(texto, **valores):
    """Traduce una cadena del PDF usando el catálogo general del sitio."""
    return translate_text(texto, **valores)


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "ReporteCompetitividadTitulo",
            parent=base["Title"],
            fontName=FUENTE_GRUESA,
            fontSize=18,
            leading=22,
            textColor=COLOR_TEXTO,
            alignment=TA_LEFT,
            spaceAfter=7 * mm,
        ),
        "seccion": ParagraphStyle(
            "ReporteCompetitividadSeccion",
            parent=base["Heading2"],
            fontName=FUENTE_GRUESA,
            fontSize=13,
            leading=16,
            textColor=COLOR_TEXTO,
            alignment=TA_LEFT,
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "encabezado_tabla": ParagraphStyle(
            "ReporteCompetitividadEncabezado",
            parent=base["BodyText"],
            fontName=FUENTE_GRUESA,
            fontSize=7.2,
            leading=9,
            textColor=COLOR_TEXTO,
            alignment=TA_LEFT,
        ),
        "celda": ParagraphStyle(
            "ReporteCompetitividadCelda",
            parent=base["BodyText"],
            fontName=FUENTE_REGULAR,
            fontSize=8.1,
            leading=10.2,
            textColor=COLOR_TEXTO,
            alignment=TA_LEFT,
        ),
        "resumen_rotulo": ParagraphStyle(
            "ReporteCompetitividadResumenRotulo",
            parent=base["BodyText"],
            fontName=FUENTE_GRUESA,
            fontSize=7.1,
            leading=8.5,
            textColor=COLOR_SUAVE,
            alignment=TA_CENTER,
        ),
        "resumen_valor": ParagraphStyle(
            "ReporteCompetitividadResumenValor",
            parent=base["BodyText"],
            fontName=FUENTE_GRUESA,
            fontSize=12,
            leading=14,
            textColor=COLOR_TEXTO,
            alignment=TA_CENTER,
        ),
        "nota": ParagraphStyle(
            "ReporteCompetitividadNota",
            parent=base["BodyText"],
            fontName=FUENTE_REGULAR,
            fontSize=8.2,
            leading=11,
            textColor=COLOR_TEXTO,
            alignment=TA_LEFT,
        ),
        "vacio": ParagraphStyle(
            "ReporteCompetitividadVacio",
            parent=base["BodyText"],
            fontName=FUENTE_REGULAR,
            fontSize=8.5,
            leading=11,
            textColor=COLOR_SUAVE,
            alignment=TA_LEFT,
        ),
    }


def _formatear_cantidad(valor):
    """Formatea un monto con el separador decimal del idioma activo."""
    if valor is None or valor == "":
        return "—"
    try:
        monto = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        return str(valor)
    if not monto.is_finite():
        return str(valor)

    decimales = 0 if monto == monto.to_integral_value() else 2
    texto = f"{monto:,.{decimales}f}"
    if (translation.get_language() or "es").lower().startswith("es"):
        texto = (
            texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        )
    return texto


class _MontoPDF(Flowable):
    """Dibuja un monto y, cuando corresponde, el símbolo de colón."""

    TAMANO = 8.1

    def __init__(self, valor, simbolo=""):
        super().__init__()
        self.texto = _formatear_cantidad(valor)
        self.simbolo = str(simbolo or "").strip()

    def wrap(self, ancho_disponible, alto_disponible):
        self._altura = self.TAMANO + 2
        if self.simbolo == "₡":
            # Vera no incluye el símbolo U+20A1. Se dibuja como una C con
            # diagonal, manteniendo el mismo significado del símbolo CRC.
            self._simbolo_dibujado = "C"
        else:
            self._simbolo_dibujado = self.simbolo
        self._ancho_simbolo = (
            pdfmetrics.stringWidth(
                self._simbolo_dibujado, FUENTE_REGULAR, self.TAMANO
            )
            if self._simbolo_dibujado
            else 0
        )
        self._ancho_texto = pdfmetrics.stringWidth(
            self.texto, FUENTE_REGULAR, self.TAMANO
        )
        return self._ancho_simbolo + self._ancho_texto, self._altura

    def draw(self):
        lienzo = self.canv
        lienzo.saveState()
        lienzo.setFillColor(COLOR_TEXTO)
        lienzo.setFont(FUENTE_REGULAR, self.TAMANO)
        if self._simbolo_dibujado:
            lienzo.drawString(0, 0, self._simbolo_dibujado)
        if self.simbolo == "₡":
            lienzo.setStrokeColor(COLOR_TEXTO)
            lienzo.setLineWidth(0.55)
            lienzo.line(
                self._ancho_simbolo * 0.88,
                self._altura - 2,
                self._ancho_simbolo * 0.12,
                0,
            )
        lienzo.drawString(self._ancho_simbolo, 0, self.texto)
        lienzo.restoreState()


def _tabla_resumen(estadisticas, porcentajes, estilos):
    """Construye el resumen con los seis indicadores del semáforo."""
    etiquetas = [
        _traducir("Productos"),
        _traducir("Disponibles"),
        _traducir("Más baratos"),
        _traducir("Empatados"),
        _traducir("Sobre el mercado"),
        _traducir("Sin referencia"),
    ]
    valores = [
        str(estadisticas["total"]),
        str(estadisticas["activos"]),
        f"{estadisticas['verde']} · {porcentajes['verde']} %",
        f"{estadisticas['amarillo']} · {porcentajes['amarillo']} %",
        f"{estadisticas['rojo']} · {porcentajes['rojo']} %",
        f"{estadisticas['neutro']} · {porcentajes['neutro']} %",
    ]
    colores_valor = [
        COLOR_TEXTO,
        COLOR_TEXTO,
        COLOR_VERDE,
        COLOR_AMARILLO,
        COLOR_ROJO,
        COLOR_NEUTRO,
    ]

    rotulos = [
        Paragraph(escape(etiqueta), estilos["resumen_rotulo"])
        for etiqueta in etiquetas
    ]
    celdas_valor = []
    for valor, color in zip(valores, colores_valor):
        estilo_valor = ParagraphStyle(
            f"ResumenValor{len(celdas_valor)}",
            parent=estilos["resumen_valor"],
            textColor=color,
        )
        celdas_valor.append(Paragraph(escape(valor), estilo_valor))

    tabla = Table(
        [rotulos, celdas_valor],
        colWidths=[ANCHO_UTIL / 6] * 6,
        hAlign="LEFT",
        repeatRows=1,
    )
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_ENCABEZADO),
                ("BOX", (0, 0), (-1, -1), 0.45, COLOR_BORDE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, COLOR_BORDE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabla


def _tabla_sobre_mercado(precios, estilos):
    """Construye la tabla de ofertas por encima del mercado."""
    encabezados = [
        "GTIN",
        _traducir("Producto"),
        _traducir("Precio final"),
        _traducir("Mínimo competidor"),
        _traducir("Estado"),
    ]
    filas = [
        [
            Paragraph(escape(encabezado), estilos["encabezado_tabla"])
            for encabezado in encabezados
        ]
    ]
    for precio in precios:
        filas.append(
            [
                Paragraph(escape(str(precio.gtin_id)), estilos["celda"]),
                Paragraph(
                    escape(str(precio.gtin.product.name)), estilos["celda"]
                ),
                _MontoPDF(precio.final_price, precio.currency.symbol),
                _MontoPDF(precio.competitor_price, precio.currency.symbol),
                Paragraph(
                    f'<font color="#BA1A1A"><b>{escape(_traducir("Revisar"))}</b></font>',
                    estilos["celda"],
                ),
            ]
        )

    tabla = Table(
        filas,
        colWidths=[30 * mm, 62 * mm, 29 * mm, 34 * mm, 27 * mm],
        hAlign="LEFT",
        repeatRows=1,
        splitByRow=1,
    )
    tabla.setStyle(_estilo_tabla_datos())
    return tabla


def _tabla_desactualizados(precios, estilos):
    """Construye la tabla de precios cuyo umbral de vigencia venció."""
    encabezados = [
        "GTIN",
        _traducir("Producto"),
        _traducir("Precio final"),
        _traducir("Última actualización"),
        _traducir("Estado"),
    ]
    filas = [
        [
            Paragraph(escape(encabezado), estilos["encabezado_tabla"])
            for encabezado in encabezados
        ]
    ]
    for precio in precios:
        fecha = (
            date_format(precio.updated_at, "d/m/Y")
            if precio.updated_at is not None
            else "—"
        )
        filas.append(
            [
                Paragraph(escape(str(precio.gtin_id)), estilos["celda"]),
                Paragraph(
                    escape(str(precio.gtin.product.name)), estilos["celda"]
                ),
                _MontoPDF(precio.final_price, precio.currency.symbol),
                Paragraph(escape(fecha), estilos["celda"]),
                Paragraph(
                    f'<font color="#7B5800"><b>{escape(_traducir("Actualizar"))}</b></font>',
                    estilos["celda"],
                ),
            ]
        )

    tabla = Table(
        filas,
        colWidths=[30 * mm, 62 * mm, 29 * mm, 35 * mm, 26 * mm],
        hAlign="LEFT",
        repeatRows=1,
        splitByRow=1,
    )
    tabla.setStyle(_estilo_tabla_datos())
    return tabla


def _estilo_tabla_datos():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_ENCABEZADO),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, COLOR_ACENTO),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_BORDE),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#FAF9F7")],
            ),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]
    )


def _nota_explicativa(estilos):
    contenido = (
        f"<b>{escape(_traducir('Cómo se calcula'))}</b><br/>"
        f"{escape(_traducir('La clasificación compara el precio final de cada oferta (precio base multiplicado por uno menos el descuento) con el precio final disponible más bajo de las otras tiendas. No se realizan conversiones de moneda.'))}"
    )
    tabla = Table(
        [[Paragraph(contenido, estilos["nota"])]],
        colWidths=[ANCHO_UTIL],
        hAlign="LEFT",
    )
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_FONDO_NOTA),
                ("LINEBEFORE", (0, 0), (0, -1), 3, COLOR_ACENTO),
                ("BOX", (0, 0), (-1, -1), 0.25, COLOR_BORDE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return tabla


def datos_reporte(store):
    """Reúne estadísticas y productos que requieren revisión."""
    ahora = timezone.now()
    queryset = _anotar_competitividad(catalogo_base(store))
    limite = limite_precio_desactualizado(ahora)
    estadisticas = estadisticas_catalogo(store, ahora=ahora)
    total = estadisticas["total"] or 1

    def porcentaje(cantidad):
        return round((cantidad / total) * 100, 1)

    return {
        "store": store,
        "generated_at": ahora,
        "generated_date": date_format(ahora, "d/m/Y H:i"),
        "language": (translation.get_language() or "es").split("-", 1)[0],
        "stale_price_days": settings.STALE_PRICE_DAYS,
        "stats": estadisticas,
        "percentages": {
            "verde": porcentaje(estadisticas["verde"]),
            "amarillo": porcentaje(estadisticas["amarillo"]),
            "rojo": porcentaje(estadisticas["rojo"]),
            "neutro": porcentaje(estadisticas["neutro"]),
        },
        "above_market": queryset.filter(
            competitiveness=COMPETITIVIDAD_ROJO
        ).order_by("gtin__product__name", "gtin_id"),
        "stale": queryset.filter(updated_at__lte=limite).order_by(
            "updated_at", "gtin__product__name", "gtin_id"
        ),
    }


def construir_historia(datos):
    """Construye el contenido Platypus del reporte con datos ya filtrados."""
    estilos = _estilos()
    historia = [
        Paragraph(
            escape(_traducir("Reporte de competitividad")), estilos["titulo"]
        ),
        Paragraph(escape(_traducir("Resumen PDF")), estilos["seccion"]),
        _tabla_resumen(datos["stats"], datos["percentages"], estilos),
        Spacer(1, 4 * mm),
        _nota_explicativa(estilos),
        Paragraph(
            escape(_traducir("Productos por encima del mercado")),
            estilos["seccion"],
        ),
    ]

    if datos["above_market"].exists():
        historia.append(_tabla_sobre_mercado(datos["above_market"], estilos))
    else:
        historia.append(
            Paragraph(
                escape(_traducir("No hay productos por encima del mercado.")),
                estilos["vacio"],
            )
        )

    historia.append(
        Paragraph(
            escape(
                _traducir(
                    "Productos sin cambios desde hace {dias} días o más",
                    dias=datos["stale_price_days"],
                )
            ),
            estilos["seccion"],
        )
    )
    if datos["stale"].exists():
        historia.append(_tabla_desactualizados(datos["stale"], estilos))
    else:
        historia.append(
            Paragraph(
                escape(
                    _traducir(
                        "No hay productos sin cambios durante este período."
                    )
                ),
                estilos["vacio"],
            )
        )
    return historia


class _CanvasNumerado(canvas.Canvas):
    """Canvas que conserva las páginas para mostrar ``Página X de Y``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estados_pagina = []

    def showPage(self):
        self._estados_pagina.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_paginas = len(self._estados_pagina)
        for estado in self._estados_pagina:
            self.__dict__.update(estado)
            self._dibujar_paginacion(total_paginas)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _dibujar_paginacion(self, total_paginas):
        self.saveState()
        self.setStrokeColor(COLOR_BORDE)
        self.setLineWidth(0.4)
        self.line(
            MARGEN_HORIZONTAL, 13 * mm, A4[0] - MARGEN_HORIZONTAL, 13 * mm
        )
        self.setFillColor(COLOR_SUAVE)
        self.setFont(FUENTE_REGULAR, 7.5)
        self.drawRightString(
            A4[0] - MARGEN_HORIZONTAL,
            8.5 * mm,
            (
                f"{_traducir('Página')} {self._pageNumber} "
                f"{_traducir('de')} {total_paginas}"
            ),
        )
        self.restoreState()


def generar_pdf_empresa(store):
    """Genera el PDF en memoria usando el idioma de la petición activa."""
    datos = datos_reporte(store)
    historia = construir_historia(datos)
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGEN_HORIZONTAL,
        rightMargin=MARGEN_HORIZONTAL,
        topMargin=MARGEN_SUPERIOR,
        bottomMargin=MARGEN_INFERIOR,
        title=_traducir("Reporte de competitividad"),
        author=_traducir("PricePeek Business"),
    )
    nombre_tienda = " ".join(str(store.name or "").split())
    fecha = datos["generated_date"]

    def crear_canvas(*args, **kwargs):
        pdf_canvas = _CanvasNumerado(*args, **kwargs)
        pdf_canvas.setTitle(_traducir("Reporte de competitividad"))
        pdf_canvas.setAuthor(_traducir("PricePeek Business"))
        pdf_canvas.setSubject(
            f"{_traducir('Tienda asignada')}: {nombre_tienda}"
        )
        pdf_canvas.setKeywords(f"{nombre_tienda}; {fecha}")
        return pdf_canvas

    def dibujar_encabezado(pdf_canvas, doc):
        pdf_canvas.saveState()
        y = A4[1] - 13 * mm
        derecha = A4[0] - doc.rightMargin
        pdf_canvas.setFillColor(COLOR_TEXTO)
        pdf_canvas.setFont(FUENTE_GRUESA, 13)
        pdf_canvas.drawString(
            doc.leftMargin, y, _traducir("PricePeek Business")
        )
        pdf_canvas.setFont(FUENTE_GRUESA, 9)
        pdf_canvas.drawRightString(derecha, y, nombre_tienda)
        pdf_canvas.setFillColor(COLOR_SUAVE)
        pdf_canvas.setFont(FUENTE_REGULAR, 7.5)
        pdf_canvas.drawRightString(
            derecha,
            y - 5 * mm,
            _traducir("Generado el {fecha}", fecha=fecha),
        )
        pdf_canvas.setStrokeColor(COLOR_ACENTO)
        pdf_canvas.setLineWidth(1.1)
        pdf_canvas.line(doc.leftMargin, y - 8 * mm, derecha, y - 8 * mm)
        pdf_canvas.restoreState()

    documento.build(
        historia,
        canvasmaker=crear_canvas,
        onFirstPage=dibujar_encabezado,
        onLaterPages=dibujar_encabezado,
    )
    return buffer.getvalue()
