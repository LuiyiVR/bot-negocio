"""Fondo de inversión: ver saldo, registrar gasto, editar/agregar fondo, eliminar gasto."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from currency import parsear_monto, formato_mxn
from formatters import safe, fmt_fecha_corta, nombre_usuario
from utils import autorizado, rechazar, db_thread, reply_clean, remember_panel
from keyboards import kb_volver, kb_cancelar, kb_fondo
from states import (
    ST_MENU, ST_FONDO_CONCEPTO, ST_FONDO_MONTO,
    ST_FONDO_EDITAR_MTO, ST_FONDO_AGREGAR_MTO,
)


# ═════════════════════════════════════════════════════════════════════════════
#  VER FONDO
# ═════════════════════════════════════════════════════════════════════════════

async def fondo_ver(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    if q:
        await q.answer()
    return await _render_fondo(update, ctx)


async def _render_fondo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    inicial = await db_thread(db.get_inversion_inicial)
    gastado = await db_thread(db.total_gastado_fondo)
    saldo = inicial - gastado
    gastos = await db_thread(db.gastos_fondo)

    pct = (gastado / inicial * 100) if inicial > 0 else 0.0

    lineas = [
        "🏦 *Fondo de Inversión*",
        "─────────────────────────────",
        f"  Inicial:    *{formato_mxn(inicial)}*",
        f"  Gastado:    −{formato_mxn(gastado)}  ({pct:.1f}%)",
        f"  Saldo:      *{formato_mxn(saldo)}*",
    ]

    if gastos:
        lineas.append("\n*Últimos gastos:*")
        for g in gastos[:8]:
            lineas.append(
                f"  • #{g['id']} _{fmt_fecha_corta(g['fecha'])}_  "
                f"{formato_mxn(g['monto'])}  ·  {safe(g['concepto'])}  "
                f"({safe(g['registrado_por'])})"
            )
        if len(gastos) > 8:
            lineas.append(f"  _… y {len(gastos) - 8} más_")

    filas = [
        [InlineKeyboardButton("➕  Registrar Gasto",  callback_data="fondo_gasto")],
        [
            InlineKeyboardButton("✏️  Editar fondo",  callback_data="fondo_editar"),
            InlineKeyboardButton("➕  Agregar fondo", callback_data="fondo_agregar"),
        ],
    ]
    for g in gastos[:5]:
        filas.append([InlineKeyboardButton(
            f"🗑  Eliminar gasto #{g['id']}",
            callback_data=f"fondo_del:{g['id']}",
        )])
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])

    kb = InlineKeyboardMarkup(filas)
    texto = "\n".join(lineas)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            texto, parse_mode="Markdown", reply_markup=kb,
        )
    else:
        msg = await update.message.reply_text(
            texto, parse_mode="Markdown", reply_markup=kb,
        )
        remember_panel(ctx, msg)
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  REGISTRAR GASTO
# ═════════════════════════════════════════════════════════════════════════════

async def fondo_gasto_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    msg = await q.edit_message_text(
        "💸 *Registrar gasto del fondo*\n\n"
        "*Paso 1/2* — ¿En qué se gastó?\n"
        "_Ej: Anuncio Facebook, dominio, herramientas_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_FONDO_CONCEPTO


async def fondo_gasto_concepto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 2 or len(txt) > 100:
        await reply_clean(update, ctx,
            "❌ Concepto inválido (2–100 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_FONDO_CONCEPTO

    ctx.user_data["fondo_concepto"] = txt
    await reply_clean(update, ctx,
        f"💸 *Registrar gasto del fondo*\n\n"
        f"✅ Concepto: {safe(txt)}\n\n"
        f"*Paso 2/2* — ¿Cuánto se gastó? (en MXN)\n"
        f"_Ej: `500` o `1,250.50`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    return ST_FONDO_MONTO


async def fondo_gasto_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = parsear_monto(update.message.text)
    except ValueError as e:
        await reply_clean(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_FONDO_MONTO

    nombre = nombre_usuario(update.effective_user)
    concepto = ctx.user_data.pop("fondo_concepto")
    await db_thread(db.registrar_gasto_fondo, concepto, monto, nombre)

    inicial = await db_thread(db.get_inversion_inicial)
    gastado = await db_thread(db.total_gastado_fondo)
    saldo = inicial - gastado

    await reply_clean(update, ctx,
        f"✅ *Gasto registrado*\n"
        f"─────────────────────────────\n"
        f"📝 {safe(concepto)}\n"
        f"💸 *{formato_mxn(monto)}*\n"
        f"👤 {safe(nombre)}\n"
        f"─────────────────────────────\n"
        f"🏦 Saldo del fondo: *{formato_mxn(saldo)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦  Ver Fondo",        callback_data="fondo_ver")],
            [InlineKeyboardButton("🏠  Menú Principal",   callback_data="menu")],
        ]),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  EDITAR / AGREGAR FONDO
# ═════════════════════════════════════════════════════════════════════════════

async def fondo_editar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    inicial = await db_thread(db.get_inversion_inicial)
    msg = await q.edit_message_text(
        "✏️ *Editar fondo de inversión*\n\n"
        f"Fondo actual: *{formato_mxn(inicial)}*\n\n"
        f"Escribe el nuevo monto total del fondo (MXN):",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_FONDO_EDITAR_MTO


async def fondo_editar_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = parsear_monto(update.message.text)
    except ValueError as e:
        await reply_clean(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_FONDO_EDITAR_MTO

    await db_thread(db.update_inversion_inicial, monto)
    await reply_clean(update, ctx,
        f"✅ *Fondo actualizado*\n\nNuevo total: *{formato_mxn(monto)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦  Ver Fondo",      callback_data="fondo_ver")],
            [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
        ]),
    )
    return ST_MENU


async def fondo_agregar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    inicial = await db_thread(db.get_inversion_inicial)
    msg = await q.edit_message_text(
        "➕ *Agregar al fondo*\n\n"
        f"Fondo actual: *{formato_mxn(inicial)}*\n\n"
        f"¿Cuánto quieres agregar al fondo? (MXN)",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_FONDO_AGREGAR_MTO


async def fondo_agregar_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = parsear_monto(update.message.text)
    except ValueError as e:
        await reply_clean(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_FONDO_AGREGAR_MTO

    await db_thread(db.agregar_a_inversion, monto)
    nuevo_total = await db_thread(db.get_inversion_inicial)

    await reply_clean(update, ctx,
        f"✅ *Fondo aumentado*\n\n"
        f"Agregado: *{formato_mxn(monto)}*\n"
        f"Nuevo total: *{formato_mxn(nuevo_total)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦  Ver Fondo",      callback_data="fondo_ver")],
            [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
        ]),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  ELIMINAR GASTO
# ═════════════════════════════════════════════════════════════════════════════

async def fondo_del_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    gid = int(q.data.split(":")[1])

    g = await db_thread(db.get_gasto_fondo, gid)
    if not g:
        await q.edit_message_text("❌ Gasto no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    await q.edit_message_text(
        f"❓ *Eliminar gasto del fondo*\n"
        f"─────────────────────────────\n"
        f"#{g['id']}  ·  {fmt_fecha_corta(g['fecha'])}\n"
        f"📝 {safe(g['concepto'])}\n"
        f"💸 {formato_mxn(g['monto'])}\n"
        f"👤 {safe(g['registrado_por'])}\n"
        f"─────────────────────────────\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑  Sí, eliminar",  callback_data=f"fondo_del_ok:{gid}")],
            [InlineKeyboardButton("⬅️  No, volver",     callback_data="fondo_ver")],
        ]),
    )
    return ST_MENU


async def fondo_del_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    gid = int(q.data.split(":")[1])
    await db_thread(db.delete_gasto_fondo, gid)
    await q.edit_message_text(
        "✅ *Gasto eliminado*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦  Ver Fondo",      callback_data="fondo_ver")],
            [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
        ]),
    )
    return ST_MENU
