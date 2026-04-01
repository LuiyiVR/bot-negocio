"""
Bot de Telegram — Negocio Airbnb / Vuelos / Tours
• Menú 100% con botones inline
• Sistema de pedidos: crear → notificar → aceptar → venta automática
• Acceso restringido a 3 IDs (ALLOWED_IDS en .env)
"""

import io
import os
import asyncio
import logging
from datetime import datetime
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

import database as db
from currency import parsear_monto, formato_mxn
import bin_info

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
_raw = os.getenv("ALLOWED_IDS", "")
ALLOWED_IDS: set[int] = {int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()}

logging.basicConfig(format="%(asctime)s  %(levelname)s  %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
SEP = "─" * 28


def safe(text: str) -> str:
    """Escapa caracteres especiales de Markdown v1 en texto de usuario."""
    for ch in ("_", "*", "[", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


def fmt_gan(monto: float) -> str:
    """Formatea ganancia: siempre positivo, emoji indica dirección."""
    ico = "📈" if monto >= 0 else "📉"
    return f"{ico} {formato_mxn(abs(monto))}"


async def _notificar_socios(bot, sender_id: int, text: str, **kwargs):
    """Envía un mensaje a todos los socios excepto al remitente, en paralelo."""
    async def _send(uid):
        try:
            await bot.send_message(chat_id=uid, text=text, **kwargs)
        except Exception as e:
            logger.warning(f"No se pudo notificar a {uid}: {e}")
    await asyncio.gather(*[_send(uid) for uid in ALLOWED_IDS if uid != sender_id])


async def _reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str, **kw):
    """Borra el mensaje del usuario y edita el último mensaje del bot (chat limpio)."""
    try:
        await update.message.delete()
    except Exception:
        pass
    last = ctx.user_data.get("_last_msg")
    if last:
        try:
            await update.get_bot().edit_message_text(
                chat_id=last[0], message_id=last[1], text=text, **kw
            )
            return
        except Exception:
            pass
    msg = await update.message.reply_text(text, **kw)
    ctx.user_data["_last_msg"] = (msg.chat_id, msg.message_id)


# ── Estados ───────────────────────────────────────────────────────────────────
(
    ST_MENU,
    # Nueva venta manual
    ST_VT_SOCIO, ST_VT_TARJETA, ST_VT_DESC, ST_VT_COBRADO, ST_VT_GASTADO,
    # Mis ventas
    ST_MV_SOCIO,
    # Resumen
    ST_RES_MES,
    # Inversión
    ST_INV_CONCEPTO, ST_INV_MONTO,
    # Socios
    ST_SOC_NUEVO,
    # Pedidos — crear
    ST_PED_TIPO, ST_PED_LINK, ST_PED_PEDESC, ST_PED_COSTO, ST_PED_COBRADOP,
    # Pedidos — aceptar (reservar)
    ST_AC_CONFIRMAR,
    # Pedidos — completar (llenar tarjeta una vez hecha la compra)
    ST_COMP_TARJETA,
    # Inversión — editar monto inicial
    ST_INV_EDITAR_MONTO,
    ST_INV_AGREGAR_MONTO,
    # Reportes descargables — otro mes
    ST_REP_OTRO_MES,
    # Bodega de BINs
    ST_BIN_NUM,
    ST_BIN_TIENDA,
    ST_BIN_NUEVA_TIENDA,
    ST_BIN_BUSCAR,
) = range(25)

TIPOS_PEDIDO = ["✈️ Vuelo", "🏠 Airbnb", "🗺️ Tour", "🎡 Otro"]


# ══════════════════════════════════════════════════════════════════════════════
#  ACCESO
# ══════════════════════════════════════════════════════════════════════════════

def autorizado(update: Update) -> bool:
    return (update.effective_user.id if update.effective_user else None) in ALLOWED_IDS


async def rechazar(update: Update):
    uid = update.effective_user.id if update.effective_user else "?"
    msg = f"⛔ *Acceso denegado*\n\nTu ID: `{uid}`\nPídele al admin que te agregue."
    if update.callback_query:
        await update.callback_query.answer("⛔ Sin acceso", show_alert=True)
    elif update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  TECLADOS
# ══════════════════════════════════════════════════════════════════════════════

def kb_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒  Nueva Venta",           callback_data="nueva_venta")],
        [InlineKeyboardButton("📦  Pedidos",               callback_data="pedidos_menu")],
        [
            InlineKeyboardButton("📋  Mis Ventas",         callback_data="mis_ventas"),
            InlineKeyboardButton("👥  Todas las Ventas",   callback_data="todas_ventas"),
        ],
        [
            InlineKeyboardButton("📅  Resumen del Mes",    callback_data="resumen_actual"),
            InlineKeyboardButton("🗓  Otro Mes",           callback_data="resumen_otro"),
        ],
        [
            InlineKeyboardButton("📥  Descargar Reporte",  callback_data="reporte_menu"),
        ],
        [
            InlineKeyboardButton("🏦  Ver Inversión",      callback_data="ver_inversion"),
            InlineKeyboardButton("💸  Gasto Inversión",    callback_data="gasto_inversion"),
        ],
        [InlineKeyboardButton("🗂  Bodega de BINs",        callback_data="bin_menu")],
    ])


def kb_pedidos_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝  Crear Pedido",          callback_data="ped_crear")],
        [
            InlineKeyboardButton("⏳  Pendientes",         callback_data="ped_pendientes"),
            InlineKeyboardButton("✅  Mis Pedidos",        callback_data="ped_mios"),
        ],
        [InlineKeyboardButton("🏠  Menú Principal",        callback_data="menu")],
    ])


def kb_tipos_pedido():
    filas = [[InlineKeyboardButton(t, callback_data=f"ped_tipo:{t}")] for t in TIPOS_PEDIDO]
    filas.append([InlineKeyboardButton("❌  Cancelar", callback_data="menu")])
    return InlineKeyboardMarkup(filas)


def kb_socios(prefijo: str):
    socios = db.get_socios()
    filas = [[InlineKeyboardButton(f"👤 {s}", callback_data=f"{prefijo}:{s}")] for s in socios]
    filas.append([InlineKeyboardButton("❌  Cancelar", callback_data="menu")])
    return InlineKeyboardMarkup(filas)


def kb_saltar_cancelar(callback_saltar: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭  Saltar este campo", callback_data=callback_saltar)],
        [InlineKeyboardButton("❌  Cancelar",          callback_data="menu")],
    ])


def kb_cancelar():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌  Cancelar", callback_data="menu")]])


def kb_volver():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")]])


def kb_volver_pedidos():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦  Volver a Pedidos", callback_data="pedidos_menu")],
        [InlineKeyboardButton("🏠  Menú Principal",   callback_data="menu")],
    ])


def kb_volver_bins():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂  Bodega de BINs",   callback_data="bin_menu")],
        [InlineKeyboardButton("🏠  Menú Principal",   callback_data="menu")],
    ])


def kb_tiendas_bin():
    tiendas = db.get_tiendas_bins()
    filas = [
        [InlineKeyboardButton(t["nombre"], callback_data=f"bin_tienda:{t['nombre']}")]
        for t in tiendas
    ]
    filas.append([InlineKeyboardButton("➕  Nueva tienda", callback_data="bin_nueva_tienda")])
    filas.append([InlineKeyboardButton("❌  Cancelar",     callback_data="menu")])
    return InlineKeyboardMarkup(filas)


# ══════════════════════════════════════════════════════════════════════════════
#  MENÚ PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

BIENVENIDA = "👋 *Panel de Control — Negocio*\n\nSelecciona una opción:"


async def mostrar_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(BIENVENIDA, parse_mode="Markdown", reply_markup=kb_menu())
    else:
        await update.message.reply_text(BIENVENIDA, parse_mode="Markdown", reply_markup=kb_menu())

    ctx.user_data.clear()
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  MENÚ DE PEDIDOS
# ══════════════════════════════════════════════════════════════════════════════

