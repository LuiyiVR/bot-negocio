"""Listas de vuelos: pendientes y vuelos sacados."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from formatters import safe, fmt_vuelo, icono_estado
from currency import formato_mxn
from utils import autorizado, rechazar, db_thread, edit_to_text
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
        await edit_to_text(q,
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

    await edit_to_text(q,
        "\n\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=_build_kb_lista(vuelos, user_id),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  VUELOS SACADOS (completados — visibles para todos los socios)
# ═════════════════════════════════════════════════════════════════════════════

async def vl_sacados(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    vuelos = await db_thread(db.vuelos_sacados)
    if not vuelos:
        await edit_to_text(q,
            "🎫 *Vuelos Sacados*\n\n_Aún no hay vuelos completados._",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    user_id = update.effective_user.id

    lineas = [f"🎫 *Vuelos Sacados* ({len(vuelos)})\n─────────────────────────────"]
    for v in vuelos:
        aero = v["aerolinea"] or ""
        ori  = v["origen"]    or ""
        des  = v["destino"]   or ""
        ruta_linea = ""
        if aero or ori or des:
            ruta_linea = f"\n   ✈️ {safe(aero)}  ·  {safe(ori)} → {safe(des)}"
        comprobante = "  🧾" if v["foto_confirmacion_file_id"] else ""
        lineas.append(
            f"*#{v['id']}*{comprobante}{ruta_linea}\n"
            f"   💰 *{formato_mxn(v['monto_cobrado'])}*  🎯 {safe(v['aceptado_por'])}"
        )

    await edit_to_text(q,
        "\n\n".join(lineas),
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
        await edit_to_text(q, "❌ Vuelo no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    user_id = update.effective_user.id
    filas = kb_acciones_vuelo(vuelo, user_id)
    volver_cb = "vl_sacados" if vuelo["estado"] == "completado" else "vl_pendientes"
    filas.append([InlineKeyboardButton("⬅️  Volver",         callback_data=volver_cb)])
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    kb = InlineKeyboardMarkup(filas)

    foto = vuelo["foto_file_id"]
    foto_conf = vuelo["foto_confirmacion_file_id"]
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
            reply_markup=kb if not foto_conf else None,
        )
        if foto_conf:
            await q.message.chat.send_photo(
                photo=foto_conf,
                caption=f"🧾 *Número de confirmación — Vuelo #{vid}*",
                parse_mode="Markdown",
                reply_markup=kb,
            )
    else:
        await q.edit_message_text(
            fmt_vuelo(vuelo),
            parse_mode="Markdown",
            reply_markup=kb,
        )
        if foto_conf:
            await q.message.chat.send_photo(
                photo=foto_conf,
                caption=f"🧾 *Número de confirmación — Vuelo #{vid}*",
                parse_mode="Markdown",
            )
    return ST_MENU
