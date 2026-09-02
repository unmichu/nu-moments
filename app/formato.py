"""Formato de números para la interfaz y para la API.

Una sola regla, en un solo sitio: **todo porcentaje se escribe con exactamente
dos decimales y un espacio fino antes del signo** — `86.43 %`, `14.00 %`,
`0.00 %`. Antes había mezcla (`86.43 %` en un lado, `14.0 %` en otro) y la
pantalla parecía sacar los números de dos fuentes distintas.

El valor numérico sigue viajando en la respuesta tal cual: la API publica
`pct_silencio: 86.43` **y** `pct_silencio_texto: "86.43 %"`. Quien calcula usa
el número; quien pinta usa el texto. Ninguno de los dos redondea por su cuenta.
"""
from __future__ import annotations

DECIMALES_PCT = 2
GUION = "—"          # lo que se pinta cuando un número no existe


def pct(valor, de_fraccion=False):
    """`86.4321` → `'86.43 %'`. Con `de_fraccion=True`, `0.864321` → `'86.43 %'`.

    `None` no se convierte en cero: se escribe con un guion, porque «no lo sé»
    y «es cero» no son lo mismo.
    """
    if valor is None:
        return GUION
    v = float(valor) * (100.0 if de_fraccion else 1.0)
    return f"{v:.{DECIMALES_PCT}f} %"


def pct_num(valor, de_fraccion=False):
    """El mismo número, redondeado igual que el texto, para poder compararlos."""
    if valor is None:
        return None
    v = float(valor) * (100.0 if de_fraccion else 1.0)
    return round(v, DECIMALES_PCT)


def veces(valor):
    """`3.214` → `'3.21×'`. El múltiplo sobre una tasa base."""
    if valor is None:
        return GUION
    return f"{float(valor):.2f}×"


def dias(valor, decimales=4):
    """Días de descubierto evitados. Siempre con signo: el daño se ve."""
    if valor is None:
        return GUION
    return f"{float(valor):+.{decimales}f} días"


def horas_de_dias(valor):
    """Los mismos días, en horas. Es cambio de unidad, no otro dato."""
    if valor is None:
        return None
    return round(float(valor) * 24.0, 2)


def bloque_pct(valor, de_fraccion=False):
    """`{valor, texto}` para un porcentaje que viaja a la pantalla."""
    return {"valor": pct_num(valor, de_fraccion), "texto": pct(valor, de_fraccion)}
