"""
Consulta múltiples APIs de BIN en paralelo y devuelve banco + país por consenso.

APIs sin clave (siempre activas):
  1. binlist.net
  2. freebinchecker.com

APIs opcionales (activar con keys en .env):
  3. bintable.com         → BINTABLE_API_KEY
  4. binsearchlookup.com  → BINSEARCH_API_KEY + BINSEARCH_USER_ID
  5. handyapi.com         → HANDYAPI_KEY
  6. api-ninjas.com       → APIINJAS_KEY
"""
import asyncio
import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timedelta

# ─── API keys opcionales ──────────────────────────────────────────────────────
_BINTABLE_KEY   = os.getenv("BINTABLE_API_KEY", "")
_BINSEARCH_KEY  = os.getenv("BINSEARCH_API_KEY", "")
_BINSEARCH_UID  = os.getenv("BINSEARCH_USER_ID", "")
_HANDYAPI_KEY   = os.getenv("HANDYAPI_KEY", "")
_APIINJAS_KEY   = os.getenv("APIINJAS_KEY", "")

# ─── Caché en memoria (BIN info no cambia → 24 h) ─────────────────────────────
_cache: dict = {}
_TTL = timedelta(days=3650)


# ─── Helper HTTP ──────────────────────────────────────────────────────────────

