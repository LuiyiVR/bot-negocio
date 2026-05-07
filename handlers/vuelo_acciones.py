"""Acciones sobre un vuelo: tomar, soltar, completar, cancelar."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from formatters import safe, fmt_vuelo, nombre_usuario
from currency import formato_mxn
from notifications import notificar_otros, notificar_a
from utils import autorizado, rechazar, db_thread
from keyboards import kb_volver, kb_confirmar_cancelar, kb_acciones_vuelo
from states import ST_MENU


def _kb_volver_con_acciones(vuelo, user_id: int):
    filas = kb_acciones_vuelo(vuelo, user_id)
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    return InlineKeyboardMarkup(filas)


# ═════════════════════════════════════════════════════════════════════════════
#  TOMAR
# ═════════════════════════════════════════════════════════════════════════════

async def vac_tomar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(db.tomar_vuelo, vid, nombre, tg_user.id)
    if not vuelo:
        # Otro lo tomó primero, o no estaba pendiente
        actual = await db_thread(db.get_vuelo, vid)
        if not actual:
            await q.edit_message_text("❌ Vuelo no encontrado.", reply_markup=kb_volver())
            return ST_MENU
        msg = {
            "en_proceso": f"ya lo tomó *{safe(actual['aceptado_por'])}*",
            "completado": "ya está completado",
            "cancelado":  "fue cancelado",
        }.get(actual["estado"], actual["estado"])
        await q.edit_message_text(
            f"⚠️ El vuelo *#{vid}* {msg}.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    # Notificar a los demás
    aviso = (
        f"🔄 *Vuelo #{vid} en proceso*\n\n"
        f"*{safe(nombre)}* tomó el vuelo:\n"
        f"✈️ {safe(vuelo['aerolinea'])}  ·  "
        f"{safe(vuelo['origen'])} → {safe(vuelo['destino'])}\n"
        f"📅 {safe(vuelo['fecha_vuelo'])}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await q.edit_message_text(
        "🔄 *Vuelo tomado*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo)}\n"
        "─────────────────────────────\n"
        "_Tómate el tiempo necesario para sacarlo._\n"
        "_Cuando esté listo, márcalo como_ *Completado*_,_\n"
        "_o_ *Suéltalo* _para que otro lo tome._",
        parse_mode="Markdown",
        reply_markup=_kb_volver_con_acciones(vuelo, tg_user.id),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  SOLTAR
# ═════════════════════════════════════════════════════════════════════════════

async def vac_soltar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(db.soltar_vuelo, vid, tg_user.id)
    if not vuelo:
        await q.edit_message_text(
            f"⚠️ No puedes soltar el vuelo *#{vid}* (no es tuyo o ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    # Notificar
    aviso = (
        f"🔓 *Vuelo #{vid} liberado*\n\n"
        f"*{safe(nombre)}* soltó el vuelo, vuelve a estar disponible:\n"
        f"✈️ {safe(vuelo['aerolinea'])}  ·  "
        f"{safe(vuelo['origen'])} → {safe(vuelo['destino'])}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}"
    )
    from keyboards import kb_aceptar_vuelo
    await notificar_otros(
        update.get_bot(), tg_user.id, aviso,
        parse_mode="Markdown", reply_markup=kb_aceptar_vuelo(vid),
    )

    await q.edit_message_text(
        f"🔓 *Vuelo #{vid} soltado*\n\n"
        f"Vuelve a estar disponible para los demás socios.",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  COMPLETAR
# ═════════════════════════════════════════════════════════════════════════════

async def vac_completar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(db.completar_vuelo, vid, tg_user.id)
    if not vuelo:
        await q.edit_message_text(
            f"⚠️ No puedes completar el vuelo *#{vid}* (no es tuyo o ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"✅ *Vuelo #{vid} completado*\n\n"
        f"*{safe(nombre)}* sacó el vuelo:\n"
        f"✈️ {safe(vuelo['aerolinea'])}  ·  "
        f"{safe(vuelo['origen'])} → {safe(vuelo['destino'])}\n"
        f"📅 {safe(vuelo['fecha_vuelo'])}\n"
        f"💰 *Ingreso: {formato_mxn(vuelo['monto_cobrado'])}*"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await q.edit_message_text(
        "✅ *Vuelo completado*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo)}\n"
        "─────────────────────────────\n"
        f"💵 Ingreso registrado: *{formato_mxn(vuelo['monto_cobrado'])}*",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  CANCELAR (con confirmación)
# ═════════════════════════════════════════════════════════════════════════════

async def vac_cancelar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
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
    estado = vuelo["estado"]

    # Validar permisos antes de pedir confirmación
    if estado == "cancelado":
        await q.edit_message_text(
            f"⚠️ El vuelo *#{vid}* ya está cancelado.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    if estado in ("pendiente", "en_proceso"):
        if vuelo["creado_por_id"] != user_id:
            await q.edit_message_text(
                "🚫 *No autorizado*\n\n"
                f"Solo *{safe(vuelo['creado_por'])}* (quien creó el vuelo) puede cancelarlo "
                f"mientras esté _{estado}_.",
                parse_mode="Markdown", reply_markup=kb_volver(),
            )
            return ST_MENU
    elif estado == "completado":
        if vuelo["aceptado_por_id"] != user_id:
            await q.edit_message_text(
                "🚫 *No autorizado*\n\n"
                f"Solo *{safe(vuelo['aceptado_por'])}* (quien sacó el vuelo) puede cancelarlo "
                f"después de completado.",
                parse_mode="Markdown", reply_markup=kb_volver(),
            )
            return ST_MENU

    await q.edit_message_text(
        "❓ *Confirmar cancelación*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo, breve=True)}\n"
        "─────────────────────────────\n"
        "_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=kb_confirmar_cancelar(vid),
    )
    return ST_MENU


async def vac_cancelar_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo, error = await db_thread(db.cancelar_vuelo, vid, tg_user.id, nombre)
    if not vuelo:
        await q.edit_message_text(
            f"❌ {error or 'No se pudo cancelar.'}",
            reply_markup=kb_volver(),
        )
        return ST_MENU

    # Notificar a los demás (incluido al que tenía el vuelo si lo había tomado alguien)
    aviso = (
        f"❌ *Vuelo #{vid} cancelado*\n\n"
        f"*{safe(nombre)}* canceló el vuelo:\n"
        f"✈️ {safe(vuelo['aerolinea'])}  ·  "
        f"{safe(vuelo['origen'])} → {safe(vuelo['destino'])}\n"
        f"📅 {safe(vuelo['fecha_vuelo'])}"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await q.edit_message_text(
        "❌ *Vuelo cancelado*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo, breve=True)}",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU
