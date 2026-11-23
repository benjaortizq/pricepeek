"""Validación de códigos de barras UPC/EAN (RF-39, UC-12)."""

from dataclasses import dataclass

# Un código válido tiene 8 (EAN-8), 12 (UPC-A), 13 (EAN-13) o 14 (GTIN-14) dígitos.
FORMATOS = {8: "EAN-8", 12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}

# Todos los códigos se guardan con 14 dígitos (rellenando con ceros a la izquierda),
# para que el mismo producto no quede registrado dos veces con distinto formato.
LONGITUD_NORMALIZADA = 14


@dataclass(frozen=True)
class ResultadoCodigo:
    valido: bool
    codigo: str = ""  # el código sin espacios en los extremos
    formato: str = ""  # "EAN-8", "UPC-A", "EAN-13" o "GTIN-14" (solo si es válido)
    normalizado: str = ""  # el código con 14 dígitos: es el que hay que guardar y buscar
    motivo: str = ""  # por qué se rechazó (solo si es inválido)

    def __bool__(self):
        return self.valido


def calcular_digito_verificador(cuerpo):
    """Dígito verificador GS1 de un código sin su último dígito.

    Desde la derecha, los dígitos se multiplican por 3, 1, 3, 1... y el
    verificador es lo que falta para llegar al siguiente múltiplo de 10.
    """
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(cuerpo)))
    return (10 - total % 10) % 10


def validar_codigo_barras(codigo):
    """Valida longitud, formato y dígito verificador de un UPC/EAN."""
    codigo = "" if codigo is None else str(codigo).strip()

    if not codigo:
        return ResultadoCodigo(
            False,
            codigo,
            motivo="El código de barras está vacío. Ingrese un código UPC/EAN de 8, 12, 13 o 14 dígitos.",
        )

    # isascii evita que pasen dígitos de otros alfabetos (por ejemplo "١٢٣").
    if not (codigo.isascii() and codigo.isdigit()):
        return ResultadoCodigo(
            False,
            codigo,
            motivo="El código de barras solo puede tener dígitos, sin espacios, guiones ni letras.",
        )

    if len(codigo) not in FORMATOS:
        return ResultadoCodigo(
            False,
            codigo,
            motivo=f"El código de barras tiene {len(codigo)} dígitos; debe tener 8, 12, 13 o 14.",
        )

    esperado = calcular_digito_verificador(codigo[:-1])
    if int(codigo[-1]) != esperado:
        return ResultadoCodigo(
            False,
            codigo,
            motivo=(
                f"El dígito verificador no coincide (debería terminar en {esperado}). "
                "Revise que el código esté completo y bien escrito."
            ),
        )

    return ResultadoCodigo(
        True,
        codigo,
        formato=FORMATOS[len(codigo)],
        normalizado=codigo.zfill(LONGITUD_NORMALIZADA),
    )