def _get(url: str, headers: dict | None = None) -> dict | None:
    """GET bloqueante con timeout de 6 s. Devuelve JSON o None."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _s(val) -> str:
    return str(val or "").strip()


# ─── Parsers por fuente ───────────────────────────────────────────────────────

def _parse_binlist(d: dict) -> dict | None:
    bank    = _s(d.get("bank", {}).get("name"))
    country = _s(d.get("country", {}).get("name"))
    code    = _s(d.get("country", {}).get("alpha2"))
    brand   = _s(d.get("scheme", "")).upper()
    ctype   = _s(d.get("type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


def _parse_freebinchecker(d: dict) -> dict | None:
    bank    = _s(d.get("issuer", {}).get("name"))
    country = _s(d.get("country", {}).get("name"))
    code    = _s(d.get("country", {}).get("alpha_2"))
    brand   = _s(d.get("card", {}).get("scheme", "")).upper()
    ctype   = _s(d.get("card", {}).get("type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


def _parse_bintable(d: dict) -> dict | None:
    inner   = d.get("data") or {}
    bank    = _s((inner.get("bank") or {}).get("name"))
    country = _s((inner.get("country") or {}).get("name"))
    code    = _s((inner.get("country") or {}).get("code"))
    brand   = _s((inner.get("card") or {}).get("scheme", "")).upper()
    ctype   = _s((inner.get("card") or {}).get("type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


def _parse_binsearch(d: dict) -> dict | None:
    inner   = d.get("data") or {}
    bank    = _s(inner.get("Issuer"))
    country = _s(inner.get("CountryName"))
    code    = _s(inner.get("isoCode2"))
    brand   = _s(inner.get("Brand", "")).upper()
    ctype   = _s(inner.get("Type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


def _parse_handyapi(d: dict) -> dict | None:
    bank    = _s(d.get("issuer") or d.get("bank") or "")
    c_data  = d.get("country") or {}
    country = _s(c_data.get("name") if isinstance(c_data, dict) else c_data)
    code    = _s(c_data.get("code") if isinstance(c_data, dict) else "")
    brand   = _s(d.get("scheme", "")).upper()
    ctype   = _s(d.get("type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


def _parse_apiinjas(d) -> dict | None:
    if isinstance(d, list):
        d = d[0] if d else {}
    bank    = _s(d.get("issuer"))
    country = _s(d.get("country"))
    code    = _s(d.get("country_iso2"))
    brand   = _s(d.get("brand", "")).upper()
    ctype   = _s(d.get("type", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype} if bank or country else None


# ─── Fetch functions (bloqueantes, corren en threads) ─────────────────────────

def _fetch_binlist(b: str) -> dict | None:
    d = _get(f"https://lookup.binlist.net/{b}", {"Accept-Version": "3"})
    return _parse_binlist(d) if d else None


def _fetch_freebinchecker(b: str) -> dict | None:
    d = _get(f"https://api.freebinchecker.com/bin/{b}")
    return _parse_freebinchecker(d) if d else None


def _fetch_bintable(b: str) -> dict | None:
    if not _BINTABLE_KEY:
        return None
    d = _get(f"https://api.bintable.com/v1/{b}?api_key={_BINTABLE_KEY}")
    return _parse_bintable(d) if d else None


def _fetch_binsearch(b: str) -> dict | None:
    if not _BINSEARCH_KEY or not _BINSEARCH_UID:
        return None
    d = _get(
        f"https://api.binsearchlookup.com/lookup?bin={b}",
        {"X-API-Key": _BINSEARCH_KEY, "X-User-ID": _BINSEARCH_UID},
    )
    return _parse_binsearch(d) if d else None


def _fetch_handyapi(b: str) -> dict | None:
    if not _HANDYAPI_KEY:
        return None
    d = _get(f"https://data.handyapi.com/bin/{b}", {"x-api-key": _HANDYAPI_KEY})
    return _parse_handyapi(d) if d else None


def _fetch_apiinjas(b: str) -> dict | None:
    if not _APIINJAS_KEY:
        return None
    d = _get(
        f"https://api.api-ninjas.com/v2/bin?bin={b}",
        {"X-Api-Key": _APIINJAS_KEY},
    )
    return _parse_apiinjas(d) if d else None


# ─── Consenso ─────────────────────────────────────────────────────────────────

def _consenso(resultados: list[dict]) -> dict:
    """Elige banco y país por mayoría de votos."""
    banks    = Counter(r["bank"]         for r in resultados if r.get("bank"))
    countries= Counter(r["country"]      for r in resultados if r.get("country"))
    codes    = Counter(r["country_code"] for r in resultados if r.get("country_code"))
    brands   = Counter(r["brand"]        for r in resultados if r.get("brand"))
    types    = Counter(r["type"]         for r in resultados if r.get("type"))

    bank,    bank_v  = banks.most_common(1)[0]    if banks    else ("", 0)
    country, _       = countries.most_common(1)[0] if countries else ("", 0)
    code             = codes.most_common(1)[0][0]  if codes    else ""
    brand            = brands.most_common(1)[0][0] if brands   else ""
    ctype            = types.most_common(1)[0][0]  if types    else ""

    return {
        "bank":         bank,
        "country":      country,
        "country_code": code,
        "brand":        brand,
        "type":         ctype,
        "fuentes":      len(resultados),   # cuántas APIs respondieron
        "confianza":    bank_v,            # cuántas coincidieron en el banco
    }


# ─── API pública ──────────────────────────────────────────────────────────────

async def consultar_bin(bin_num: str) -> dict | None:
    """
    Consulta todas las APIs en paralelo. Devuelve consenso o None.
    Campos del resultado: bank, country, country_code, brand, type, fuentes, confianza.
    """
    now = datetime.utcnow()
    hit = _cache.get(bin_num)
    if hit and (now - hit["ts"]) < _TTL:
        return hit["data"]

    fetchers = [
        _fetch_binlist,
        _fetch_freebinchecker,
        _fetch_bintable,
        _fetch_binsearch,
        _fetch_handyapi,
        _fetch_apiinjas,
    ]

    raw = await asyncio.gather(*[asyncio.to_thread(fn, bin_num) for fn in fetchers],
                               return_exceptions=True)
    resultados = [r for r in raw if isinstance(r, dict) and r]

    if not resultados:
        return None

    info = _consenso(resultados)
    _cache[bin_num] = {"data": info, "ts": now}
    return info
