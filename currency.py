"""
Detección de moneda y conversión a MXN.

Formato OBLIGATORIO:
  "1500 MX"  → 1500 pesos mexicanos
  "100 USD"  → 100 dólares  (se convierte a MXN)

Sin sufijo → error, el usuario debe especificar siempre.
"""
import re
import urllib.request
import json
from datetime import datetime, timedelta

_cache: dict = {}   # {"rate": float, "ts": datetime}
_CACHE_TTL_MIN = 60


def _fetch_usd_mxn() -> float:
    """Obtiene el tipo de cambio USD→MXN desde open.er-api.com (sin key)."""
    url = "https://open.er-api.com/v6/latest/USD"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        return float(data["rates"]["MXN"])
    except Exception:
        # Fallback si no hay internet: tipo de cambio aproximado
        return 17.5


def get_tipo_cambio() -> float:
    """Devuelve USD/MXN usando caché de 60 minutos."""
    now = datetime.utcnow()
    if _cache.get("rate") and (now - _cache["ts"]) < timedelta(minutes=_CACHE_TTL_MIN):
        return _cache["rate"]
    rate = _fetch_usd_mxn()
    _cache["rate"] = rate
    _cache["ts"] = now
    return rate


def parsear_monto(texto: str):
    """
    Parsea un string de monto.

    Retorna (monto_original, moneda, monto_mxn, tipo_cambio)
    moneda: 'MXN' o 'USD'
    """
    texto = texto.strip().upper().replace(",", "")
    # Busca número seguido de sufijo de moneda
    m = re.match(r"^([\d.]+)\s*(USD|MX|MXN|PESOS|DOLARES|DÓLARES)$", texto)
    if not m:
        raise ValueError(
            "Debes indicar la moneda:\n"
            "  `1500 MX` para pesos mexicanos\n"
            "  `100 USD` para dólares"
        )

    monto = float(m.group(1))
    sufijo = m.group(2)

    if sufijo in ("USD", "DOLARES", "DÓLARES"):
        moneda = "USD"
        tc = get_tipo_cambio()
        monto_mxn = round(monto * tc, 2)
    else:
        moneda = "MXN"
        tc = 1.0
        monto_mxn = monto

    return monto, moneda, monto_mxn, tc


def formato_mxn(monto: float) -> str:
    return f"${monto:,.2f} MXN"