async def pedidos_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    pendientes = len(db.pedidos_pendientes())
    badge = f" ({pendientes} pendiente{'s' if pendientes != 1 else ''})" if pendientes else ""

    await q.edit_message_text(
        f"📦 *Pedidos*{badge}\n\n¿Qué deseas hacer?",
        parse_mode="Markdown",
        reply_markup=kb_pedidos_menu(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  CREAR PEDIDO — flujo paso a paso
# ══════════════════════════════════════════════════════════════════════════════

async def ped_crear_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📝 *Nuevo Pedido*\n\n*Paso 1 / 5* — ¿Qué tipo de pedido es?",
        parse_mode="Markdown",
        reply_markup=kb_tipos_pedido(),
    )
    return ST_PED_TIPO


async def ped_tipo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    tipo = q.data.split(":", 1)[1]
    ctx.user_data["ped_tipo"] = tipo

    await q.edit_message_text(
        f"📝 *Nuevo Pedido — {tipo}*\n\n"
        f"✅ Tipo: {tipo}\n\n"
        f"*Paso 2 / 5* — Pega el *link* del servicio\n"
        f"_Si no tienes link, presiona Saltar_",
        parse_mode="Markdown",
        reply_markup=kb_saltar_cancelar("ped_skip_link"),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_PED_LINK


async def ped_link_saltar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["ped_link"] = ""
    await q.edit_message_text(
        f"📝 *Nuevo Pedido — {ctx.user_data['ped_tipo']}*\n\n"
        f"✅ Tipo: {ctx.user_data['ped_tipo']}\n"
        f"✅ Link: —\n\n"
        f"*Paso 3 / 5* — Escribe una *descripción* breve del pedido\n"
        f"_Ej: Airbnb CDMX 3 noches del 5 al 8 abril_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_PED_PEDESC


async def ped_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["ped_link"] = update.message.text.strip()
    ud = ctx.user_data
    await _reply(update, ctx,
        f"📝 *Nuevo Pedido — {ud['ped_tipo']}*\n\n"
        f"✅ Tipo: {ud['ped_tipo']}\n"
        f"✅ Link: {safe(ud['ped_link'])}\n\n"
        f"*Paso 3 / 5* — Escribe una *descripción* breve\n"
        f"_Ej: Airbnb CDMX 3 noches del 5 al 8 abril_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_PED_PEDESC


async def ped_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["ped_desc"] = update.message.text.strip()
    ud = ctx.user_data
    await _reply(update, ctx,
        f"📝 *Nuevo Pedido — {ud['ped_tipo']}*\n\n"
        f"✅ Tipo: {ud['ped_tipo']}\n"
        f"✅ Descripción: {safe(ud['ped_desc'])}\n\n"
        f"*Paso 4 / 5* — ¿Cuál es el *total de la compra*?\n"
        f"_(Lo que marca el servicio / lo que se va a cobrar)_\n"
        f"_Ej: `2000 MX` o `120 USD`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_PED_COSTO


async def ped_costo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto, moneda, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx,
            f"❌ {e}\n_Usa `2000 MX` o `120 USD`_",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_PED_COSTO

    ctx.user_data["ped_costo"] = (monto, moneda, mxn, tc)
    ud = ctx.user_data
    txt_tc = f" _(TC: ${tc:.2f})_" if moneda == "USD" else ""

    await _reply(update, ctx,
        f"📝 *Nuevo Pedido — {ud['ped_tipo']}*\n\n"
        f"✅ Descripción: {safe(ud['ped_desc'])}\n"
        f"✅ Total de compra: *{formato_mxn(mxn)}*{txt_tc}\n\n"
        f"*Paso 5 / 5* — ¿Cuánto le *cobras al cliente*?\n"
        f"_Ej: `2500 MX` o `150 USD`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_PED_COBRADOP


async def ped_cobrado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto, moneda, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx,
            f"❌ {e}\n_Usa `2500 MX` o `150 USD`_",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_PED_COBRADOP

    # Leer TODOS los datos antes de tocar user_data
    c_monto, c_moneda, c_mxn, c_tc = ctx.user_data["ped_costo"]
    p_monto, p_moneda, p_mxn, p_tc = (monto, moneda, mxn, tc)
    ped_tipo  = ctx.user_data["ped_tipo"]
    ped_desc  = ctx.user_data["ped_desc"]
    ped_link  = ctx.user_data.get("ped_link", "")
    tc_final  = c_tc if c_moneda == "USD" else p_tc
    ganancia_est = p_mxn - c_mxn

    tg_user = update.effective_user
    nombre_usuario = tg_user.first_name or tg_user.username or str(tg_user.id)

    pedido_id = db.crear_pedido(
        creado_por=nombre_usuario,
        tipo=ped_tipo,
        link=ped_link,
        descripcion=ped_desc,
        monto_compra=c_monto, moneda_compra=c_moneda, monto_compra_mxn=c_mxn,
        monto_cobrado=p_monto, moneda_cobrado=p_moneda, monto_cobrado_mxn=p_mxn,
        tipo_cambio=tc_final,
    )
    ctx.user_data.clear()  # seguro limpiar aquí, ya no usamos user_data

    # ── Notificar a los demás usuarios ────────────────────────────────────────
    txt_notif = _texto_pedido_notif(db.get_pedido(pedido_id))
    kb_notif = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅  Aceptar pedido #{pedido_id}", callback_data=f"aceptar_ped:{pedido_id}")
    ]])
    await _notificar_socios(
        update.get_bot(), tg_user.id,
        f"🔔 *Nuevo Pedido Disponible*\n\n{txt_notif}",
        parse_mode="Markdown", reply_markup=kb_notif,
    )

    txt_tc = f"\n_TC: ${tc_final:.2f} MXN/USD_" if tc_final != 1.0 else ""

    await _reply(update, ctx,
        f"✅ *¡Pedido #{pedido_id} creado!*\n"
        f"{SEP}\n"
        f"{ped_tipo} — {safe(ped_desc)}\n"
        f"💸 Total de compra: {formato_mxn(c_mxn)}\n"
        f"💰 Cobrado al cliente: {formato_mxn(p_mxn)}\n"
        f"Ganancia estimada: *{fmt_gan(ganancia_est)}*\n"
        f"{txt_tc}\n\n"
        f"📲 _Se notificó a los demás socios._",
        parse_mode="Markdown",
        reply_markup=kb_volver_pedidos(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  VER PEDIDOS PENDIENTES
# ══════════════════════════════════════════════════════════════════════════════

async def ped_ver_pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    pedidos = db.pedidos_pendientes()

    if not pedidos:
        await q.edit_message_text(
            "⏳ No hay pedidos pendientes en este momento.",
            reply_markup=kb_volver_pedidos(),
        )
        return ST_MENU

    lineas = [f"⏳ *Pedidos Pendientes* ({len(pedidos)})\n{SEP}"]
    filas_btn = []
    for p in pedidos:
        gan = p["monto_cobrado_mxn"] - p["monto_compra_mxn"]
        lineas.append(
            f"*#{p['id']}* {p['tipo']} — {safe(p['descripcion'])}\n"
            f"   💸 Total de compra: {formato_mxn(p['monto_compra_mxn'])}  "
            f"💰 Cobrado: {formato_mxn(p['monto_cobrado_mxn'])}  "
            f"*{fmt_gan(gan)}*\n"
            f"   👤 {safe(p['creado_por'])}  🗓 {p['fecha_creacion'][:10]}"
        )
        filas_btn.append([
            InlineKeyboardButton(
                f"✅ Aceptar #{p['id']} — {p['descripcion'][:22]}",
                callback_data=f"aceptar_ped:{p['id']}"
            ),
        ])

    filas_btn.append([InlineKeyboardButton("📦 Volver a Pedidos", callback_data="pedidos_menu")])
    filas_btn.append([InlineKeyboardButton("🏠 Menú Principal",   callback_data="menu")])

    await q.edit_message_text(
        "\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas_btn),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  MIS PEDIDOS (aceptados por este usuario)
# ══════════════════════════════════════════════════════════════════════════════

async def ped_mios(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    tg_user = update.effective_user
    nombre = tg_user.first_name or tg_user.username or str(tg_user.id)
    pedidos = db.pedidos_de_usuario(nombre)

    if not pedidos:
        await q.edit_message_text(
            f"📭 *{nombre}*, no tienes pedidos aceptados aún.",
            parse_mode="Markdown",
            reply_markup=kb_volver_pedidos(),
        )
        return ST_MENU

    lineas = [f"📋 *Mis Pedidos — {nombre}* ({len(pedidos)})\n{SEP}"]
    filas_btn = []

    for p in pedidos:
        gan = p["monto_cobrado_mxn"] - p["monto_compra_mxn"]
        if p["estado"] == "en_proceso":
            estado_ico = "🔄"
            fecha_txt = f"Aceptado: {p['fecha_completado'][:10]}"
            tarjeta_txt = "Tarjeta pendiente"
        else:
            estado_ico = "✅"
            fecha_txt = f"Completado: {p['fecha_completado'][:10]}"
            tarjeta_txt = f"****{p['tarjeta'][-4:]}" if p["tarjeta"] else "—"

        lineas.append(
            f"{estado_ico} *#{p['id']}* {p['tipo']} — {safe(p['descripcion'])}\n"
            f"   💳 {tarjeta_txt}  |  {fecha_txt}\n"
            f"   💸 {formato_mxn(p['monto_compra_mxn'])}  💰 {formato_mxn(p['monto_cobrado_mxn'])}  *{fmt_gan(gan)}*"
        )

        # Botones según estado — sin duplicados
        if p["estado"] == "en_proceso":
            filas_btn.append([
                InlineKeyboardButton("✔️ Completar",    callback_data=f"completar_ped:{p['id']}"),
                InlineKeyboardButton("🔓 Soltar",       callback_data=f"soltar_ped:{p['id']}"),
            ])
        else:
            # completado → solo eliminar
            filas_btn.append([
                InlineKeyboardButton(f"🗑 Eliminar #{p['id']}", callback_data=f"del_pedido:{p['id']}"),
            ])

    filas_btn.append([InlineKeyboardButton("📦 Volver a Pedidos", callback_data="pedidos_menu")])
    filas_btn.append([InlineKeyboardButton("🏠 Menú Principal",   callback_data="menu")])

    await q.edit_message_text(
        "\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas_btn),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  ACEPTAR PEDIDO — solo reserva, sin pedir tarjeta todavía
# ══════════════════════════════════════════════════════════════════════════════

async def aceptar_ped_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    pedido = db.get_pedido(pedido_id)

    if not pedido:
        await q.edit_message_text("❌ Pedido no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    if pedido["estado"] != "pendiente":
        estados = {"en_proceso": "ya fue tomado por otro socio", "completado": "ya está completado", "cancelado": "fue cancelado"}
        msg = estados.get(pedido["estado"], pedido["estado"])
        await q.edit_message_text(
            f"⚠️ El pedido *#{pedido_id}* {msg}.",
            parse_mode="Markdown",
            reply_markup=kb_volver_pedidos(),
        )
        return ST_MENU

    ctx.user_data["ac_pedido_id"] = pedido_id
    gan = pedido["monto_cobrado_mxn"] - pedido["monto_compra_mxn"]
    link_txt = f"\n🔗 {pedido['link']}" if pedido["link"] else ""

    kb_confirm = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Sí, lo acepto", callback_data=f"ac_confirmar:{pedido_id}")],
        [InlineKeyboardButton("❌  Cancelar",       callback_data="pedidos_menu")],
    ])

    await q.edit_message_text(
        f"📦 *Pedido #{pedido_id}*\n"
        f"{SEP}\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}{safe(link_txt)}\n\n"
        f"💸 Total de compra: {formato_mxn(pedido['monto_compra_mxn'])}\n"
        f"💰 Cobrado al cliente: {formato_mxn(pedido['monto_cobrado_mxn'])}\n"
        f"Ganancia estimada: *{fmt_gan(gan)}*\n"
        f"👤 Creado por: {safe(pedido['creado_por'])}\n"
        f"{SEP}\n"
        f"¿Confirmas que *tú* vas a trabajar este pedido?",
        parse_mode="Markdown",
        reply_markup=kb_confirm,
    )
    return ST_AC_CONFIRMAR


async def aceptar_ped_confirmar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    tg_user = update.effective_user
    nombre = tg_user.first_name or tg_user.username or str(tg_user.id)

    pedido = db.aceptar_pedido(pedido_id, nombre)
    if not pedido:
        await q.edit_message_text(
            "⚠️ Otro socio acaba de tomar este pedido. Ya no está disponible.",
            reply_markup=kb_volver_pedidos(),
        )
        ctx.user_data.clear()
        return ST_MENU

    gan = pedido["monto_cobrado_mxn"] - pedido["monto_compra_mxn"]

    # Notificar a los demás
    await _notificar_socios(
        update.get_bot(), tg_user.id,
        f"🔄 *Pedido #{pedido_id} en proceso*\n\n"
        f"*{nombre}* aceptó el pedido:\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}\n"
        f"📈 Ganancia estimada: *{formato_mxn(gan)}*",
        parse_mode="Markdown",
    )

    await q.edit_message_text(
        f"🔄 *Pedido #{pedido_id} reservado para ti*\n"
        f"{SEP}\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}\n"
        f"💸 Total de compra: {formato_mxn(pedido['monto_compra_mxn'])}\n"
        f"💰 Cobras: {formato_mxn(pedido['monto_cobrado_mxn'])}\n"
        f"Ganancia: *{fmt_gan(gan)}*\n"
        f"{SEP}\n"
        f"_Tómate el tiempo que necesites para realizar la compra._\n"
        f"_Cuando lo hayas completado, ve a_ *📦 Pedidos → ✅ Mis Pedidos*\n"
        f"_y marca el pedido como terminado._",
        parse_mode="Markdown",
        reply_markup=kb_volver_pedidos(),
    )
    ctx.user_data.clear()
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  COMPLETAR PEDIDO — cuando ya se hizo la compra, llena tarjeta y cierra
# ══════════════════════════════════════════════════════════════════════════════

async def completar_ped_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    pedido = db.get_pedido(pedido_id)
    gan = pedido["monto_cobrado_mxn"] - pedido["monto_compra_mxn"]
    link_txt = f"\n🔗 {pedido['link']}" if pedido["link"] else ""

    ctx.user_data["comp_pedido_id"] = pedido_id

    await q.edit_message_text(
        f"✔️ *Completar Pedido #{pedido_id}*\n"
        f"{SEP}\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}{safe(link_txt)}\n"
        f"💸 Total de compra: {formato_mxn(pedido['monto_compra_mxn'])}\n"
        f"💰 Cobrado: {formato_mxn(pedido['monto_cobrado_mxn'])}\n"
        f"Ganancia: *{fmt_gan(gan)}*\n"
        f"{SEP}\n"
        f"Escribe los *16 dígitos* de la tarjeta con la que hiciste la compra:",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_COMP_TARJETA


async def completar_ped_tarjeta(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    tarjeta = update.message.text.strip().replace(" ", "").replace("-", "")
    if not tarjeta.isdigit() or len(tarjeta) != 16:
        await _reply(update, ctx,
            "❌ Deben ser exactamente *16 dígitos*. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_COMP_TARJETA

    pedido_id = ctx.user_data["comp_pedido_id"]
    tg_user = update.effective_user
    nombre = tg_user.first_name or tg_user.username or str(tg_user.id)

    pedido = db.completar_pedido(pedido_id, nombre, tarjeta)
    if not pedido:
        await _reply(update, ctx,
            "⚠️ No se pudo completar. Verifica que este pedido aún te pertenece.",
            reply_markup=kb_volver_pedidos(),
        )
        ctx.user_data.clear()
        return ST_MENU

    gan = pedido["monto_cobrado_mxn"] - pedido["monto_compra_mxn"]
    txt_tc = f"\n_TC: ${pedido['tipo_cambio']:.2f}_" if pedido["tipo_cambio"] != 1.0 else ""

    # Notificar a los demás que quedó cerrado
    await _notificar_socios(
        update.get_bot(), tg_user.id,
        f"✅ *Pedido #{pedido_id} completado*\n\n"
        f"*{nombre}* cerró el pedido:\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}\n"
        f"💳 Tarjeta: `****{tarjeta[-4:]}`\n"
        f"Ganancia registrada: *{fmt_gan(gan)}*",
        parse_mode="Markdown",
    )

    await _reply(update, ctx,
        f"🎉 *¡Pedido #{pedido_id} completado!*\n"
        f"{SEP}\n"
        f"👤 *{nombre}*\n"
        f"💳 Tarjeta: `****{tarjeta[-4:]}`\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}\n"
        f"💸 Total de compra: {formato_mxn(pedido['monto_compra_mxn'])}\n"
        f"💰 Cobrado: {formato_mxn(pedido['monto_cobrado_mxn'])}\n"
        f"*Ganancia: {fmt_gan(gan)}*{txt_tc}\n\n"
        f"_Venta registrada automáticamente._",
        parse_mode="Markdown",
        reply_markup=kb_volver_pedidos(),
    )
    ctx.user_data.clear()
    return ST_MENU


def _texto_pedido_notif(p) -> str:
    gan = p["monto_cobrado_mxn"] - p["monto_compra_mxn"]
    link_txt = f"\n🔗 {safe(p['link'])}" if p["link"] else ""
    return (
        f"*#{p['id']}* {p['tipo']} — {safe(p['descripcion'])}{link_txt}\n"
        f"💸 Total de compra: {formato_mxn(p["monto_compra_mxn"])}\n"
        f"💰 Cobrado al cliente: {formato_mxn(p['monto_cobrado_mxn'])}\n"
        f"Ganancia: *{fmt_gan(gan)}*\n"
        f"👤 Creado por: {safe(p['creado_por'])}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  NUEVA VENTA MANUAL
# ══════════════════════════════════════════════════════════════════════════════

async def nv_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🛒 *Nueva Venta*\n\n*Paso 1 / 5* — ¿Quién realizó esta venta?",
        parse_mode="Markdown",
        reply_markup=kb_socios("vt_socio"),
    )
    return ST_VT_SOCIO


async def nv_socio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["vt_usuario"] = q.data.split(":", 1)[1]
    await q.edit_message_text(
        f"🛒 *Nueva Venta*\n\n✅ Socio: *{ctx.user_data['vt_usuario']}*\n\n"
        f"*Paso 2 / 5* — Escribe los *16 dígitos* de la tarjeta:",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_VT_TARJETA


async def nv_tarjeta(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    tarjeta = update.message.text.strip().replace(" ", "").replace("-", "")
    if not tarjeta.isdigit() or len(tarjeta) != 16:
        await _reply(update, ctx,
            "❌ Deben ser exactamente *16 dígitos*. Intenta de nuevo:",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_VT_TARJETA
    ctx.user_data["vt_tarjeta"] = tarjeta
    await _reply(update, ctx,
        f"🛒 *Nueva Venta*\n\n✅ Socio: *{ctx.user_data['vt_usuario']}*\n"
        f"✅ Tarjeta: `****{tarjeta[-4:]}`\n\n"
        f"*Paso 3 / 5* — ¿Qué se vendió?\n"
        f"_Ej: Airbnb CDMX 3 noches, Vuelo GDL-CUN..._",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    return ST_VT_DESC


async def nv_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["vt_desc"] = update.message.text.strip()
    ud = ctx.user_data
    await _reply(update, ctx,
        f"🛒 *Nueva Venta*\n\n✅ Socio: *{ud['vt_usuario']}*\n"
        f"✅ Tarjeta: `****{ud['vt_tarjeta'][-4:]}`\n"
        f"✅ Concepto: {safe(ud['vt_desc'])}\n\n"
        f"*Paso 4 / 5* — ¿Cuánto le *cobró al cliente*?\n"
        f"_Ej: `2500 MX` o `150 USD`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    return ST_VT_COBRADO


async def nv_cobrado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto, moneda, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_VT_COBRADO
    ctx.user_data["vt_cobrado"] = (monto, moneda, mxn, tc)
    ud = ctx.user_data
    txt_tc = f" _(TC: ${tc:.2f})_" if moneda == "USD" else ""
    await _reply(update, ctx,
        f"🛒 *Nueva Venta*\n\n✅ Cobrado: *{formato_mxn(mxn)}*{txt_tc}\n\n"
        f"*Paso 5 / 5* — ¿Cuánto *gastaste tú* para conseguirlo?\n"
        f"_Ej: `2000 MX` o `120 USD`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    return ST_VT_GASTADO


async def nv_gastado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto, moneda, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_VT_GASTADO

    ctx.user_data["vt_gastado"] = (monto, moneda, mxn, tc)
    ud = ctx.user_data
    c_monto, c_moneda, c_mxn, c_tc = ud["vt_cobrado"]
    g_monto, g_moneda, g_mxn, g_tc = ud["vt_gastado"]
    tc_final = c_tc if c_moneda == "USD" else g_tc

    db.registrar_venta(
        usuario=ud["vt_usuario"], tarjeta=ud["vt_tarjeta"],
        descripcion=ud["vt_desc"],
        monto_cobrado=c_monto, moneda_cobrado=c_moneda, monto_cobrado_mxn=c_mxn,
        monto_gastado=g_monto, moneda_gastado=g_moneda, monto_gastado_mxn=g_mxn,
        tipo_cambio=tc_final,
    )

    ganancia = c_mxn - g_mxn
    txt_tc = f"\n_TC: ${tc_final:.2f}_" if tc_final != 1.0 else ""
    await _reply(update, ctx,
        f"✅ *¡Venta registrada!*\n{SEP}\n"
        f"👤 {ud['vt_usuario']}  💳 `****{ud['vt_tarjeta'][-4:]}`\n"
        f"📦 {safe(ud['vt_desc'])}\n"
        f"💰 Cobrado: {formato_mxn(c_mxn)}  💸 Gastado: {formato_mxn(g_mxn)}\n"
        f"*Ganancia: {fmt_gan(ganancia)}*{txt_tc}",
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    ctx.user_data.clear()
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  MIS VENTAS
# ══════════════════════════════════════════════════════════════════════════════

async def mv_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📋 *Mis Ventas*\n\n¿De qué socio?",
        parse_mode="Markdown",
        reply_markup=kb_socios("mv_socio"),
    )
    return ST_MV_SOCIO


async def mv_mostrar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    usuario = q.data.split(":", 1)[1]
    ventas = db.ventas_por_usuario(usuario)

    if not ventas:
        await q.edit_message_text(
            f"📭 *{usuario}* no tiene ventas aún.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    total_c = sum(v["monto_cobrado_mxn"] for v in ventas)
    total_g = sum(v["monto_gastado_mxn"] for v in ventas)
    lineas = [f"📋 *{usuario}* — {len(ventas)} venta(s)\n{SEP}"]
    filas_btn = []
    for v in ventas:
        gan = v["monto_cobrado_mxn"] - v["monto_gastado_mxn"]
        lineas.append(
            f"*#{v['id']}*  🗓 `{v['fecha'][:10]}`  💳 `****{v['tarjeta'][-4:]}`\n"
            f"   {safe(v['descripcion'])}\n"
            f"   💰 {formato_mxn(v['monto_cobrado_mxn'])}  💸 {formato_mxn(v['monto_gastado_mxn'])}  *{fmt_gan(gan)}*"
        )
        filas_btn.append([InlineKeyboardButton(
            f"🗑  Eliminar #{v['id']} — {v['descripcion'][:25]}",
            callback_data=f"del_venta:{v['id']}"
        )])
    lineas.append(f"\n{SEP}\n*Ganancia total: {fmt_gan(total_c - total_g)}*")
    filas_btn.append([InlineKeyboardButton("🏠 Menú Principal", callback_data="menu")])

    await q.edit_message_text(
        "\n".join(lineas), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas_btn),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  TODAS LAS VENTAS
# ══════════════════════════════════════════════════════════════════════════════

async def todas_ventas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    ventas = db.todas_las_ventas()

    if not ventas:
        await q.edit_message_text("📭 No hay ventas aún.", reply_markup=kb_volver())
        return ST_MENU

    por_socio: dict = defaultdict(list)
    for v in ventas:
        por_socio[v["usuario"]].append(v)

    gran_c = sum(v["monto_cobrado_mxn"] for v in ventas)
    gran_g = sum(v["monto_gastado_mxn"] for v in ventas)
    lineas = [f"👥 *Todas las Ventas* — {len(ventas)} total\n{SEP}"]
    for socio, svs in por_socio.items():
        tc = sum(v["monto_cobrado_mxn"] for v in svs)
        tg = sum(v["monto_gastado_mxn"] for v in svs)
        lineas.append(
            f"👤 *{socio}* — {len(svs)} venta(s)\n"
            f"   💰 {formato_mxn(tc)}  💸 {formato_mxn(tg)}  *{fmt_gan(tc - tg)}*"
        )
    lineas.append(
        f"\n{SEP}\n🏦 *TOTAL*\n"
        f"💰 {formato_mxn(gran_c)}  💸 {formato_mxn(gran_g)}\n"
        f"*{fmt_gan(gran_c - gran_g)}*"
    )
    await q.edit_message_text(
        "\n".join(lineas), parse_mode="Markdown", reply_markup=kb_volver(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  RESUMEN
# ══════════════════════════════════════════════════════════════════════════════

async def resumen_actual(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    hoy = datetime.now()
    await q.edit_message_text(
        _calcular_resumen(hoy.year, hoy.month),
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    return ST_MENU


async def resumen_otro_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🗓 *Resumen por Mes*\n\nEscribe el mes en formato *MM/AAAA*\n_Ej: `03/2026`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_RES_MES


async def resumen_mes_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        partes = update.message.text.strip().split("/")
        mes, anio = int(partes[0]), int(partes[1])
        if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
            raise ValueError
    except (ValueError, IndexError):
        await _reply(update, ctx,
            "❌ Formato incorrecto. Usa *MM/AAAA*\n_Ej: `03/2026`_",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_RES_MES

    await _reply(update, ctx,
        _calcular_resumen(anio, mes),
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    return ST_MENU


def _calcular_resumen(anio: int, mes: int) -> str:
    ventas = db.ventas_mes(anio, mes)
    inv_ini = float(db.get_config("inversion_inicial") or 15000)
    socios = db.get_socios()
    total_inv = db.total_gastado_inversion()
    nombre_mes = f"{mes:02d}/{anio}"

    if not ventas:
        return f"📭 No hay ventas en *{nombre_mes}*."

    total_c = sum(v["monto_cobrado_mxn"] for v in ventas)
    total_g = sum(v["monto_gastado_mxn"] for v in ventas)
    ganancia = total_c - total_g
    por_socio_gan = ganancia / len(socios) if socios else ganancia

    por_socio: dict = defaultdict(list)
    for v in ventas:
        por_socio[v["usuario"]].append(v)

    lineas = [f"📅 *Resumen — {nombre_mes}*\n{SEP}"]
    for s in socios:
        svs = por_socio.get(s, [])
        c = sum(v["monto_cobrado_mxn"] for v in svs)
        g = sum(v["monto_gastado_mxn"] for v in svs)
        lineas.append(f"👤 *{s}* — {len(svs)} venta(s) | {fmt_gan(c - g)}")

    lineas += [
        f"\n{SEP}",
        f"💰 Total cobrado: {formato_mxn(total_c)}",
        f"💸 Total gastado: {formato_mxn(total_g)}",
        f"*Ganancia del mes: {fmt_gan(ganancia)}*",
        f"\n{SEP}",
        f"🏦 Inversión inicial: {formato_mxn(inv_ini)}",
        f"💼 Gastos acumulados: {formato_mxn(total_inv)}",
        f"💵 Saldo inversión: *{formato_mxn(max(0, inv_ini - total_inv))}*",
        f"\n{SEP}",
        f"🤝 *Reparto ({len(socios)} socios):*",
    ]
    for s in socios:
        lineas.append(f"   👤 {s} → *{formato_mxn(por_socio_gan)}*")
    return "\n".join(lineas)


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTES DESCARGABLES
# ══════════════════════════════════════════════════════════════════════════════

def _csv_bytes(ventas, titulo: str) -> bytes:
    """Genera un CSV en memoria con las ventas dadas."""
    buf = io.StringIO()
    buf.write(f"# {titulo}\n")
    buf.write("ID,Fecha,Socio,Tarjeta,Descripcion,Cobrado MXN,Gastado MXN,Ganancia MXN\n")
    for v in ventas:
        gan = v["monto_cobrado_mxn"] - v["monto_gastado_mxn"]
        desc = v["descripcion"].replace('"', "'")
        buf.write(
            f"{v['id']},{v['fecha'][:10]},{v['usuario']},****{v['tarjeta'][-4:]},"
            f"\"{desc}\",{v['monto_cobrado_mxn']:.2f},{v['monto_gastado_mxn']:.2f},{gan:.2f}\n"
        )
    total_c = sum(v["monto_cobrado_mxn"] for v in ventas)
    total_g = sum(v["monto_gastado_mxn"] for v in ventas)
    buf.write(f"\nTOTAL,,,,,{total_c:.2f},{total_g:.2f},{total_c - total_g:.2f}\n")
    return buf.getvalue().encode("utf-8")


async def reporte_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Hoy",         callback_data="rep_hoy"),
            InlineKeyboardButton("📆 Esta Semana", callback_data="rep_semana"),
        ],
        [
            InlineKeyboardButton("🗓 Este Mes",    callback_data="rep_mes_actual"),
            InlineKeyboardButton("📁 Otro Mes",    callback_data="rep_otro_mes"),
        ],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu")],
    ])
    await q.edit_message_text(
        "📥 *Descargar Reporte*\n\n¿Qué periodo quieres descargar?",
        parse_mode="Markdown", reply_markup=kb,
    )
    return ST_MENU


async def rep_hoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer("Generando reporte...")
    ventas = db.ventas_hoy()
    hoy = datetime.now().strftime("%Y-%m-%d")
    titulo = f"Reporte Diario — {hoy}"
    if not ventas:
        await q.edit_message_text(f"📭 No hay ventas hoy ({hoy}).", reply_markup=kb_volver())
        return ST_MENU
    csv_data = _csv_bytes(ventas, titulo)
    await update.get_bot().send_document(
        chat_id=q.message.chat_id,
        document=io.BytesIO(csv_data),
        filename=f"reporte_diario_{hoy}.csv",
        caption=f"📅 *{titulo}* — {len(ventas)} venta(s)",
        parse_mode="Markdown",
    )
    return ST_MENU


async def rep_semana(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer("Generando reporte...")
    ventas = db.ventas_semana()
    hoy = datetime.now().strftime("%Y-%m-%d")
    titulo = f"Reporte Semanal — hasta {hoy}"
    if not ventas:
        await q.edit_message_text("📭 No hay ventas en los últimos 7 días.", reply_markup=kb_volver())
        return ST_MENU
    csv_data = _csv_bytes(ventas, titulo)
    await update.get_bot().send_document(
        chat_id=q.message.chat_id,
        document=io.BytesIO(csv_data),
        filename=f"reporte_semanal_{hoy}.csv",
        caption=f"📆 *{titulo}* — {len(ventas)} venta(s)",
        parse_mode="Markdown",
    )
    return ST_MENU


async def rep_mes_actual(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer("Generando reporte...")
    now = datetime.now()
    ventas = db.ventas_mes(now.year, now.month)
    nombre_mes = now.strftime("%m-%Y")
    titulo = f"Reporte Mensual — {nombre_mes}"
    if not ventas:
        await q.edit_message_text(f"📭 No hay ventas este mes ({nombre_mes}).", reply_markup=kb_volver())
        return ST_MENU
    csv_data = _csv_bytes(ventas, titulo)
    await update.get_bot().send_document(
        chat_id=q.message.chat_id,
        document=io.BytesIO(csv_data),
        filename=f"reporte_mensual_{nombre_mes}.csv",
        caption=f"🗓 *{titulo}* — {len(ventas)} venta(s)",
        parse_mode="Markdown",
    )
    return ST_MENU


async def rep_otro_mes_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "📁 *Reporte de otro mes*\n\nEscribe el mes en formato *MM/AAAA*\n_Ej: `03/2026`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_REP_OTRO_MES


async def rep_otro_mes_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        partes = update.message.text.strip().split("/")
        mes, anio = int(partes[0]), int(partes[1])
    except Exception:
        await _reply(update, ctx,
            "❌ Formato incorrecto. Usa *MM/AAAA*\n_Ej: `03/2026`_",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_REP_OTRO_MES

    ventas = db.ventas_mes(anio, mes)
    nombre_mes = f"{mes:02d}-{anio}"
    titulo = f"Reporte Mensual — {nombre_mes}"
    if not ventas:
        await _reply(update, ctx,
            f"📭 No hay ventas en *{nombre_mes}*.", parse_mode="Markdown", reply_markup=kb_volver()
        )
        return ST_MENU
    try:
        await update.message.delete()
    except Exception:
        pass
    csv_data = _csv_bytes(ventas, titulo)
    await update.message.reply_document(
        document=io.BytesIO(csv_data),
        filename=f"reporte_{nombre_mes}.csv",
        caption=f"📁 *{titulo}* — {len(ventas)} venta(s)",
        parse_mode="Markdown",
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  INVERSIÓN
# ══════════════════════════════════════════════════════════════════════════════

async def ver_inversion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    return await _render_inversion(q)


async def _render_inversion(q) -> int:
    inv_ini = float(db.get_config("inversion_inicial") or 15000)
    gastos  = db.gastos_inversion()
    total_g = db.total_gastado_inversion()
    restante = inv_ini - total_g

    texto = (
        f"🏦 Estado de la Inversión\n{SEP}\n"
        f"💵 Inversión inicial: {formato_mxn(inv_ini)}\n"
        f"💸 Total gastado: {formato_mxn(total_g)}\n"
        f"{'✅' if restante >= 0 else '⚠️'} Saldo disponible: {formato_mxn(max(0, restante))}"
    )
    if restante < 0:
        texto += f"\n⚠️ Excedida en {formato_mxn(abs(restante))}"
    if gastos:
        texto += f"\n\n{SEP}\nÚltimos gastos:"
        for g in gastos[:10]:
            texto += f"\n  #{g['id']}  {g['fecha'][:10]}  {g['concepto']}  {formato_mxn(g['monto_mxn'])}"
    else:
        texto += "\n\nSin gastos registrados aún."

    # Botones de gestión
    filas = [
        [
            InlineKeyboardButton("➕ Agregar dinero",   callback_data="inv_agregar"),
            InlineKeyboardButton("✏️ Editar total",    callback_data="inv_editar"),
        ],
        [InlineKeyboardButton("💸 Nuevo Gasto",        callback_data="gasto_inversion")],
    ]
    # Botón eliminar por cada gasto
    for g in gastos[:10]:
        filas.append([InlineKeyboardButton(
            f"🗑  Eliminar #{g['id']} — {g['concepto'][:28]}",
            callback_data=f"del_gasto:{g['id']}"
        )])
    filas.append([InlineKeyboardButton("🏠 Menú Principal", callback_data="menu")])

    await q.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(filas))
    return ST_MENU


# ── Editar / Agregar inversión inicial ───────────────────────────────────────

async def inv_editar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    actual = float(db.get_config("inversion_inicial") or 15000)
    await q.edit_message_text(
        f"✏️ *Editar Inversión Inicial*\n\n"
        f"Monto actual: *{formato_mxn(actual)}*\n\n"
        f"Escribe el *nuevo monto total*:\n_Ej: `20000 MX` o `1000 USD`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_INV_EDITAR_MONTO


async def inv_editar_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _, _, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_INV_EDITAR_MONTO
    db.update_inversion_inicial(mxn)
    txt_tc = f"\n_TC: ${tc:.2f}_" if tc != 1.0 else ""
    await _reply(update, ctx,
        f"✅ Inversión inicial actualizada a *{formato_mxn(mxn)}*{txt_tc}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏦 Ver Inversión", callback_data="ver_inversion")
        ]]),
    )
    return ST_MENU


async def inv_agregar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    actual = float(db.get_config("inversion_inicial") or 15000)
    await q.edit_message_text(
        f"➕ *Agregar Dinero a la Inversión*\n\n"
        f"Monto actual: *{formato_mxn(actual)}*\n\n"
        f"¿Cuánto se agrega?\n_Ej: `5000 MX` o `300 USD`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_INV_AGREGAR_MONTO


async def inv_agregar_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _, _, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_INV_AGREGAR_MONTO
    db.agregar_a_inversion(mxn)
    nuevo_total = float(db.get_config("inversion_inicial") or 15000)
    txt_tc = f"\n_TC: ${tc:.2f}_" if tc != 1.0 else ""
    await _reply(update, ctx,
        f"✅ *{formato_mxn(mxn)}* agregados a la inversión{txt_tc}\n"
        f"Nuevo total: *{formato_mxn(nuevo_total)}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏦 Ver Inversión", callback_data="ver_inversion")
        ]]),
    )
    return ST_MENU


# ── Eliminar gasto de inversión ───────────────────────────────────────────────

async def del_gasto_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    gasto_id = int(q.data.split(":")[1])
    gastos = db.gastos_inversion()
    g = next((x for x in gastos if x["id"] == gasto_id), None)
    if not g:
        await q.edit_message_text("❌ Gasto no encontrado.", reply_markup=kb_volver())
        return ST_MENU
    await q.edit_message_text(
        f"🗑 *¿Eliminar este gasto?*\n\n"
        f"📅 {g['fecha'][:10]}\n"
        f"📝 {g['concepto']}\n"
        f"💸 {formato_mxn(g['monto_mxn'])}\n\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"del_gasto_ok:{gasto_id}")],
            [InlineKeyboardButton("❌ Cancelar",     callback_data="ver_inversion")],
        ]),
    )
    return ST_MENU


async def del_gasto_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    gasto_id = int(q.data.split(":")[1])
    db.delete_gasto_inversion(gasto_id)
    await q.answer("🗑 Gasto eliminado", show_alert=True)
    return await _render_inversion(q)


async def gasto_inv_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "💼 *Gasto de Inversión*\n\n*Paso 1 / 2* — ¿En qué se gastó?",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_INV_CONCEPTO


async def gasto_inv_concepto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["inv_concepto"] = update.message.text.strip()
    await _reply(update, ctx,
        f"✅ Concepto: {ctx.user_data['inv_concepto']}\n\n"
        f"*Paso 2 / 2* — ¿Cuánto?\n_Ej: `500 MX` o `30 USD`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    return ST_INV_MONTO


async def gasto_inv_monto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto, moneda, mxn, tc = await parsear_monto(update.message.text)
    except ValueError as e:
        await _reply(update, ctx, f"❌ {e}", reply_markup=kb_cancelar())
        return ST_INV_MONTO

    concepto = ctx.user_data["inv_concepto"]
    db.registrar_gasto_inversion(concepto, monto, moneda, mxn, tc)
    restante = float(db.get_config("inversion_inicial") or 15000) - db.total_gastado_inversion()
    txt_tc = f"\n_TC: ${tc:.2f}_" if tc != 1.0 else ""
    await _reply(update, ctx,
        f"✅ *Gasto registrado*\n{SEP}\n"
        f"📝 {concepto}\n💸 {formato_mxn(mxn)}\n"
        f"💵 Saldo restante: *{formato_mxn(max(0, restante))}*{txt_tc}",
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    ctx.user_data.clear()
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  SOCIOS
# ══════════════════════════════════════════════════════════════════════════════

async def socios_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    socios = db.get_socios()
    await q.edit_message_text(
        f"⚙️ *Socios actuales:*\n" + "\n".join(f"   • {s}" for s in socios) +
        "\n\nEscribe los nuevos nombres separados por coma:\n_Ej: `Juan, Pedro, María`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_SOC_NUEVO


async def socios_guardar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    partes = [p.strip() for p in update.message.text.split(",") if p.strip()]
    if len(partes) < 2:
        await _reply(update, ctx,
            "❌ Al menos *2 nombres* separados por coma.",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_SOC_NUEVO
    db.set_socios(partes)
    await _reply(update, ctx,
        f"✅ *Socios actualizados:*\n" + "\n".join(f"   • {s}" for s in partes),
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  SOLTAR PEDIDO
# ══════════════════════════════════════════════════════════════════════════════

async def soltar_ped_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    p = db.get_pedido(pedido_id)
    if not p:
        await q.edit_message_text("❌ Pedido no encontrado.", reply_markup=kb_volver_pedidos())
        return ST_MENU
    await q.edit_message_text(
        f"🔓 *¿Soltar este pedido?*\n\n"
        f"*#{p['id']}* {p['tipo']} — {safe(p['descripcion'])}\n\n"
        f"El pedido regresará a *pendiente* y los demás socios\n"
        f"podrán tomarlo.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, soltar",  callback_data=f"soltar_ped_ok:{pedido_id}")],
            [InlineKeyboardButton("❌ Cancelar",    callback_data="ped_mios")],
        ]),
    )
    return ST_MENU


async def soltar_ped_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    tg_user = update.effective_user
    nombre = tg_user.first_name or tg_user.username or str(tg_user.id)

    pedido = db.soltar_pedido(pedido_id, nombre)
    if not pedido:
        await q.edit_message_text(
            "⚠️ No se pudo soltar. Verifica que este pedido aún te pertenece.",
            reply_markup=kb_volver_pedidos(),
        )
        return ST_MENU

    # Notificar a los demás que volvió a estar disponible
    kb_notif = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Aceptar pedido #{pedido_id}", callback_data=f"aceptar_ped:{pedido_id}")
    ]])
    gan = pedido["monto_cobrado_mxn"] - pedido["monto_compra_mxn"]
    await _notificar_socios(
        update.get_bot(), tg_user.id,
        f"🔓 *Pedido #{pedido_id} disponible de nuevo*\n\n"
        f"*{nombre}* lo soltó:\n"
        f"{pedido['tipo']} — {safe(pedido['descripcion'])}\n"
        f"💸 Total: {formato_mxn(pedido['monto_compra_mxn'])}\n"
        f"💰 Cobrado: {formato_mxn(pedido['monto_cobrado_mxn'])}\n"
        f"📈 Ganancia: *{formato_mxn(gan)}*",
        parse_mode="Markdown", reply_markup=kb_notif,
    )

    await q.edit_message_text(
        f"🔓 Pedido *#{pedido_id}* soltado.\n"
        f"Los demás socios fueron notificados.",
        parse_mode="Markdown",
        reply_markup=kb_volver_pedidos(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  ELIMINAR VENTA
# ══════════════════════════════════════════════════════════════════════════════

async def del_venta_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    venta_id = int(q.data.split(":")[1])
    v = db.get_venta(venta_id)
    if not v:
        await q.edit_message_text("❌ Venta no encontrada.", reply_markup=kb_volver())
        return ST_MENU
    gan = v["monto_cobrado_mxn"] - v["monto_gastado_mxn"]
    await q.edit_message_text(
        f"🗑 *¿Eliminar esta venta?*\n\n"
        f"📅 {v['fecha'][:10]}\n"
        f"👤 {v['usuario']}  💳 `****{v['tarjeta'][-4:]}`\n"
        f"📦 {safe(v['descripcion'])}\n"
        f"💰 {formato_mxn(v['monto_cobrado_mxn'])}  💸 {formato_mxn(v['monto_gastado_mxn'])}\n"
        f"📈 Ganancia: {formato_mxn(gan)}\n\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"del_venta_ok:{venta_id}")],
            [InlineKeyboardButton("❌ Cancelar",     callback_data="mis_ventas")],
        ]),
    )
    return ST_MENU


async def del_venta_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("🗑 Venta eliminada", show_alert=True)
    venta_id = int(q.data.split(":")[1])
    db.delete_venta(venta_id)
    # Vuelve al menú principal
    await q.edit_message_text(
        "✅ Venta eliminada.\n\nSelecciona una opción:",
        reply_markup=kb_menu(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  ELIMINAR PEDIDO
# ══════════════════════════════════════════════════════════════════════════════

async def del_pedido_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    pedido_id = int(q.data.split(":")[1])
    p = db.get_pedido(pedido_id)
    if not p:
        await q.edit_message_text("❌ Pedido no encontrado.", reply_markup=kb_volver_pedidos())
        return ST_MENU
    estados_txt = {"pendiente": "⏳ Pendiente", "en_proceso": "🔄 En proceso",
                   "completado": "✅ Completado", "cancelado": "❌ Cancelado"}
    await q.edit_message_text(
        f"🗑 *¿Eliminar este pedido?*\n\n"
        f"*#{p['id']}* {p['tipo']} — {safe(p['descripcion'])}\n"
        f"Estado: {estados_txt.get(p['estado'], p['estado'])}\n"
        f"💸 {formato_mxn(p['monto_compra_mxn'])}  💰 {formato_mxn(p['monto_cobrado_mxn'])}\n\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sí, eliminar", callback_data=f"del_pedido_ok:{pedido_id}")],
            [InlineKeyboardButton("❌ Cancelar",     callback_data="pedidos_menu")],
        ]),
    )
    return ST_MENU


async def del_pedido_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("🗑 Pedido eliminado", show_alert=True)
    pedido_id = int(q.data.split(":")[1])
    db.delete_pedido(pedido_id)
    await q.edit_message_text(
        "✅ Pedido eliminado.\n\n¿Qué deseas hacer?",
        reply_markup=kb_pedidos_menu(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  BODEGA DE BINS
# ══════════════════════════════════════════════════════════════════════════════

async def bin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    todos = db.todos_los_bins()
    tiendas = db.get_tiendas_bins()
    await q.edit_message_text(
        f"🗂 *Bodega de BINs*\n\n"
        f"💳 {len(todos)} BINs  |  🏪 {len(tiendas)} tiendas\n\n"
        f"¿Qué deseas hacer?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕  Agregar BIN",        callback_data="bin_agregar")],
            [InlineKeyboardButton("🔍  Buscar BIN",         callback_data="bin_buscar")],
            [
                InlineKeyboardButton("🏪  Ver por Tienda",  callback_data="bin_ver_tiendas"),
                InlineKeyboardButton("📋  Ver Todos",       callback_data="bin_ver_todos"),
            ],
            [InlineKeyboardButton("🏠  Menú Principal",    callback_data="menu")],
        ]),
    )
    return ST_MENU


async def bin_agregar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🗂 *Agregar BIN*\n\n"
        "Escribe los primeros *6 dígitos* de la tarjeta:\n"
        "_Ej: `431274`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_BIN_NUM


async def bin_buscar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🔍 *Buscar BIN(s)*\n\n"
        "Puedes enviar:\n"
        "• Un BIN: `431274`\n"
        "• Varios separados por espacio, coma o salto de línea:\n"
        "  `431274 523456 412345`\n"
        "• Un archivo *.txt* con un BIN por línea",
        parse_mode="Markdown",
        reply_markup=kb_volver_bins(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_BIN_BUSCAR


async def _procesar_lista_bins(bins: list[str]) -> list[str]:
    """Consulta info y bodega de cada BIN en paralelo. Devuelve lista de bloques de texto."""
    async def _uno(b: str) -> str:
        info_task = asyncio.create_task(bin_info.consultar_bin(b))
        registros = await asyncio.to_thread(db.buscar_bin, b)
        info = await info_task

        if info:
            banco  = safe(info["bank"]) or "Desconocido"
            pais   = safe(info["country"]) or "?"
            codigo = f" `{info['country_code']}`" if info.get("country_code") else ""
            partes = [p for p in [info.get("brand"), info.get("type"), info.get("level")] if p]
            marca  = f"  💠 {' · '.join(partes)}" if partes else ""
            lineas = [f"💳 `{b}`  🏦 *{banco}*\n🌍 {pais}{codigo}{marca}"]
        else:
            lineas = [f"💳 `{b}`  ⚠️ _Sin info bancaria_"]

        if registros:
            tiendas = ", ".join(f"*{safe(r['tienda'])}*" for r in registros)
            lineas.append(f"✅ Bodega: {tiendas}")
        else:
            lineas.append("📭 _No en bodega_")

        return "\n".join(lineas)

    return await asyncio.gather(*[_uno(b) for b in bins])


async def _enviar_en_partes(message, bloques: list[str], reply_markup) -> None:
    """Envía los bloques respetando el límite de 4096 chars de Telegram."""
    separador = "\n\n─────────────────\n\n"
    chunk = ""
    for i, bloque in enumerate(bloques):
        es_ultimo = i == len(bloques) - 1
        nuevo = (chunk + separador + bloque) if chunk else bloque
        if len(nuevo) > 4000:
            await message.reply_text(chunk, parse_mode="Markdown")
            chunk = bloque
        else:
            chunk = nuevo
        if es_ultimo and chunk:
            await message.reply_text(chunk, parse_mode="Markdown",
                                     reply_markup=reply_markup)


async def bin_buscar_resultado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    import re
    texto = update.message.text
    bins = list(dict.fromkeys(re.findall(r'\b(\d{6})\b', texto)))  # únicos, en orden

    if not bins:
        await _reply(update, ctx,
            "❌ No encontré ningún BIN de 6 dígitos. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    if len(bins) == 1:
        # Formato detallado para un solo BIN
        b = bins[0]
        info_task = asyncio.create_task(bin_info.consultar_bin(b))
        registros = await asyncio.to_thread(db.buscar_bin, b)
        info = await info_task

        lineas = []
        if info:
            conf_str = f"{info['confianza']}/{info['fuentes']} fuentes"
            lineas += [
                f"💳 BIN: `{b}`",
                f"🏦 Banco: *{safe(info['bank']) or 'Desconocido'}*",
                f"🌍 País: {safe(info['country']) or 'Desconocido'}"
                + (f" `{info['country_code']}`" if info.get("country_code") else ""),
                f"💠 {safe(info['brand'])}  •  {safe(info['type'])}"
                + (f"  •  ⭐ {safe(info['level'])}" if info.get("level") else ""),
                f"🔎 Consenso: _{conf_str}_",
            ]
        else:
            lineas.append(f"💳 BIN: `{b}`\n⚠️ _No se obtuvo info bancaria_")

        if registros:
            lineas.append(f"\n✅ *Registrado en {len(registros)} tienda(s):*")
            for r in registros:
                lineas.append(
                    f"🏪 *{safe(r['tienda'])}*\n"
                    f"   👤 {safe(r['agregado_por'])}  •  📅 {r['fecha'][:10]}"
                )
        else:
            lineas.append("\n📭 _No está en la bodega aún._")

        await _reply(update, ctx, "\n".join(lineas), parse_mode="Markdown",
                     reply_markup=kb_volver_bins())
        return ST_MENU

    # Múltiples BINs — formato compacto
    try:
        await update.message.delete()
    except Exception:
        pass
    aviso = await update.message.reply_text(
        f"⏳ Consultando {len(bins)} BINs...", parse_mode="Markdown"
    )
    bloques = await _procesar_lista_bins(bins)
    await aviso.delete()
    encabezado = f"🔍 *Resultados — {len(bins)} BINs*\n"
    bloques[0] = encabezado + bloques[0]
    await _enviar_en_partes(update.message, bloques, kb_volver_bins())
    return ST_MENU


async def bin_buscar_txt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe un archivo .txt con BINs y los procesa todos."""
    import re
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await _reply(update, ctx,
            "❌ Solo acepto archivos *.txt*. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    try:
        await update.message.delete()
    except Exception:
        pass

    tg_file = await ctx.bot.get_file(doc.file_id)
    raw = await tg_file.download_as_bytearray()
    texto = raw.decode("utf-8", errors="ignore")
    bins = list(dict.fromkeys(re.findall(r'\b(\d{6})\b', texto)))

    if not bins:
        await update.message.reply_text(
            "❌ No encontré BINs de 6 dígitos en el archivo.",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    aviso = await update.message.reply_text(
        f"⏳ Consultando {len(bins)} BINs del archivo...", parse_mode="Markdown"
    )
    bloques = await _procesar_lista_bins(bins)
    await aviso.delete()
    encabezado = f"🔍 *Resultados del archivo — {len(bins)} BINs*\n"
    bloques[0] = encabezado + bloques[0]
    await _enviar_en_partes(update.message, bloques, kb_volver_bins())
    return ST_MENU


async def bin_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip().replace(" ", "")
    if not texto.isdigit() or len(texto) != 6:
        await _reply(update, ctx,
            "❌ Deben ser exactamente *6 dígitos*. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_BIN_NUM

    ctx.user_data["bin_num"] = texto
    tiendas = db.get_tiendas_bins()

    if not tiendas:
        await _reply(update, ctx,
            f"🗂 BIN: `{texto}`\n\n"
            "No hay tiendas registradas aún.\n"
            "Escribe el nombre del establecimiento donde jala:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_BIN_NUEVA_TIENDA

    await _reply(update, ctx,
        f"🗂 BIN: `{texto}`\n\n¿En qué tienda/establecimiento jala?",
        parse_mode="Markdown",
        reply_markup=kb_tiendas_bin(),
    )
    return ST_BIN_TIENDA


async def bin_tienda_sel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    tienda = q.data.split(":", 1)[1]
    return await _guardar_bin(update, ctx, tienda)


async def bin_nueva_tienda_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🏪 *Nueva Tienda*\n\n"
        "Escribe el nombre del establecimiento:\n"
        "_Ej: Amazon, Airbnb, Walmart_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (q.message.chat_id, q.message.message_id)
    return ST_BIN_NUEVA_TIENDA


async def bin_nueva_tienda_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    nombre = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    db.agregar_tienda_bin(nombre)
    return await _guardar_bin(update, ctx, nombre)


async def _guardar_bin(update: Update, ctx: ContextTypes.DEFAULT_TYPE, tienda: str) -> int:
    bin_num = ctx.user_data.pop("bin_num", "")
    tg_user = update.effective_user
    nombre = tg_user.first_name or tg_user.username or str(tg_user.id)

    ok = db.agregar_bin(bin_num, tienda, nombre)
    info = await bin_info.consultar_bin(bin_num)

    kb_post = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Otro BIN",          callback_data="bin_agregar")],
        [InlineKeyboardButton("🗂  Bodega de BINs",    callback_data="bin_menu")],
        [InlineKeyboardButton("🏠  Menú Principal",    callback_data="menu")],
    ])

    def _info_lineas() -> str:
        if not info:
            return ""
        return (
            f"\n🏦 {safe(info['bank']) or 'Banco desconocido'}"
            f" · 🌍 {safe(info['country']) or '?'}"
            + (f" ({info['country_code']})" if info.get("country_code") else "")
            + (f"\n💠 {info['brand']}  •  {info['type']}"
               + (f"  •  ⭐ {info['level']}" if info.get("level") else "")
               if info.get("brand") else "")
        )

    async def reply(text, **kw):
        if update.callback_query:
            await update.callback_query.edit_message_text(text, **kw)
        else:
            await _reply(update, ctx, text, **kw)

    if not ok:
        existente = db.get_bin_existente(bin_num, tienda)
        await reply(
            f"⚠️ *BIN ya registrado*\n\n"
            f"💳 `{bin_num}` en *{safe(tienda)}* ya fue registrado\n"
            f"por *{safe(existente['agregado_por'])}* el {existente['fecha'][:10]}."
            + _info_lineas(),
            parse_mode="Markdown",
            reply_markup=kb_post,
        )
    else:
        await reply(
            f"✅ *BIN registrado*\n\n"
            f"💳 BIN: `{bin_num}`\n"
            f"🏪 Tienda: *{safe(tienda)}*\n"
            f"👤 Por: {nombre}"
            + _info_lineas(),
            parse_mode="Markdown",
            reply_markup=kb_post,
        )
        await _notificar_socios(
            update.get_bot(), tg_user.id,
            f"🗂 *Nuevo BIN registrado*\n\n"
            f"💳 `{bin_num}` jala en *{tienda}*\n"
            f"👤 Por {nombre}"
            + _info_lineas(),
            parse_mode="Markdown",
        )

    ctx.user_data.clear()
    return ST_MENU


async def bin_ver_todos(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    bins = db.todos_los_bins()
    if not bins:
        await q.edit_message_text("📭 No hay BINs registrados aún.", reply_markup=kb_volver_bins())
        return ST_MENU

    por_tienda: dict = {}
    for b in bins:
        por_tienda.setdefault(b["tienda"], []).append(b["bin"])

    lineas = [f"📋 *Todos los BINs* ({len(bins)})\n{SEP}"]
    for tienda, lista in sorted(por_tienda.items()):
        lineas.append(f"🏪 *{safe(tienda)}*")
        lineas.append("  " + "   ".join(f"`{b}`" for b in lista))

    await q.edit_message_text(
        "\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=kb_volver_bins(),
    )
    return ST_MENU


async def bin_ver_tiendas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    tiendas = db.get_tiendas_bins()
    if not tiendas:
        await q.edit_message_text("📭 No hay tiendas registradas.", reply_markup=kb_volver_bins())
        return ST_MENU

    filas = [
        [InlineKeyboardButton(t["nombre"], callback_data=f"bin_ver:{t['nombre']}")]
        for t in tiendas
    ]
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    await q.edit_message_text(
        "🔍 *Ver BINs por Tienda*\n\nSelecciona la tienda:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas),
    )
    return ST_MENU


async def bin_ver_tienda(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    tienda = q.data.split(":", 1)[1]
    bins = db.bins_por_tienda(tienda)
    if not bins:
        await q.edit_message_text(
            f"📭 No hay BINs para *{safe(tienda)}* aún.",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_MENU

    lineas = [f"🏪 *{safe(tienda)}* — {len(bins)} BINs\n{SEP}"]
    for b in bins:
        lineas.append(f"  💳 `{b['bin']}` — {safe(b['agregado_por'])} · {b['fecha'][:10]}")

    await q.edit_message_text(
        "\n".join(lineas),
        parse_mode="Markdown",
        reply_markup=kb_volver_bins(),
    )
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  /RMV — ELIMINAR TIENDAS Y BINS
# ══════════════════════════════════════════════════════════════════════════════

async def rmv_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END
    texto = "🗑 *Eliminar de Bodega de BINs*\n\n¿Qué quieres eliminar?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏪  Tienda completa (y sus BINs)", callback_data="rmv_modo:tienda")],
        [InlineKeyboardButton("💳  Un BIN específico",            callback_data="rmv_modo:bin")],
        [InlineKeyboardButton("❌  Cancelar",                     callback_data="bin_menu")],
    ])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(texto, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=kb)
    return ST_MENU


async def rmv_sel_tiendas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    modo = q.data.split(":", 1)[1]
    tiendas = db.get_tiendas_bins()
    if not tiendas:
        await q.edit_message_text("📭 No hay tiendas registradas.", reply_markup=kb_volver_bins())
        return ST_MENU

    if modo == "tienda":
        prefijo = "rmv_del_tienda"
        titulo = "🏪 *Selecciona la tienda a eliminar*\n_Se borrarán todos sus BINs_"
    else:
        prefijo = "rmv_bins"
        titulo = "💳 *¿De qué tienda quieres eliminar el BIN?*"

    filas = [
        [InlineKeyboardButton(t["nombre"], callback_data=f"{prefijo}:{t['nombre']}")]
        for t in tiendas
    ]
    filas.append([InlineKeyboardButton("❌  Cancelar", callback_data="bin_menu")])
    await q.edit_message_text(titulo, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(filas))
    return ST_MENU


async def rmv_confirmar_tienda(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    tienda = q.data.split(":", 1)[1]
    n_bins = len(db.bins_por_tienda(tienda))
    await q.edit_message_text(
        f"⚠️ *¿Eliminar esta tienda?*\n\n"
        f"🏪 *{safe(tienda)}*\n"
        f"💳 {n_bins} BINs guardados se eliminarán también\n\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅  Sí, eliminar todo", callback_data=f"rmv_ok_tienda:{tienda}")],
            [InlineKeyboardButton("❌  Cancelar",          callback_data="bin_menu")],
        ]),
    )
    return ST_MENU


async def rmv_ok_tienda(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    tienda = q.data.split(":", 1)[1]
    n_bins = len(db.bins_por_tienda(tienda))
    db.delete_tienda_bin(tienda)
    await q.edit_message_text(
        f"✅ *Tienda eliminada*\n\n"
        f"🏪 {safe(tienda)}\n"
        f"💳 {n_bins} BIN{'s' if n_bins != 1 else ''} eliminado{'s' if n_bins != 1 else ''}",
        parse_mode="Markdown",
        reply_markup=kb_volver_bins(),
    )
    return ST_MENU


async def rmv_sel_bins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    tienda = q.data.split(":", 1)[1]
    bins = db.bins_por_tienda(tienda)
    if not bins:
        await q.edit_message_text(
            f"📭 No hay BINs en *{safe(tienda)}*.",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_MENU

    filas = [
        [InlineKeyboardButton(
            f"💳 {b['bin']} — {b['agregado_por']}",
            callback_data=f"rmv_del_bin:{b['id']}"
        )]
        for b in bins
    ]
    filas.append([InlineKeyboardButton("❌  Cancelar", callback_data="bin_menu")])
    await q.edit_message_text(
        f"💳 *BINs de {safe(tienda)}*\nSelecciona el que quieres eliminar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(filas),
    )
    return ST_MENU


async def rmv_confirmar_bin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    bin_id = int(q.data.split(":")[1])
    b = db.get_bin(bin_id)
    if not b:
        await q.edit_message_text("❌ BIN no encontrado.", reply_markup=kb_volver_bins())
        return ST_MENU
    await q.edit_message_text(
        f"⚠️ *¿Eliminar este BIN?*\n\n"
        f"💳 `{b['bin']}` en *{safe(b['tienda'])}*\n"
        f"👤 Registrado por {safe(b['agregado_por'])} el {b['fecha'][:10]}\n\n"
        f"_Esta acción no se puede deshacer._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅  Sí, eliminar", callback_data=f"rmv_ok_bin:{bin_id}")],
            [InlineKeyboardButton("❌  Cancelar",     callback_data="bin_menu")],
        ]),
    )
    return ST_MENU


async def rmv_ok_bin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    bin_id = int(q.data.split(":")[1])
    b = db.get_bin(bin_id)
    if b:
        db.delete_bin(bin_id)
        await q.edit_message_text(
            f"✅ *BIN eliminado*\n\n"
            f"💳 `{b['bin']}` de *{safe(b['tienda'])}*",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
    else:
        await q.edit_message_text("❌ BIN no encontrado.", reply_markup=kb_volver_bins())
    return ST_MENU


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en .env")
    if not ALLOWED_IDS:
        raise RuntimeError("Falta ALLOWED_IDS en .env  Ej: ALLOWED_IDS=123,456,789")

    db.init_db()
    logger.info(f"IDs autorizados: {ALLOWED_IDS}")

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", mostrar_menu),
            CommandHandler("rmv",   rmv_menu),
            # Permiten interactuar con pedidos desde notificaciones externas
            CallbackQueryHandler(aceptar_ped_inicio,   pattern=r"^aceptar_ped:\d+$"),
            CallbackQueryHandler(completar_ped_inicio, pattern=r"^completar_ped:\d+$"),
        ],
        states={
            ST_MENU: [
                CallbackQueryHandler(mostrar_menu,         pattern="^menu$"),
                CallbackQueryHandler(pedidos_menu,         pattern="^pedidos_menu$"),
                CallbackQueryHandler(ped_crear_inicio,     pattern="^ped_crear$"),
                CallbackQueryHandler(ped_ver_pendientes,   pattern="^ped_pendientes$"),
                CallbackQueryHandler(ped_mios,             pattern="^ped_mios$"),
                CallbackQueryHandler(aceptar_ped_inicio,   pattern=r"^aceptar_ped:\d+$"),
                CallbackQueryHandler(completar_ped_inicio, pattern=r"^completar_ped:\d+$"),
                CallbackQueryHandler(nv_inicio,            pattern="^nueva_venta$"),
                CallbackQueryHandler(mv_inicio,            pattern="^mis_ventas$"),
                CallbackQueryHandler(todas_ventas,         pattern="^todas_ventas$"),
                CallbackQueryHandler(resumen_actual,       pattern="^resumen_actual$"),
                CallbackQueryHandler(resumen_otro_inicio,  pattern="^resumen_otro$"),
                CallbackQueryHandler(reporte_menu,         pattern="^reporte_menu$"),
                CallbackQueryHandler(rep_hoy,              pattern="^rep_hoy$"),
                CallbackQueryHandler(rep_semana,           pattern="^rep_semana$"),
                CallbackQueryHandler(rep_mes_actual,       pattern="^rep_mes_actual$"),
                CallbackQueryHandler(rep_otro_mes_inicio,  pattern="^rep_otro_mes$"),
                CallbackQueryHandler(ver_inversion,        pattern="^ver_inversion$"),
                CallbackQueryHandler(gasto_inv_inicio,     pattern="^gasto_inversion$"),
                CallbackQueryHandler(inv_editar_inicio,    pattern="^inv_editar$"),
                CallbackQueryHandler(inv_agregar_inicio,   pattern="^inv_agregar$"),
                CallbackQueryHandler(del_gasto_confirm,    pattern=r"^del_gasto:\d+$"),
                CallbackQueryHandler(del_gasto_ok,         pattern=r"^del_gasto_ok:\d+$"),
                CallbackQueryHandler(del_venta_confirm,    pattern=r"^del_venta:\d+$"),
                CallbackQueryHandler(del_venta_ok,         pattern=r"^del_venta_ok:\d+$"),
                CallbackQueryHandler(del_pedido_confirm,   pattern=r"^del_pedido:\d+$"),
                CallbackQueryHandler(del_pedido_ok,        pattern=r"^del_pedido_ok:\d+$"),
                CallbackQueryHandler(soltar_ped_confirm,   pattern=r"^soltar_ped:\d+$"),
                CallbackQueryHandler(soltar_ped_ok,        pattern=r"^soltar_ped_ok:\d+$"),
                # Bodega de BINs — navegación
                CallbackQueryHandler(bin_menu,             pattern="^bin_menu$"),
                CallbackQueryHandler(bin_agregar_inicio,   pattern="^bin_agregar$"),
                CallbackQueryHandler(bin_buscar_inicio,    pattern="^bin_buscar$"),
                CallbackQueryHandler(bin_ver_todos,        pattern="^bin_ver_todos$"),
                CallbackQueryHandler(bin_ver_tiendas,      pattern="^bin_ver_tiendas$"),
                CallbackQueryHandler(bin_ver_tienda,       pattern=r"^bin_ver:"),
                # Bodega de BINs — eliminar (/rmv)
                CommandHandler("rmv",                      rmv_menu),
                CallbackQueryHandler(rmv_menu,             pattern="^rmv_menu$"),
                CallbackQueryHandler(rmv_sel_tiendas,      pattern=r"^rmv_modo:"),
                CallbackQueryHandler(rmv_confirmar_tienda, pattern=r"^rmv_del_tienda:"),
                CallbackQueryHandler(rmv_ok_tienda,        pattern=r"^rmv_ok_tienda:"),
                CallbackQueryHandler(rmv_sel_bins,         pattern=r"^rmv_bins:"),
                CallbackQueryHandler(rmv_confirmar_bin,    pattern=r"^rmv_del_bin:\d+$"),
                CallbackQueryHandler(rmv_ok_bin,           pattern=r"^rmv_ok_bin:\d+$"),
            ],
            # ── Pedidos — crear ───────────────────────────────────────────────
            ST_PED_TIPO: [
                CallbackQueryHandler(ped_tipo,         pattern=r"^ped_tipo:"),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_PED_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ped_link),
                CallbackQueryHandler(ped_link_saltar,  pattern="^ped_skip_link$"),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_PED_PEDESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ped_desc),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_PED_COSTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ped_costo),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_PED_COBRADOP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ped_cobrado),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Pedidos — confirmar aceptación ───────────────────────────────
            ST_AC_CONFIRMAR: [
                CallbackQueryHandler(aceptar_ped_confirmar, pattern=r"^ac_confirmar:\d+$"),
                CallbackQueryHandler(pedidos_menu,          pattern="^pedidos_menu$"),
                CallbackQueryHandler(mostrar_menu,          pattern="^menu$"),
            ],
            # ── Pedidos — completar (llenar tarjeta) ──────────────────────────
            ST_COMP_TARJETA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, completar_ped_tarjeta),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Nueva venta manual ────────────────────────────────────────────
            ST_VT_SOCIO: [
                CallbackQueryHandler(nv_socio,         pattern=r"^vt_socio:"),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_VT_TARJETA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, nv_tarjeta),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_VT_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, nv_desc),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_VT_COBRADO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, nv_cobrado),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_VT_GASTADO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, nv_gastado),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Mis ventas ────────────────────────────────────────────────────
            ST_MV_SOCIO: [
                CallbackQueryHandler(mv_mostrar,       pattern=r"^mv_socio:"),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Resumen ───────────────────────────────────────────────────────
            ST_RES_MES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, resumen_mes_texto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Reportes descargables — otro mes ──────────────────────────────
            ST_REP_OTRO_MES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rep_otro_mes_texto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Inversión ─────────────────────────────────────────────────────
            ST_INV_CONCEPTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_inv_concepto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_INV_MONTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_inv_monto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_INV_EDITAR_MONTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, inv_editar_monto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_INV_AGREGAR_MONTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, inv_agregar_monto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            # ── Bodega de BINs ────────────────────────────────────────────────
            ST_BIN_BUSCAR: [
                MessageHandler(filters.Document.ALL,              bin_buscar_txt),
                MessageHandler(filters.TEXT & ~filters.COMMAND,   bin_buscar_resultado),
                CallbackQueryHandler(bin_menu,         pattern="^bin_menu$"),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_BIN_NUM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bin_num),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
            ST_BIN_TIENDA: [
                CallbackQueryHandler(bin_tienda_sel,          pattern=r"^bin_tienda:"),
                CallbackQueryHandler(bin_nueva_tienda_inicio, pattern="^bin_nueva_tienda$"),
                CallbackQueryHandler(mostrar_menu,            pattern="^menu$"),
            ],
            ST_BIN_NUEVA_TIENDA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bin_nueva_tienda_texto),
                CallbackQueryHandler(mostrar_menu,     pattern="^menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", mostrar_menu),
            CallbackQueryHandler(mostrar_menu, pattern="^menu$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("✅ Bot iniciado y escuchando...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
