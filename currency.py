"""
Detección de moneda y conversión a MXN.

Formato OBLIGATORIO:
  "1500 MX"  → 1500 pesos mexicanos
  "100 USD"  → 100 dólares  (se convierte a MXN)

Sin sufijo → error, el usuario debe especificar siempre.
"""
import re
import asyncio
import logging
import urllib.request
import json
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_cache: dict = {}   # {"rate": float, "ts": datetime}
_CACHE_TTL_MIN = 60


def _fetch_usd_mxn() -> float | None:
    """Obtiene el tipo de cambio USD→MXN desde open.er-api.com (sin key). Bloqueante."""
    url = "https://open.er-api.com/v6/latest/USD"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        return float(data["rates"]["MXN"])
    except Exception as e:
        logger.warning("No se pudo obtener tipo de cambio USD/MXN: %s", e)
        return None


async def get_tipo_cambio() -> float:
    """Devuelve USD/MXN usando caché de 60 minutos. No bloquea el event loop."""
    now = datetime.now(timezone.utc)
    if _cache.get("rate") and (now - _cache["ts"]) < timedelta(minutes=_CACHE_TTL_MIN):
        return _cache["rate"]
    rate = await asyncio.to_thread(_fetch_usd_mxn)
    if rate is not None:
        _cache["rate"] = rate
        _cache["ts"] = now
        return rate
    # API falló — usar cache viejo si existe, si no usar fallback
    if _cache.get("rate"):
        logger.warning("API de tipo de cambio falló, usando valor en caché: %s", _cache["rate"])
        return _cache["rate"]
    logger.warning("API de tipo de cambio falló y no hay caché, usando fallback 17.5")
    return 17.5


async def parsear_monto(texto: str):
    """
    Parsea un string de monto.

    Retorna (monto_original, moneda, monto_mxn, tipo_cambio)
    moneda: 'MXN' o 'USD'
    """
    texto = texto.strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*(USD|MX|MXN|PESOS|DOLARES|DÓLARES)$", texto)
    if not m:
        raise ValueError(
            "Debes indicar la moneda:\n"
            "  `1500 MX` para pesos mexicanos\n"
            "  `100 USD` para dólares"
        )

    monto = float(m.group(1))
    sufijo = m.group(2)

    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero.")
    if monto > 1_000_000:
        raise ValueError("Monto demasiado grande. Verifica la cantidad.")

    if sufijo in ("USD", "DOLARES", "DÓLARES"):
        moneda = "USD"
        tc = await get_tipo_cambio()
        monto_mxn = round(monto * tc, 2)
    else:
        moneda = "MXN"
        tc = 1.0
        monto_mxn = monto

    return monto, moneda, monto_mxn, tc


def formato_mxn(monto: float) -> str:
    return f"${monto:,.2f} MXN"
