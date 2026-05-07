"""Flujo de captura de un nuevo vuelo (8 pasos + confirmación)."""
import re
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from currency import parsear_monto, formato_mxn
from formatters import safe, nombre_usuario
from notifications import notificar_otros
from utils import autorizado, rechazar, db_thread, reply_clean, remember_panel
from keyboards import kb_cancelar, kb_saltar, kb_aceptar_vuelo
from states import (
    ST_VC_AEROLINEA, ST_VC_ORIGEN, ST_VC_DESTINO, ST_VC_FECHA, ST_VC_HORARIO,
    ST_VC_PASAJEROS, ST_VC_EXTRAS, ST_VC_COBRADO, ST_VC_CONFIRMAR, ST_MENU,
)

TOTAL_PASOS = 8


def _header(paso: int, titulo_campo: str, ud: dict) -> str:
    """Construye el header con el progreso y los campos ya capturados."""
    capturados = []
    if "vc_aerolinea" in ud:
        capturados.append(f"✅ Aerolínea: *{safe(ud['vc_aerolinea'])}*")
    if "vc_origen" in ud and "vc_destino" in ud:
        capturados.append(f"✅ Ruta: {safe(ud['vc_origen'])} → {safe(ud['vc_destino'])}")
    elif "vc_origen" in ud:
        capturados.append(f"✅ Origen: {safe(ud['vc_origen'])}")
    if "vc_fecha" in ud:
        capturados.append(f"✅ Fecha: {safe(ud['vc_fecha'])}")
    if "vc_horario" in ud:
        capturados.append(f"✅ Horario: {safe(ud['vc_horario'])}")
    if "vc_pasajeros" in ud:
        n = ud["vc_pasajeros"].count("\n") + 1 if ud["vc_pasajeros"] else 0
        capturados.append(f"✅ Pasajeros: {n}")
    if "vc_extras" in ud:
        ex = ud["vc_extras"]
        capturados.append(f"✅ Extras: {safe(ex) if ex else '—'}")

    cap_txt = "\n".join(capturados)
    sep = "\n" if cap_txt else ""
    return (
        f"✈️ *Nuevo Vuelo*  ·  Paso {paso}/{TOTAL_PASOS}\n"
        f"{cap_txt}{sep}\n"
        f"*{titulo_campo}*"
    )


# ─────────────────────────── INICIO ──────────────────────────────────────────

