"""Flujo de captura de un nuevo vuelo: foto → pasajeros → cobrado → publicar."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from currency import parsear_monto, formato_mxn
from formatters import safe, nombre_usuario
from notifications import notificar_otros_foto
from utils import autorizado, rechazar, db_thread, reply_clean, remember_panel
from keyboards import kb_cancelar, kb_aceptar_vuelo
from states import ST_VC_FOTO, ST_VC_PASAJEROS, ST_VC_COBRADO, ST_VC_CONFIRMAR, ST_MENU

TOTAL_PASOS = 3


def _header(paso: int, titulo_campo: str, ud: dict) -> str:
    capturados = []
    if "vc_foto" in ud:
        capturados.append("✅ Captura recibida")
    if "vc_pasajeros" in ud:
        n = ud["vc_pasajeros"].count("\n") + 1 if ud["vc_pasajeros"] else 0
        capturados.append(f"✅ Datos de pasajeros ({n} línea/s)")

    cap_txt = "\n".join(capturados)
    sep = "\n" if cap_txt else ""
    return (
        f"✈️ *Nuevo Vuelo*  ·  Paso {paso}/{TOTAL_PASOS}\n"
        f"{cap_txt}{sep}\n"
        f"*{titulo_campo}*"
    )


# ─────────────────────────── INICIO ──────────────────────────────────────────

async def vc_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()

    msg = await q.edit_message_text(
        _header(1, "Captura del vuelo", ctx.user_data) +
        "\n_Envía una imagen donde se vea la *ruta* y *fecha* del vuelo._\n"
        "_(screenshot del buscador, itinerario, etc.)_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_VC_FOTO


# ─────────────────────────── PASO 1: Foto ────────────────────────────────────

async def vc_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.photo:
        await reply_clean(update, ctx,
            "❌ Necesito una *imagen* (no un archivo ni texto). "
            "Envía la captura del vuelo:",
            parse_mode="Markdown",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_FOTO

    # Telegram manda varias resoluciones; tomamos la mayor (última).
    file_id = update.message.photo[-1].file_id
    ctx.user_data["vc_foto"] = file_id

    await reply_clean(update, ctx,
        _header(2, "Pasajeros y notas", ctx.user_data) +
        "\n_Nombre completo + fecha de nacimiento (DD/MM/AA) por pasajero._\n"
        "_Si hay extras (equipaje, asientos, preferencias), agrégalos al final._\n\n"
        "_Ej:_\n"
        "_`Juan Pérez García 15/03/85`_\n"
        "_`María López Ruiz 22/06/90`_\n"
        "_`2 maletas documentadas + asientos juntos`_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_PASAJEROS


async def vc_foto_no_es_imagen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Atrapa texto/documentos cuando se espera la foto."""
    await reply_clean(update, ctx,
        "❌ Necesito una *imagen* (envíala como foto, no como archivo). "
        "Envía la captura del vuelo:",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_FOTO


# ─────────────────────────── PASO 2: Pasajeros + Extras ──────────────────────

async def vc_pasajeros(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    if len(txt) < 5 or len(txt) > 2000:
        await reply_clean(update, ctx,
            "❌ Texto inválido (mínimo 5, máximo 2000 caracteres). Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_PASAJEROS

    ctx.user_data["vc_pasajeros"] = txt
    await reply_clean(update, ctx,
        _header(3, "Total cobrado al cliente", ctx.user_data) +
        "\n_Ej: `5500` o `5,500.50`  (siempre en MXN)_",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    return ST_VC_COBRADO


# ─────────────────────────── PASO 3: Cobrado ─────────────────────────────────

async def vc_cobrado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = parsear_monto(update.message.text)
    except ValueError as e:
        await reply_clean(update, ctx,
            f"❌ {e}",
            reply_markup=kb_cancelar(),
        )
        return ST_VC_COBRADO

    ctx.user_data["vc_cobrado"] = monto
    return await _mostrar_confirmacion(update, ctx)


# ─────────────────────────── CONFIRMACIÓN ────────────────────────────────────

async def _mostrar_confirmacion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ud = ctx.user_data

    resumen = (
        "📋 *Confirmar Nuevo Vuelo*\n"
        "─────────────────────────────\n"
        f"📷 Captura: ✅\n"
        f"👥 Pasajeros / notas:\n{safe(ud['vc_pasajeros'])}\n"
        f"💰 Total cobrado: *{formato_mxn(ud['vc_cobrado'])}*\n"
        "─────────────────────────────\n"
        "_¿Publicar este vuelo a los socios?_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Publicar vuelo", callback_data="vc_publicar")],
        [InlineKeyboardButton("❌  Cancelar",        callback_data="menu")],
    ])

    await reply_clean(update, ctx, resumen,
        parse_mode="Markdown", reply_markup=kb,
    )
    return ST_VC_CONFIRMAR


# ─────────────────────────── PUBLICAR ────────────────────────────────────────

async def vc_publicar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("Publicando…")

    ud = ctx.user_data
    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(
        db.crear_vuelo,
        creado_por=nombre,
        creado_por_id=tg_user.id,
        foto_file_id=ud["vc_foto"],
        pasajeros=ud["vc_pasajeros"],
        monto_cobrado=ud["vc_cobrado"],
    )
    vid = vuelo["id"]
    ctx.user_data.clear()

    # Notificar a los demás socios con la captura como foto + caption.
    caption = (
        "🔔 *Nuevo Vuelo Disponible*\n"
        "─────────────────────────────\n"
        f"*#{vid}*\n"
        f"💰 *{formato_mxn(vuelo['monto_cobrado'])}*\n"
        f"👤 Alta: {safe(vuelo['creado_por'])}\n\n"
        f"👥 {safe(vuelo['pasajeros'])}"
    )
    await notificar_otros_foto(
        update.get_bot(), tg_user.id,
        photo=vuelo["foto_file_id"],
        caption=caption,
        parse_mode="Markdown",
        reply_markup=kb_aceptar_vuelo(vid),
    )

    await q.edit_message_text(
        f"✅ *Vuelo #{vid} publicado*\n\n"
        f"_Se notificó a los demás socios._\n"
        f"_Cualquiera puede tomarlo desde 📋 Pendientes._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠  Menú Principal", callback_data="menu"),
        ]]),
    )
    return ST_MENU
