"""Listas de vuelos: pendientes, mis vuelos."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from formatters import safe, fmt_vuelo, icono_estado, nombre_estado
from currency import formato_mxn
from utils import autorizado, rechazar, db_thread
from keyboards import kb_volver, kb_acciones_vuelo
from states import ST_MENU


def _build_kb_lista(vuelos, user_id: int):
    filas = []
    for v in vuelos:
        # Botón para ver el vuelo en detalle
        filas.append([InlineKeyboardButton(
            f"{icono_estado(v['estado'])} #{v['id']} · {v['aerolinea'][:18]} · "
            f"{v['origen'][:8]}→{v['destino'][:8]}",
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
        lineas.append(
            f"*#{v['id']}* ✈️ {safe(v['aerolinea'])}  ·  "
            f"{safe(v['origen'])} → {safe(v['destino'])}\n"
            f"   📅 {safe(v['fecha_vuelo'])}   🕐 {safe(v['horario'])}\n"
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
            lineas.append(
                f"  *#{v['id']}* ✈️ {safe(v['aerolinea'])}  ·  "
                f"{safe(v['origen'])} → {safe(v['destino'])}  ·  "
                f"*{formato_mxn(v['monto_cobrado'])}*"
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

    await q.edit_message_text(
        fmt_vuelo(vuelo),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas),
    )
    return ST_MENU