async def vc_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()

    msg = await q.edit_message_text(
        _header(1, "Aerolínea", ctx.user_data) + "\n_Ej: Aeroméxico, Volaris, Viva, American_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_VC_AEROLINEA


# ─────────────────────────── PASO 1: Aerolínea ───────────────────────────────

async def vc_aerolinea(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 2 or len(txt) > 50:
        await reply_clean(update, ctx,
            "❌ Aerolínea inválida (2–50 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_AEROLINEA

    ctx.user_data["vc_aerolinea"] = txt
    await reply_clean(update, ctx,
        _header(2, "Origen", ctx.user_data) + "\n_Ej: CDMX, MEX, Cancún_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_ORIGEN


# ─────────────────────────── PASO 2: Origen ──────────────────────────────────

async def vc_origen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 2 or len(txt) > 50:
        await reply_clean(update, ctx,
            "❌ Origen inválido (2–50 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_ORIGEN

    ctx.user_data["vc_origen"] = txt
    await reply_clean(update, ctx,
        _header(3, "Destino", ctx.user_data) + "\n_Ej: Guadalajara, GDL, Madrid_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_DESTINO


# ─────────────────────────── PASO 3: Destino ─────────────────────────────────

async def vc_destino(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 2 or len(txt) > 50:
        await reply_clean(update, ctx,
            "❌ Destino inválido (2–50 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_DESTINO

    ctx.user_data["vc_destino"] = txt
    await reply_clean(update, ctx,
        _header(4, "Fecha del vuelo", ctx.user_data) + "\n_Formato: DD/MM/AAAA · Ej: 15/06/2026_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_FECHA


# ─────────────────────────── PASO 4: Fecha ───────────────────────────────────

_RE_FECHA = re.compile(r"^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2}|\d{4})$")


def _normalizar_fecha(txt: str) -> str | None:
    m = _RE_FECHA.match(txt.strip())
    if not m:
        return None
    d, mo, a = m.groups()
    a = "20" + a if len(a) == 2 else a
    try:
        dt = datetime(int(a), int(mo), int(d))
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return None


async def vc_fecha(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    fecha = _normalizar_fecha(txt)
    if not fecha:
        await reply_clean(update, ctx,
            "❌ Fecha inválida. Usa formato `DD/MM/AAAA` (ej: `15/06/2026`):",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_FECHA

    ctx.user_data["vc_fecha"] = fecha
    await reply_clean(update, ctx,
        _header(5, "Horario del vuelo", ctx.user_data) +
        "\n_Ej: `06:30 → 09:15` · `14:00` · `Salida 22:00`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_HORARIO


# ─────────────────────────── PASO 5: Horario ─────────────────────────────────

async def vc_horario(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 2 or len(txt) > 80:
        await reply_clean(update, ctx,
            "❌ Horario inválido (2–80 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_HORARIO

    ctx.user_data["vc_horario"] = txt
    await reply_clean(update, ctx,
        _header(6, "Pasajeros", ctx.user_data) +
        "\n_Nombre completo + fecha de nacimiento (DD/MM/AA)_\n"
        "_Un pasajero por línea, o todos en un mensaje._\n\n"
        "_Ej:_\n"
        "_`Juan Pérez García 15/03/85`_\n"
        "_`María López Ruiz 22/06/90`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_PASAJEROS


# ─────────────────────────── PASO 6: Pasajeros ───────────────────────────────

async def vc_pasajeros(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 5 or len(txt) > 1500:
        await reply_clean(update, ctx,
            "❌ Lista de pasajeros inválida (mínimo 5, máximo 1500 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_PASAJEROS

    ctx.user_data["vc_pasajeros"] = txt
    await reply_clean(update, ctx,
        _header(7, "Extras (opcional)", ctx.user_data) +
        "\n_Notas para quien saque el vuelo: equipaje, asientos, preferencias…_\n"
        "_Ej: `2 maletas documentadas + asientos juntos`_",
        parse_mode="Markdown",
        reply_markup=kb_saltar("vc_skip_extras"),
    )
    return ST_VC_EXTRAS


# ─────────────────────────── PASO 7: Extras ──────────────────────────────────

async def vc_extras(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) > 500:
        await reply_clean(update, ctx,
            "❌ Nota de extras demasiado larga (máx 500). Intenta de nuevo:",
            reply_markup=kb_saltar("vc_skip_extras"),
        )
        return ST_VC_EXTRAS

    ctx.user_data["vc_extras"] = txt
    return await _pedir_cobrado(update, ctx, edit=False)


async def vc_skip_extras(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["vc_extras"] = ""
    return await _pedir_cobrado(update, ctx, edit=True)


async def _pedir_cobrado(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *, edit: bool) -> int:
    texto = (
        _header(8, "Total cobrado al cliente", ctx.user_data) +
        "\n_Ej: `5500` o `5,500.50`  (siempre en MXN)_"
    )
    if edit and update.callback_query:
        msg = await update.callback_query.edit_message_text(
            texto, parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        remember_panel(ctx, msg)
    else:
        await reply_clean(update, ctx, texto,
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
    return ST_VC_COBRADO


# ─────────────────────────── PASO 8: Cobrado ─────────────────────────────────

async def vc_cobrado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = parsear_monto(update.message.text)
    except ValueError as e:
        await reply_clean(update, ctx,
            f"❌ {e}",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_COBRADO

    ctx.user_data["vc_cobrado"] = monto
    return await _mostrar_confirmacion(update, ctx)


# ─────────────────────────── CONFIRMACIÓN ────────────────────────────────────

async def _mostrar_confirmacion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ud = ctx.user_data
    extras_txt = ud["vc_extras"] if ud["vc_extras"] else "—"

    resumen = (
        "📋 *Confirmar Nuevo Vuelo*\n"
        "─────────────────────────────\n"
        f"✈️ Aerolínea: *{safe(ud['vc_aerolinea'])}*\n"
        f"🛫 Ruta: {safe(ud['vc_origen'])} → {safe(ud['vc_destino'])}\n"
        f"📅 Fecha: {safe(ud['vc_fecha'])}\n"
        f"🕐 Horario: {safe(ud['vc_horario'])}\n"
        f"👥 Pasajeros:\n{safe(ud['vc_pasajeros'])}\n"
        f"📝 Extras: _{safe(extras_txt)}_\n"
        f"💰 Total cobrado: *{formato_mxn(ud['vc_cobrado'])}*\n"
        "─────────────────────────────\n"
        "_¿Publicar este vuelo a los socios?_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Publicar vuelo", callback_data="vc_publicar")],
        [InlineKeyboardButton("❌  Cancelar",        callback_data="menu")],
    ])

    await reply_clean(update, ctx, resumen,
        parse_mode="Markdown", reply_markup=kb,
    )
    return ST_VC_CONFIRMAR


# ─────────────────────────── PUBLICAR ────────────────────────────────────────

async def vc_publicar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("Publicando…")

    ud = ctx.user_data
    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(
        db.crear_vuelo,
        creado_por=nombre,
        creado_por_id=tg_user.id,
        aerolinea=ud["vc_aerolinea"],
        origen=ud["vc_origen"],
        destino=ud["vc_destino"],
        fecha_vuelo=ud["vc_fecha"],
        horario=ud["vc_horario"],
        pasajeros=ud["vc_pasajeros"],
        extras=ud.get("vc_extras", ""),
        monto_cobrado=ud["vc_cobrado"],
    )
    vid = vuelo["id"]
    ctx.user_data.clear()

    # Notificar a los demás socios
    aviso = (
        "🔔 *Nuevo Vuelo Disponible*\n"
        "─────────────────────────────\n"
        f"✈️ *{safe(vuelo['aerolinea'])}*\n"
        f"🛫 {safe(vuelo['origen'])} → {safe(vuelo['destino'])}\n"
        f"📅 {safe(vuelo['fecha_vuelo'])}   🕐 {safe(vuelo['horario'])}\n"
        f"💰 *{formato_mxn(vuelo['monto_cobrado'])}*\n"
        f"👤 Alta: {safe(vuelo['creado_por'])}"
    )
    await notificar_otros(
        update.get_bot(), tg_user.id, aviso,
        parse_mode="Markdown", reply_markup=kb_aceptar_vuelo(vid),
    )

    # Confirmación al creador
    await q.edit_message_text(
        f"✅ *Vuelo #{vid} publicado*\n\n"
        f"_Se notificó a los demás socios._\n"
        f"_Cualquiera puede tomarlo desde 📋 Pendientes._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠  Menú Principal", callback_data="menu"),
        ]]),
    )
    return ST_MENU
