"""Formateo: texto, dinero, fechas, tarjetas de vuelo."""
from datetime import datetime

from currency import formato_mxn
from config import (
    ESTADO_PENDIENTE, ESTADO_EN_PROCESO,
    ESTADO_COMPLETADO, ESTADO_CANCELADO,
)


_ICONO_ESTADO = {
    ESTADO_PENDIENTE:  "⏳",
    ESTADO_EN_PROCESO: "🔄",
    ESTADO_COMPLETADO: "✅",
    ESTADO_CANCELADO:  "❌",
}

_NOMBRE_ESTADO = {
    ESTADO_PENDIENTE:  "Pendiente",
    ESTADO_EN_PROCESO: "En proceso",
    ESTADO_COMPLETADO: "Completado",
    ESTADO_CANCELADO:  "Cancelado",
}


def safe(text) -> str:
    """Escapa caracteres especiales de Markdown v1."""
    if text is None:
        return ""
    text = str(text)
    for ch in ("_", "*", "[", "]", "(", ")", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


def icono_estado(estado: str) -> str:
    return _ICONO_ESTADO.get(estado, "❔")


def nombre_estado(estado: str) -> str:
    return _NOMBRE_ESTADO.get(estado, estado.capitalize())


def fmt_fecha_corta(iso: str) -> str:
    """'2026-05-07 12:34:56' → '07/05/2026'"""
    if not iso:
        return "—"
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


def nombre_usuario(tg_user) -> str:
    """Nombre display del usuario de Telegram."""
    return tg_user.first_name or tg_user.username or str(tg_user.id)


def fmt_vuelo(v, *, breve: bool = False, mostrar_pasajeros: bool = True) -> str:
    """Tarjeta de vuelo formateada (acepta sqlite3.Row o dict)."""
    g = (lambda k: v[k]) if hasattr(v, "keys") else (lambda k: getattr(v, k))

    estado = g("estado")
    ico = icono_estado(estado)

    lineas = [
        f"{ico} *Vuelo #{g('id')}* — _{nombre_estado(estado)}_",
        f"✈️ *{safe(g('aerolinea'))}*",
        f"🛫 {safe(g('origen'))} → {safe(g('destino'))}",
        f"📅 {safe(g('fecha_vuelo'))}   🕐 {safe(g('horario'))}",
    ]

    if not breve and mostrar_pasajeros:
        lineas.append(f"👥 {safe(g('pasajeros'))}")
        extras = g("extras")
        if extras:
            lineas.append(f"📝 _{safe(extras)}_")

    lineas.append(f"💰 *{formato_mxn(g('monto_cobrado'))}*")
    lineas.append(f"👤 Alta: {safe(g('creado_por'))}")

    if g("aceptado_por"):
        lineas.append(f"🎯 Tomado: {safe(g('aceptado_por'))}")

    return "\n".join(lineas)
