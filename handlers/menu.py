"""Menú principal."""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import db
from utils import autorizado, rechazar, db_thread, edit_to_text
from keyboards import kb_menu
from states import ST_MENU


BIENVENIDA = (
    "🏢 *Panel de Control — Vuelos*\n"
    "_Selecciona una opción:_"
)


def _es_dia_de_checkout() -> bool:
    """True si hoy es sábado y aún no se ha cerrado la semana hoy."""
    hoy = datetime.now()
    if hoy.weekday() != 5:  # 5 = sábado
        return False
    ultimo = db.get_ultimo_checkout()
    if not ultimo:
        return True
    inicio_hoy = hoy.strftime("%Y-%m-%d 00:00:00")
    return ultimo < inicio_hoy


async def mostrar_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    pendientes = len(await db_thread(db.vuelos_pendientes))
    en_proc = await db_thread(
        db.vuelos_de_usuario,
        update.effective_user.id,
        ["en_proceso"],
    )
    badges = []
    if pendientes:
        badges.append(f"⏳ {pendientes} pendiente{'s' if pendientes != 1 else ''}")
    if en_proc:
        badges.append(f"🔄 {len(en_proc)} en proceso")
    sub = "\n_" + " · ".join(badges) + "_" if badges else ""

    mostrar_checkout = await db_thread(_es_dia_de_checkout)
    if mostrar_checkout:
        sub += "\n\n🔒 _Hoy es sábado — toca *CHECKOUT* para cerrar la semana._"

    texto = BIENVENIDA + sub
    kb = kb_menu(mostrar_checkout=mostrar_checkout)

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        msg = await edit_to_text(
            q, texto, parse_mode="Markdown", reply_markup=kb,
        )
    else:
        msg = await update.message.reply_text(
            texto, parse_mode="Markdown", reply_markup=kb,
        )

    ctx.user_data.clear()
    if msg:
        ctx.user_data["_last_msg"] = (msg.chat_id, msg.message_id)
    return ST_MENU
