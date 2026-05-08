"""Listas de vuelos: pendientes, mis vuelos."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from formatters import safe, fmt_vuelo, icono_estado, nombre_estado
from currency import formato_mxn
from utils import autorizado, rechazar, db_thread
from keyboards import kb_volver, kb_acciones_vuelo
from states import ST_MENU


def _etiqueta_vuelo(v) -> str:
    """Etiqueta breve para botón de lista, robusta a campos vacíos."""
    aero = (v["aerolinea"] or "").strip()
    ori  = (v["origen"]    or "").strip()
    des  = (v["destino"]   or "").strip()
    if aero or ori or des:
        partes = []
        if aero:
            partes.append(aero[:18])
        if ori or des:
            partes.append(f"{ori[:8]}→{des[:8]}")
        return " · ".join(partes)
    # Vuelo nuevo (con captura): mostrar creador y monto
    return f"{(v['creado_por'] or '?')[:14]} · {formato_mxn(v['monto_cobrado'])}"


def _build_kb_lista(vuelos, user_id: int):
    filas = []
    for v in vuelos:
        filas.append([InlineKeyboardButton(
            f"{icono_estado(v['estado'])} #{v['id']} · {_etiqueta_vuelo(v)}",
            callback_data=f"vl_ver:{v['id']}",
        )])
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    return InlineKeyboardMarkup(filas)


# ═════════════════════════════════════════════════════════════════════════════
#  PENDIENTES
# ═════════════════════════════════════════════════════════════════════════════

async def vl_pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    vuelos = await db_thread(db.vuelos_pendientes)
    if not vuelos:
        await q.edit_message_text(
            "⏳ *Pendientes*\n\n_No hay vuelos pendientes en este momento._",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    user_id = update.effective_user.id

    lineas = [f"⏳ *Pendientes* ({len(vuelos)})\n─────────────────────────────"]
    for v in vuelos:
        aero = v["aerolinea"] or ""
        ori  = v["origen"]    or ""
        des  = v["destino"]   or ""
        fv   = v["fecha_vuelo"] or ""
        hr   = v["horario"]   or ""
        ruta_linea = ""
        if aero or ori or des:
            ruta_linea = f"\n   ✈️ {safe(aero)}  ·  {safe(ori)} → {safe(des)}"
        if fv or hr:
            ruta_linea += f"\n   📅 {safe(fv)}   🕐 {safe(hr)}"
        adjunto = "  📷" if v["foto_file_id"] else ""
        lineas.append(
            f"*#{v['id']}*{adjunto}{ruta_linea}\n"
            f"   💰 *{formato_mxn(v['monto_cobrado'])}*  👤 {safe(v['creado_por'])}"
        )

    await q.edit_message_text(
        "\n\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=_build_kb_lista(vuelos, user_id),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  MIS VUELOS (los que yo tomé/saqué)
# ═════════════════════════════════════════════════════════════════════════════

async def vl_mios(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    user_id = update.effective_user.id
    vuelos = await db_thread(db.vuelos_de_usuario, user_id)

    if not vuelos:
        await q.edit_message_text(
            "🛫 *Mis Vuelos*\n\n_Aún no has tomado ningún vuelo._",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    # Agrupar por estado
    por_estado = {"en_proceso": [], "completado": [], "cancelado": []}
    for v in vuelos:
        por_estado.setdefault(v["estado"], []).append(v)

    lineas = [f"🛫 *Mis Vuelos* ({len(vuelos)})\n─────────────────────────────"]

    for estado in ("en_proceso", "completado", "cancelado"):
        grupo = por_estado.get(estado, [])
        if not grupo:
            continue
        lineas.append(f"\n*{icono_estado(estado)} {nombre_estado(estado)}* ({len(grupo)})")
        for v in grupo:
            aero = v["aerolinea"] or ""
            ori  = v["origen"]    or ""
            des  = v["destino"]   or ""
            ruta = ""
            if aero or ori or des:
                ruta = f"✈️ {safe(aero)}  ·  {safe(ori)} → {safe(des)}  ·  "
            adjunto = "📷  " if v["foto_file_id"] else ""
            lineas.append(
                f"  *#{v['id']}* {adjunto}{ruta}*{formato_mxn(v['monto_cobrado'])}*"
            )

    await q.edit_message_text(
        "\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=_build_kb_lista(vuelos, user_id),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  VER UN VUELO INDIVIDUAL
# ═════════════════════════════════════════════════════════════════════════════

async def vl_ver(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    vuelo = await db_thread(db.get_vuelo, vid)
    if not vuelo:
        await q.edit_message_text("❌ Vuelo no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    user_id = update.effective_user.id
    filas = kb_acciones_vuelo(vuelo, user_id)
    filas.append([InlineKeyboardButton("⬅️  Volver",         callback_data="vl_pendientes")])
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    kb = InlineKeyboardMarkup(filas)

    foto = vuelo["foto_file_id"]
    if foto:
        # No se puede editar un mensaje de texto a foto: borramos y mandamos nuevo.
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.chat.send_photo(
            photo=foto,
            caption=fmt_vuelo(vuelo),
            parse_mode="Markdown",
            reply_markup=kb,
        )
    else:
        await q.edit_message_text(
            fmt_vuelo(vuelo),
            parse_mode="Markdown",
            reply_markup=kb,
        )
    return ST_MENU
