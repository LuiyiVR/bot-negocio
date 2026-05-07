"""Configuración: editar lista de socios."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from formatters import safe
from utils import autorizado, rechazar, db_thread, reply_clean, remember_panel
from keyboards import kb_volver, kb_cancelar
from states import ST_MENU, ST_CONFIG_SOCIOS


async def config_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    socios = await db_thread(db.get_socios)
    inversion = await db_thread(db.get_inversion_inicial)

    texto = (
        "⚙️ *Configuración*\n"
        "─────────────────────────────\n"
        f"👥 Socios ({len(socios)}): {', '.join(safe(s) for s in socios) if socios else '_ninguno_'}\n"
        f"🏦 Fondo inicial: ${inversion:,.2f} MXN\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥  Editar socios",   callback_data="config_socios")],
        [InlineKeyboardButton("🏠  Menú Principal",  callback_data="menu")],
    ])
    await q.edit_message_text(texto, parse_mode="Markdown", reply_markup=kb)
    return ST_MENU


async def config_socios_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    socios = await db_thread(db.get_socios)
    msg = await q.edit_message_text(
        "👥 *Editar Socios*\n\n"
        f"Actuales: *{', '.join(safe(s) for s in socios) if socios else '—'}*\n\n"
        "Escribe la nueva lista separada por comas:\n"
        "_Ej: `LAVR, FEDE, SPAIDER RATA`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_CONFIG_SOCIOS


async def config_socios_guardar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    nombres = [s.strip() for s in txt.split(",") if s.strip()]
    if not nombres or len(nombres) > 10:
        await reply_clean(update, ctx,
            "❌ Lista inválida (1–10 nombres separados por coma). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_CONFIG_SOCIOS

    await db_thread(db.set_socios, nombres)
    await reply_clean(update, ctx,
        f"✅ *Socios actualizados*\n\n"
        f"Nueva lista: *{', '.join(safe(n) for n in nombres)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️  Configuración",   callback_data="config_menu")],
            [InlineKeyboardButton("🏠  Menú Principal",  callback_data="menu")],
        ]),
    )
    return ST_MENU
