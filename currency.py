"""Parsing y formateo de montos en pesos mexicanos."""
import re


def parsear_monto(texto: str) -> float:
    """
    Parsea un monto en MXN.
    Acepta: '1500', '1,500.50', '$1500', '1500 MX', '1500 MXN', '1500 pesos'
    """
    if not texto:
        raise ValueError("Escribe el monto.")

    t = texto.strip().upper().replace(",", "").replace("$", "")
    t = re.sub(r"\s*(MXN|MX|PESOS|PESO)\s*$", "", t).strip()

    try:
        monto = float(t)
    except ValueError:
        raise ValueError(
            "No reconocí el monto.\n"
            "Escríbelo así: `1500` o `1,500.50`"
        )

    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero.")
    if monto > 10_000_000:
        raise ValueError("Monto demasiado grande. Verifica la cantidad.")

    return round(monto, 2)


def formato_mxn(monto: float) -> str:
    return f"${monto:,.2f} MXN"
