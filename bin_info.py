"""
Consulta múltiples APIs de BIN en paralelo y devuelve banco + país por consenso.
Los resultados se guardan permanentemente en la BD (bin_cache). Solo se consultan
las APIs si el BIN no se conoce aún; tras un reinicio del bot se recupera de la BD.

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

import database as db

# ─── API keys opcionales ──────────────────────────────────────────────────────
_BINTABLE_KEY   = os.getenv("BINTABLE_API_KEY", "")
_BINSEARCH_KEY  = os.getenv("BINSEARCH_API_KEY", "")
_BINSEARCH_UID  = os.getenv("BINSEARCH_USER_ID", "")
_HANDYAPI_KEY   = os.getenv("HANDYAPI_KEY", "")
_APIINJAS_KEY   = os.getenv("APIINJAS_KEY", "")


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
    # binlist no tiene nivel explícito; "prepaid" es lo más cercano
    level   = "Prepaid" if d.get("prepaid") else ""
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


def _parse_freebinchecker(d: dict) -> dict | None:
    bank    = _s(d.get("issuer", {}).get("name"))
    country = _s(d.get("country", {}).get("name"))
    code    = _s(d.get("country", {}).get("alpha_2"))
    brand   = _s(d.get("card", {}).get("scheme", "")).upper()
    ctype   = _s(d.get("card", {}).get("type", "")).capitalize()
    level   = _s(d.get("card", {}).get("category", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


def _parse_bintable(d: dict) -> dict | None:
    inner   = d.get("data") or {}
    bank    = _s((inner.get("bank") or {}).get("name"))
    country = _s((inner.get("country") or {}).get("name"))
    code    = _s((inner.get("country") or {}).get("code"))
    brand   = _s((inner.get("card") or {}).get("scheme", "")).upper()
    ctype   = _s((inner.get("card") or {}).get("type", "")).capitalize()
    level   = _s((inner.get("card") or {}).get("category", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


def _parse_binsearch(d: dict) -> dict | None:
    inner   = d.get("data") or {}
    bank    = _s(inner.get("Issuer"))
    country = _s(inner.get("CountryName"))
    code    = _s(inner.get("isoCode2"))
    brand   = _s(inner.get("Brand", "")).upper()
    ctype   = _s(inner.get("Type", "")).capitalize()
    level   = _s(inner.get("Category", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


def _parse_handyapi(d: dict) -> dict | None:
    bank    = _s(d.get("issuer") or d.get("bank") or "")
    c_data  = d.get("country") or {}
    country = _s(c_data.get("name") if isinstance(c_data, dict) else c_data)
    code    = _s(c_data.get("code") if isinstance(c_data, dict) else "")
    brand   = _s(d.get("scheme", "")).upper()
    ctype   = _s(d.get("type", "")).capitalize()
    level   = _s(d.get("tier", "")).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


def _parse_apiinjas(d) -> dict | None:
    if isinstance(d, list):
        d = d[0] if d else {}
    bank    = _s(d.get("issuer"))
    country = _s(d.get("country"))
    code    = _s(d.get("country_iso2"))
    brand   = _s(d.get("brand", "")).upper()
    ctype   = _s(d.get("type", "")).capitalize()
    cats    = d.get("categories") or []
    level   = _s(cats[0] if isinstance(cats, list) and cats else cats).capitalize()
    return {"bank": bank, "country": country, "country_code": code,
            "brand": brand, "type": ctype, "level": level} if bank or country else None


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
    """Elige banco, país y nivel por mayoría de votos."""
    banks    = Counter(r["bank"]         for r in resultados if r.get("bank"))
    countries= Counter(r["country"]      for r in resultados if r.get("country"))
    codes    = Counter(r["country_code"] for r in resultados if r.get("country_code"))
    brands   = Counter(r["brand"]        for r in resultados if r.get("brand"))
    types    = Counter(r["type"]         for r in resultados if r.get("type"))
    levels   = Counter(r["level"]        for r in resultados if r.get("level"))

    bank,    bank_v  = banks.most_common(1)[0]    if banks    else ("", 0)
    country, _       = countries.most_common(1)[0] if countries else ("", 0)
    code             = codes.most_common(1)[0][0]  if codes    else ""
    brand            = brands.most_common(1)[0][0] if brands   else ""
    ctype            = types.most_common(1)[0][0]  if types    else ""
    level            = levels.most_common(1)[0][0] if levels   else ""

    return {
        "bank":         bank,
        "country":      country,
        "country_code": code,
        "brand":        brand,
        "type":         ctype,
        "level":        level,
        "fuentes":      len(resultados),
        "confianza":    bank_v,
    }


# ─── API pública ──────────────────────────────────────────────────────────────

async def consultar_bin(bin_num: str) -> dict | None:
    """
    1. Busca en la BD — si ya se conoce el BIN lo devuelve sin tocar ninguna API.
    2. Si no está en la BD consulta todas las APIs en paralelo, guarda el resultado
       permanentemente y lo devuelve.
    Campos del resultado: bank, country, country_code, brand, type, fuentes, confianza.
    """
    # ── 1. Caché persistente (BD) ─────────────────────────────────────────────
    row = await asyncio.to_thread(db.get_bin_cache, bin_num)
    if row:
        return {
            "bank":         row["bank"],
            "country":      row["country"],
            "country_code": row["country_code"],
            "brand":        row["brand"],
            "type":         row["type"],
            "level":        row["level"],
            "fuentes":      row["fuentes"],
            "confianza":    row["confianza"],
        }

    # ── 2. Consultar APIs en paralelo ─────────────────────────────────────────
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

    # ── 3. Guardar en BD para siempre ─────────────────────────────────────────
    await asyncio.to_thread(
        db.set_bin_cache,
        bin_num,
        info["bank"], info["country"], info["country_code"],
        info["brand"], info["type"], info["level"],
        info["fuentes"], info["confianza"],
    )

    return info
