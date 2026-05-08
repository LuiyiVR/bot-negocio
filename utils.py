"""Helpers compartidos por los handlers."""
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

from config import ALLOWED_IDS

logger = logging.getLogger(__name__)


def autorizado(update: Update) -> bool:
    return (update.effective_user.id if update.effective_user else None) in ALLOWED_IDS


async def rechazar(update: Update):
    uid = update.effective_user.id if update.effective_user else "?"
    msg = (
        f"⛔ *Acceso denegado*\n\n"
        f"Tu ID: `{uid}`\n"
        f"Pídele al administrador que te agregue."
    )
    if update.callback_query:
        await update.callback_query.answer("⛔ Sin acceso", show_alert=True)
    elif update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def db_thread(func, *args, **kwargs):
    """Ejecuta una función bloqueante de DB en un thread (no bloquear event loop)."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def reply_clean(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str, **kw):
    """
    Mantiene el chat con un solo panel activo: borra el mensaje del usuario
    y edita el último mensaje del bot. Si no hay panel anterior o falla la edición,
    envía uno nuevo.
    """
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

    last = ctx.user_data.get("_last_msg")
    if last:
        try:
            await update.get_bot().edit_message_text(
                chat_id=last[0], message_id=last[1], text=text, **kw,
            )
            return
        except Exception:
            pass

    if update.message:
        msg = await update.message.reply_text(text, **kw)
        ctx.user_data["_last_msg"] = (msg.chat_id, msg.message_id)


def remember_panel(ctx: ContextTypes.DEFAULT_TYPE, msg):
    if msg:
        ctx.user_data["_last_msg"] = (msg.chat_id, msg.message_id)


async def edit_q(q, text: str, **kwargs):
    """Edita un callback_query, sea su mensaje texto o foto.

    - Si el mensaje original tiene foto, edita el caption.
    - Si es texto, edita el texto.
    """
    if q.message and q.message.photo:
        # edit_message_caption no acepta `text`; usa `caption`.
        return await q.edit_message_caption(caption=text, **kwargs)
    return await q.edit_message_text(text=text, **kwargs)
