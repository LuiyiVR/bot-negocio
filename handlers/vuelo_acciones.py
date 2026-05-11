"""Acciones sobre un vuelo: tomar, soltar, completar, cancelar, caído."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import db
from config import ESTADO_EN_PROCESO, ESTADO_CAIDO, ESTADO_COMPLETADO
from formatters import safe, fmt_vuelo, nombre_usuario
from currency import formato_mxn
from notifications import notificar_otros, notificar_otros_foto
from utils import (
    autorizado, rechazar, db_thread, edit_q, edit_to_text,
    reply_clean, remember_panel,
)
from keyboards import (
    kb_volver, kb_cancelar, kb_confirmar_cancelar,
    kb_acciones_vuelo, kb_aceptar_vuelo, kb_caido_opciones,
    kb_duracion_sacado,
)
from states import ST_MENU, ST_VAC_COMPLETAR_FOTO


def _kb_volver_con_acciones(vuelo, user_id: int):
    filas = kb_acciones_vuelo(vuelo, user_id)
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")])
    return InlineKeyboardMarkup(filas)


def _resumen_corto(v) -> str:
    """Línea corta para avisos: usa ruta si existe, si no creador + monto."""
    aero = (v["aerolinea"] or "").strip()
    ori  = (v["origen"]    or "").strip()
    des  = (v["destino"]   or "").strip()
    if aero or ori or des:
        partes = []
        if aero:
            partes.append(f"✈️ {safe(aero)}")
        if ori or des:
            partes.append(f"{safe(ori)} → {safe(des)}")
        ruta = "  ·  ".join(partes)
        fv = (v["fecha_vuelo"] or "").strip()
        if fv:
            ruta += f"\n📅 {safe(fv)}"
        return ruta
    return f"📷 Vuelo #{v['id']} · 👤 {safe(v['creado_por'])}"


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
        actual = await db_thread(db.get_vuelo, vid)
        if not actual:
            await edit_q(q, "❌ Vuelo no encontrado.", reply_markup=kb_volver())
            return ST_MENU
        msg = {
            "en_proceso": f"ya lo tomó *{safe(actual['aceptado_por'])}*",
            "completado": "ya está completado",
            "cancelado":  "fue cancelado",
            "caido":      f"está marcado como caído por *{safe(actual['aceptado_por'])}*",
        }.get(actual["estado"], actual["estado"])
        await edit_q(q,
            f"⚠️ El vuelo *#{vid}* {msg}.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"🔄 *Vuelo #{vid} en proceso*\n\n"
        f"*{safe(nombre)}* tomó el vuelo:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await edit_q(q,
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
        await edit_q(q,
            f"⚠️ No puedes soltar el vuelo *#{vid}* (no es tuyo o ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"🔓 *Vuelo #{vid} liberado*\n\n"
        f"*{safe(nombre)}* soltó el vuelo, vuelve a estar disponible:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}"
    )
    await notificar_otros(
        update.get_bot(), tg_user.id, aviso,
        parse_mode="Markdown", reply_markup=kb_aceptar_vuelo(vid),
    )

    await edit_q(q,
        f"🔓 *Vuelo #{vid} soltado*\n\n"
        f"Vuelve a estar disponible para los demás socios.",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  COMPLETAR (requiere captura del número de confirmación)
# ═════════════════════════════════════════════════════════════════════════════

async def vac_completar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Punto de entrada de completar: valida y pide la captura de confirmación."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    vuelo = await db_thread(db.get_vuelo, vid)
    if not vuelo:
        await edit_q(q, "❌ Vuelo no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    if vuelo["estado"] not in (ESTADO_EN_PROCESO, ESTADO_CAIDO):
        await edit_q(q,
            f"⚠️ El vuelo *#{vid}* no se puede completar en su estado actual "
            f"(_{vuelo['estado']}_).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    if vuelo["aceptado_por_id"] != tg_user.id:
        await edit_q(q,
            f"🚫 Solo *{safe(vuelo['aceptado_por'])}* puede completar este vuelo.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    ctx.user_data["completar_vid"] = vid
    msg = await edit_to_text(q,
        f"🧾 *Completar vuelo #{vid}*\n"
        "─────────────────────────────\n"
        "_Sube la *captura* donde se vea claramente el *número de confirmación*._\n"
        "_Se compartirá con todos los socios como comprobante._",
        parse_mode="Markdown",
        reply_markup=kb_cancelar(),
    )
    remember_panel(ctx, msg)
    return ST_VAC_COMPLETAR_FOTO


async def vac_completar_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Recibe la captura de confirmación y completa el vuelo."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    if not update.message or not update.message.photo:
        await reply_clean(update, ctx,
            "❌ Necesito una *imagen* con el número de confirmación visible. "
            "Envíala como foto (no como archivo):",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_VAC_COMPLETAR_FOTO

    vid = ctx.user_data.get("completar_vid")
    if not vid:
        await reply_clean(update, ctx,
            "❌ Sesión expirada, vuelve a iniciar el proceso desde Mis Vuelos.",
            reply_markup=kb_volver(),
        )
        return ST_MENU

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)
    foto_file_id = update.message.photo[-1].file_id

    vuelo = await db_thread(db.completar_vuelo, vid, tg_user.id, foto_file_id)
    if not vuelo:
        await reply_clean(update, ctx,
            f"⚠️ No se pudo completar el vuelo *#{vid}* "
            f"(ya cambió de estado o no es tuyo).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    ctx.user_data.pop("completar_vid", None)

    # Borra el mensaje de la foto del usuario (queda solo el panel del bot).
    try:
        await update.message.delete()
    except Exception:
        pass

    # Notificar a los demás con la captura.
    caption = (
        f"✅ *Vuelo #{vid} completado*\n\n"
        f"*{safe(nombre)}* sacó el vuelo:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 *Ingreso: {formato_mxn(vuelo['monto_cobrado'])}*\n\n"
        f"🧾 _Comprobante con número de confirmación:_"
    )
    await notificar_otros_foto(
        update.get_bot(), tg_user.id,
        photo=foto_file_id, caption=caption, parse_mode="Markdown",
    )

    # Editar el panel del bot con el resultado + pregunta de expiración.
    last = ctx.user_data.get("_last_msg")
    texto = (
        "✅ *Vuelo completado*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo)}\n"
        "─────────────────────────────\n"
        f"💵 Ingreso registrado: *{formato_mxn(vuelo['monto_cobrado'])}*\n"
        "🧾 Captura del número de confirmación enviada a los socios.\n\n"
        "🗑 *¿En cuánto tiempo quieres que se quite de* 🎫 *Vuelos Sacados?*"
    )
    kb = kb_duracion_sacado(vid)
    if last:
        try:
            await update.get_bot().edit_message_text(
                chat_id=last[0], message_id=last[1],
                text=texto, parse_mode="Markdown",
                reply_markup=kb,
            )
            return ST_MENU
        except Exception:
            pass

    await update.effective_chat.send_message(
        texto, parse_mode="Markdown", reply_markup=kb,
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  VOLADO (quita el vuelo de la lista, sin tocar la contabilidad)
# ═════════════════════════════════════════════════════════════════════════════

async def vac_volado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    vuelo = await db_thread(db.marcar_volado, vid, tg_user.id)
    if not vuelo:
        await edit_q(q,
            f"⚠️ No puedes marcar como volado el vuelo *#{vid}* "
            f"(no es tuyo o ya no está completado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    await edit_q(q,
        f"✈️ *Vuelo #{vid} marcado como volado*\n\n"
        f"_Se quitó de_ 🎫 *Vuelos Sacados*. _El ingreso de "
        f"{formato_mxn(vuelo['monto_cobrado'])} sigue contando en las ganancias._",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  EXPIRACIÓN DE VUELOS SACADOS (cuánto tiempo se ven en la lista)
# ═════════════════════════════════════════════════════════════════════════════

async def vac_expira_sacado(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    try:
        _, vid_s, horas_s = q.data.split(":")
        vid, horas = int(vid_s), int(horas_s)
    except (ValueError, IndexError):
        await edit_q(q, "❌ Opción inválida.", reply_markup=kb_volver())
        return ST_MENU

    tg_user = update.effective_user
    vuelo = await db_thread(db.set_expiracion_sacado, vid, tg_user.id, horas)
    if not vuelo:
        await edit_q(q,
            f"⚠️ No se pudo configurar la expiración del vuelo *#{vid}* "
            f"(no es tuyo o ya no está completado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    if horas % 24 == 0 and horas >= 24:
        legible = f"{horas // 24} día{'s' if horas != 24 else ''}"
    else:
        legible = f"{horas} hora{'s' if horas != 1 else ''}"

    await edit_q(q,
        f"🗑 *Vuelo #{vid}*\n\n"
        f"Se quitará automáticamente de 🎫 *Vuelos Sacados* en *{legible}* "
        f"(el {vuelo['fecha_expira_sacado'][:16]}).",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  VUELO CAÍDO (en proceso → pregunta: liberar o mantener para mí)
# ═════════════════════════════════════════════════════════════════════════════

async def vac_caido_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    vuelo = await db_thread(db.get_vuelo, vid)
    if not vuelo:
        await edit_q(q, "❌ Vuelo no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    if vuelo["estado"] not in (ESTADO_EN_PROCESO, ESTADO_COMPLETADO):
        await edit_q(q,
            f"⚠️ El vuelo *#{vid}* no se puede marcar como caído en su estado "
            f"actual (_{vuelo['estado']}_).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    if vuelo["aceptado_por_id"] != update.effective_user.id:
        await edit_q(q,
            f"🚫 Solo *{safe(vuelo['aceptado_por'])}* puede marcar caído este vuelo.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso_extra = ""
    if vuelo["estado"] == ESTADO_COMPLETADO:
        aviso_extra = (
            "\n\n⚠️ _Este vuelo ya estaba completado. Al marcarlo como caído "
            "su ingreso *dejará de contar* en la ganancia y se borrará la "
            "captura del número de confirmación._"
        )

    await edit_q(q,
        f"💥 *Vuelo #{vid} caído*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo, breve=True)}\n"
        "─────────────────────────────\n"
        "_¿Qué prefieres hacer?_\n\n"
        "🔓 *Liberar para todos* — vuelve a quedar disponible como pendiente.\n\n"
        "📌 *Mantener para mí* — sigue reservado a tu nombre para que lo "
        "vuelvas a intentar. Su monto *no se contará* como ganancia hasta "
        "que confirmes que lo sacaste."
        f"{aviso_extra}",
        parse_mode="Markdown",
        reply_markup=kb_caido_opciones(vid),
    )
    return ST_MENU


async def vac_caido_soltar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """El usuario eligió liberar el vuelo caído (en proceso → pendiente)."""
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
        # Pudo haber pasado a caido o estar completado — intentar las otras rutas.
        vuelo = await db_thread(db.liberar_caido, vid, tg_user.id)
    if not vuelo:
        vuelo = await db_thread(db.soltar_completado, vid, tg_user.id)

    if not vuelo:
        await edit_q(q,
            f"⚠️ No puedes liberar el vuelo *#{vid}* (ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"💥🔓 *Vuelo #{vid} cayó y fue liberado*\n\n"
        f"*{safe(nombre)}* marcó el vuelo como caído y lo liberó:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}\n\n"
        f"_Vuelve a estar disponible para todos._"
    )
    await notificar_otros(
        update.get_bot(), tg_user.id, aviso,
        parse_mode="Markdown", reply_markup=kb_aceptar_vuelo(vid),
    )

    await edit_q(q,
        f"🔓 *Vuelo #{vid} liberado*\n\n"
        f"El vuelo cayó y queda disponible para los demás socios.",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU


async def vac_caido_mantener(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """El usuario decide mantener el vuelo caído reservado para él."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(db.marcar_caido, vid, tg_user.id)
    if not vuelo:
        await edit_q(q,
            f"⚠️ No puedes marcar caído el vuelo *#{vid}* (ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"💥 *Vuelo #{vid} caído*\n\n"
        f"*{safe(nombre)}* marcó el vuelo como caído pero lo mantiene "
        f"reservado para volver a intentarlo:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}\n\n"
        f"_La ganancia de este vuelo no se contará hasta que confirme que lo sacó._"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await edit_q(q,
        f"💥 *Vuelo #{vid} marcado como caído*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo)}\n"
        "─────────────────────────────\n"
        "_Sigue reservado a tu nombre. Cuando logres sacarlo, márcalo como "
        "*Completar* y sube la captura del número de confirmación._\n"
        "_Si decides no intentarlo más, libéralo para que otro lo tome._",
        parse_mode="Markdown",
        reply_markup=_kb_volver_con_acciones(vuelo, tg_user.id),
    )
    return ST_MENU


async def vac_caido_liberar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Libera un vuelo que ya está en estado caído (caído → pendiente)."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    vid = int(q.data.split(":")[1])

    tg_user = update.effective_user
    nombre = nombre_usuario(tg_user)

    vuelo = await db_thread(db.liberar_caido, vid, tg_user.id)
    if not vuelo:
        await edit_q(q,
            f"⚠️ No puedes liberar el vuelo *#{vid}* (no es tuyo o ya cambió de estado).",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"🔓 *Vuelo #{vid} liberado*\n\n"
        f"*{safe(nombre)}* liberó un vuelo que tenía caído, vuelve a estar disponible:\n"
        f"{_resumen_corto(vuelo)}\n"
        f"💰 {formato_mxn(vuelo['monto_cobrado'])}"
    )
    await notificar_otros(
        update.get_bot(), tg_user.id, aviso,
        parse_mode="Markdown", reply_markup=kb_aceptar_vuelo(vid),
    )

    await edit_q(q,
        f"🔓 *Vuelo #{vid} liberado*\n\n"
        f"Vuelve a estar disponible para los demás socios.",
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
        await edit_q(q, "❌ Vuelo no encontrado.", reply_markup=kb_volver())
        return ST_MENU

    user_id = update.effective_user.id
    estado = vuelo["estado"]

    if estado == "cancelado":
        await edit_q(q,
            f"⚠️ El vuelo *#{vid}* ya está cancelado.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    if estado in ("pendiente", "en_proceso", "caido"):
        if vuelo["creado_por_id"] != user_id:
            await edit_q(q,
                "🚫 *No autorizado*\n\n"
                f"Solo *{safe(vuelo['creado_por'])}* (quien creó el vuelo) puede cancelarlo "
                f"mientras esté _{estado}_.",
                parse_mode="Markdown", reply_markup=kb_volver(),
            )
            return ST_MENU
    elif estado == "completado":
        if vuelo["aceptado_por_id"] != user_id:
            await edit_q(q,
                "🚫 *No autorizado*\n\n"
                f"Solo *{safe(vuelo['aceptado_por'])}* (quien sacó el vuelo) puede cancelarlo "
                f"después de completado.",
                parse_mode="Markdown", reply_markup=kb_volver(),
            )
            return ST_MENU

    await edit_q(q,
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
        await edit_q(q,
            f"❌ {error or 'No se pudo cancelar.'}",
            reply_markup=kb_volver(),
        )
        return ST_MENU

    aviso = (
        f"❌ *Vuelo #{vid} cancelado*\n\n"
        f"*{safe(nombre)}* canceló el vuelo:\n"
        f"{_resumen_corto(vuelo)}"
    )
    await notificar_otros(update.get_bot(), tg_user.id, aviso, parse_mode="Markdown")

    await edit_q(q,
        "❌ *Vuelo cancelado*\n"
        "─────────────────────────────\n"
        f"{fmt_vuelo(vuelo, breve=True)}",
        parse_mode="Markdown",
        reply_markup=kb_volver(),
    )
    return ST_MENU
