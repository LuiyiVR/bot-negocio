"""Bodega de BINs: agregar, buscar, ver, eliminar (/rmv)."""
import asyncio
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
import bin_info
from config import SEP
from formatters import safe, nombre_usuario
from notifications import notificar_otros
from utils import autorizado, rechazar, db_thread, reply_clean, remember_panel
from keyboards import kb_cancelar, kb_volver_bins, kb_tiendas_bin, kb_bin_menu
from states import (
    ST_MENU, ST_BIN_NUM, ST_BIN_TIENDA, ST_BIN_NUEVA_TIENDA, ST_BIN_BUSCAR,
)


# ═════════════════════════════════════════════════════════════════════════════
#  MENÚ DE BINs
# ═════════════════════════════════════════════════════════════════════════════

async def bin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    todos = await db_thread(db.todos_los_bins)
    tiendas = await db_thread(db.get_tiendas_bins)

    await q.edit_message_text(
        f"🗂 *Bodega de BINs*\n\n"
        f"💳 {len(todos)} BINs  |  🏪 {len(tiendas)} tiendas\n\n"
        f"¿Qué deseas hacer?",
        parse_mode="Markdown",
        reply_markup=kb_bin_menu(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  AGREGAR BIN
# ═════════════════════════════════════════════════════════════════════════════

async def bin_agregar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    msg = await q.edit_message_text(
        "🗂 *Agregar BIN*\n\n"
        "Escribe los primeros *6 dígitos* de la tarjeta:\n"
        "_Ej: `431274`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_BIN_NUM


async def bin_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip().replace(" ", "")
    if not texto.isdigit() or len(texto) != 6:
        await reply_clean(update, ctx,
            "❌ Deben ser exactamente *6 dígitos*. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_BIN_NUM

    ctx.user_data["bin_num"] = texto
    tiendas = await db_thread(db.get_tiendas_bins)

    if not tiendas:
        await reply_clean(update, ctx,
            f"🗂 BIN: `{texto}`\n\n"
            "No hay tiendas registradas aún.\n"
            "Escribe el nombre del establecimiento donde jala:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_BIN_NUEVA_TIENDA

    await reply_clean(update, ctx,
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
    msg = await q.edit_message_text(
        "🏪 *Nueva Tienda*\n\n"
        "Escribe el nombre del establecimiento:\n"
        "_Ej: Amazon, Airbnb, Walmart_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_BIN_NUEVA_TIENDA


async def bin_nueva_tienda_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    nombre = update.message.text.strip()
    if not nombre or len(nombre) > 50:
        await reply_clean(update, ctx,
            "❌ Nombre inválido (1–50 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_BIN_NUEVA_TIENDA

    try:
        await update.message.delete()
    except Exception:
        pass

    await db_thread(db.agregar_tienda_bin, nombre)
    return await _guardar_bin(update, ctx, nombre)


async def _guardar_bin(update: Update, ctx: ContextTypes.DEFAULT_TYPE, tienda: str) -> int:
    bin_num_v = ctx.user_data.pop("bin_num", "")
    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    ok = await db_thread(db.agregar_bin, bin_num_v, tienda, nombre)
    info = await bin_info.consultar_bin(bin_num_v)

    kb_post = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Otro BIN",          callback_data="bin_agregar")],
        [InlineKeyboardButton("🗂  Bodega de BINs",    callback_data="bin_menu")],
        [InlineKeyboardButton("🏠  Menú Principal",    callback_data="menu")],
    ])

    def _info_lineas() -> str:
        if not info:
            return ""
        out = (
            f"\n🏦 {safe(info['bank']) or 'Banco desconocido'}"
            f" · 🌍 {safe(info['country']) or '?'}"
        )
        if info.get("country_code"):
            out += f" ({info['country_code']})"
        if info.get("brand"):
            extra = f"\n💠 {info['brand']}  •  {info['type']}"
            if info.get("level"):
                extra += f"  •  ⭐ {info['level']}"
            out += extra
        return out

    async def reply(text, **kw):
        if update.callback_query:
            await update.callback_query.edit_message_text(text, **kw)
        else:
            await reply_clean(update, ctx, text, **kw)

    if not ok:
        existente = await db_thread(db.get_bin_existente, bin_num_v, tienda)
        await reply(
            f"⚠️ *BIN ya registrado*\n\n"
            f"💳 `{bin_num_v}` en *{safe(tienda)}* ya fue registrado\n"
            f"por *{safe(existente['agregado_por'])}* el {existente['fecha'][:10]}."
            + _info_lineas(),
            parse_mode="Markdown",
            reply_markup=kb_post,
        )
    else:
        await reply(
            f"✅ *BIN registrado*\n\n"
            f"💳 BIN: `{bin_num_v}`\n"
            f"🏪 Tienda: *{safe(tienda)}*\n"
            f"👤 Por: {nombre}"
            + _info_lineas(),
            parse_mode="Markdown",
            reply_markup=kb_post,
        )
        await notificar_otros(
            update.get_bot(), tg_user.id,
            f"🗂 *Nuevo BIN registrado*\n\n"
            f"💳 `{bin_num_v}` jala en *{tienda}*\n"
            f"👤 Por {nombre}"
            + _info_lineas(),
            parse_mode="Markdown",
        )

    ctx.user_data.clear()
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  BUSCAR BIN
# ═════════════════════════════════════════════════════════════════════════════

async def bin_buscar_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    msg = await q.edit_message_text(
        "🔍 *Buscar BIN(s)*\n\n"
        "Puedes enviar:\n"
        "• Un BIN: `431274`\n"
        "• Varios separados por espacio, coma o salto de línea:\n"
        "  `431274 523456 412345`\n"
        "• Un archivo *.txt* con un BIN por línea",
        parse_mode="Markdown",
        reply_markup=kb_volver_bins(),
    )
    remember_panel(ctx, msg)
    return ST_BIN_BUSCAR


async def _procesar_lista_bins(bins: list[str]) -> list[str]:
    """Consulta info y bodega de cada BIN en paralelo. Devuelve bloques de texto."""
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
    """Envía bloques respetando el límite de 4096 chars de Telegram."""
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
    texto = update.message.text
    bins = list(dict.fromkeys(re.findall(r"\b(\d{6})\b", texto)))

    if not bins:
        await reply_clean(update, ctx,
            "❌ No encontré ningún BIN de 6 dígitos. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    if len(bins) == 1:
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

        await reply_clean(update, ctx, "\n".join(lineas),
            parse_mode="Markdown", reply_markup=kb_volver_bins())
        return ST_MENU

    # Múltiples BINs
    chat = update.effective_chat
    try:
        await update.message.delete()
    except Exception:
        pass

    aviso = await chat.send_message(
        f"⏳ Consultando {len(bins)} BINs...", parse_mode="Markdown"
    )
    bloques = await _procesar_lista_bins(bins)
    await aviso.delete()
    encabezado = f"🔍 *Resultados — {len(bins)} BINs*\n"
    bloques[0] = encabezado + bloques[0]
    await _enviar_en_partes(aviso, bloques, kb_volver_bins())
    return ST_MENU


async def bin_buscar_txt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe un archivo .txt con BINs y los procesa todos."""
    MAX_BINS_POR_ARCHIVO = 100
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await reply_clean(update, ctx,
            "❌ Solo acepto archivos *.txt*. Intenta de nuevo:",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    chat = update.effective_chat
    try:
        await update.message.delete()
    except Exception:
        pass

    tg_file = await ctx.bot.get_file(doc.file_id)
    raw = await tg_file.download_as_bytearray()
    texto = raw.decode("utf-8", errors="ignore")
    bins = list(dict.fromkeys(re.findall(r"\b(\d{6})\b", texto)))

    if not bins:
        await chat.send_message(
            "❌ No encontré BINs de 6 dígitos en el archivo.",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    if len(bins) > MAX_BINS_POR_ARCHIVO:
        await chat.send_message(
            f"⚠️ El archivo tiene *{len(bins)} BINs*. Máximo: {MAX_BINS_POR_ARCHIVO}.\n"
            f"Divide el archivo en partes más pequeñas.",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
        return ST_BIN_BUSCAR

    aviso = await chat.send_message(
        f"⏳ Consultando {len(bins)} BINs del archivo...", parse_mode="Markdown"
    )
    bloques = await _procesar_lista_bins(bins)
    await aviso.delete()
    encabezado = f"🔍 *Resultados del archivo — {len(bins)} BINs*\n"
    bloques[0] = encabezado + bloques[0]
    await _enviar_en_partes(aviso, bloques, kb_volver_bins())
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  VER BINs
# ═════════════════════════════════════════════════════════════════════════════

async def bin_ver_todos(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    bins = await db_thread(db.todos_los_bins)
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
    tiendas = await db_thread(db.get_tiendas_bins)
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
    bins = await db_thread(db.bins_por_tienda, tienda)
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


# ═════════════════════════════════════════════════════════════════════════════
#  /RMV — ELIMINAR
# ═════════════════════════════════════════════════════════════════════════════

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
    tiendas = await db_thread(db.get_tiendas_bins)
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
    n_bins = len(await db_thread(db.bins_por_tienda, tienda))
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
    n_bins = len(await db_thread(db.bins_por_tienda, tienda))
    await db_thread(db.delete_tienda_bin, tienda)
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
    bins = await db_thread(db.bins_por_tienda, tienda)
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
            callback_data=f"rmv_del_bin:{b['id']}",
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
    b = await db_thread(db.get_bin, bin_id)
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
    b = await db_thread(db.get_bin, bin_id)
    if b:
        await db_thread(db.delete_bin, bin_id)
        await q.edit_message_text(
            f"✅ *BIN eliminado*\n\n"
            f"💳 `{b['bin']}` de *{safe(b['tienda'])}*",
            parse_mode="Markdown",
            reply_markup=kb_volver_bins(),
        )
    else:
        await q.edit_message_text("❌ BIN no encontrado.", reply_markup=kb_volver_bins())
    return ST_MENU
