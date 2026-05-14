"""Reportes: Balance del Mes, Reporte Semanal, descargables."""
import io
import re
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes, ConversationHandler

import db
from config import ALLOWED_IDS
from currency import formato_mxn
from formatters import safe, fmt_fecha_corta, nombre_usuario
from notifications import notificar_a
from utils import autorizado, rechazar, db_thread, reply_clean
from keyboards import kb_volver, kb_cancelar, kb_checkout_confirmar
from states import ST_MENU, ST_REP_OTRO_MES


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _resumen_vuelos(vuelos: list) -> dict:
    """Cuenta y suma vuelos por estado.

    Los cancelados se reportan solo en `cancelados` (informativo) y no
    cuentan en `total` ni en ningún cálculo de ingresos/tasa de éxito.

    Los caídos cuentan en `total` y en `caidos`, pero su monto NO entra a
    `ingreso_completados`; queda en `monto_caido` (dinero "atorado" que solo
    se contará como ganancia cuando el usuario confirme que sacó el vuelo).
    """
    r = {
        "total":        0,    # solo activos (no cancelados)
        "pendientes":   0,
        "en_proceso":   0,
        "completados":  0,
        "caidos":       0,
        "cancelados":   0,    # solo informativo
        "ingreso_completados": 0.0,
        "monto_pendiente":     0.0,  # vuelos pendientes + en_proceso
        "monto_caido":         0.0,  # vuelos caídos sin completar
        "por_socio":           {},   # nombre -> {"vuelos": n, "monto": m}
    }
    for v in vuelos:
        e = v["estado"]
        m = v["monto_cobrado"]
        if e == "cancelado":
            r["cancelados"] += 1
            continue
        r["total"] += 1
        if e == "pendiente":
            r["pendientes"] += 1
            r["monto_pendiente"] += m
        elif e == "en_proceso":
            r["en_proceso"] += 1
            r["monto_pendiente"] += m
        elif e == "caido":
            r["caidos"] += 1
            r["monto_caido"] += m
        elif e == "completado":
            r["completados"] += 1
            r["ingreso_completados"] += m
            nombre = (v["aceptado_por"] or "—").strip() or "—"
            slot = r["por_socio"].setdefault(nombre, {"vuelos": 0, "monto": 0.0})
            slot["vuelos"] += 1
            slot["monto"] += m
    return r


def _bloque_por_socio(r: dict) -> str:
    """Líneas con desglose de vuelos completados por socio (ordenado desc)."""
    if not r["por_socio"]:
        return ""
    filas = sorted(
        r["por_socio"].items(),
        key=lambda kv: (kv[1]["vuelos"], kv[1]["monto"]),
        reverse=True,
    )
    lineas = ["*🏆 Vuelos sacados por socio*"]
    for nombre, info in filas:
        lineas.append(
            f"  • {safe(nombre)}: {info['vuelos']}  "
            f"({formato_mxn(info['monto'])})"
        )
    return "\n".join(lineas) + "\n\n"


def _gastos_fondo_rango(gastos: list, desde_iso: str, hasta_iso: str | None = None) -> tuple[list, float]:
    """Filtra gastos por rango y devuelve (lista, total)."""
    filtrados = []
    for g in gastos:
        f = g["fecha"]
        if f >= desde_iso and (hasta_iso is None or f <= hasta_iso):
            filtrados.append(g)
    total = sum(g["monto"] for g in filtrados)
    return filtrados, total


def _tasa_exito(r: dict) -> float:
    """% de vuelos activos que ya están completados (cancelados no penalizan)."""
    if r["total"] == 0:
        return 0.0
    return (r["completados"] / r["total"]) * 100


# ═════════════════════════════════════════════════════════════════════════════
#  BALANCE DEL MES
# ═════════════════════════════════════════════════════════════════════════════

async def rep_mes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    ahora = datetime.now()
    await _render_balance_mes(q, ahora.year, ahora.month)
    return ST_MENU


async def rep_otro_mes_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()
    msg = await q.edit_message_text(
        "🗓 *Otro mes*\n\nEscribe el mes en formato `MM/AAAA`\n_Ej: `03/2026`_",
        parse_mode="Markdown", reply_markup=kb_cancelar(),
    )
    ctx.user_data["_last_msg"] = (msg.chat_id, msg.message_id)
    return ST_REP_OTRO_MES


async def rep_otro_mes_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    m = re.match(r"^(\d{1,2})[/\-\.](\d{4})$", txt)
    if not m:
        await reply_clean(update, ctx,
            "❌ Formato inválido. Usa `MM/AAAA` (ej: `03/2026`):",
            parse_mode="Markdown", reply_markup=kb_cancelar(),
        )
        return ST_REP_OTRO_MES

    mes, anio = int(m.group(1)), int(m.group(2))
    if not 1 <= mes <= 12 or anio < 2024 or anio > 2100:
        await reply_clean(update, ctx,
            "❌ Mes o año fuera de rango. Intenta de nuevo:",
            reply_markup=kb_cancelar(),
        )
        return ST_REP_OTRO_MES

    # Borrar mensaje del usuario y editar el panel
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

    last = ctx.user_data.get("_last_msg")
    if last:
        from telegram import Bot
        bot = update.get_bot()
        # Construimos un q-like adapter editando directamente
        from types import SimpleNamespace
        async def _edit(text, **kw):
            return await bot.edit_message_text(
                chat_id=last[0], message_id=last[1], text=text, **kw,
            )
        q_like = SimpleNamespace(edit_message_text=_edit, message=None)
        await _render_balance_mes(q_like, anio, mes)
    return ST_MENU


async def _render_balance_mes(q, anio: int, mes: int):
    vuelos = await db_thread(db.vuelos_mes, anio, mes)
    gastos = await db_thread(db.gastos_fondo)

    desde = f"{anio}-{mes:02d}-01"
    if mes == 12:
        hasta = f"{anio + 1}-01-01"
    else:
        hasta = f"{anio}-{mes + 1:02d}-01"
    gastos_mes, gastos_total = _gastos_fondo_rango(gastos, desde, hasta)

    r = _resumen_vuelos(vuelos)
    ingresos = r["ingreso_completados"]
    ganancia_neta = ingresos - gastos_total

    socios = await db_thread(db.get_socios)
    n_socios = max(1, len(socios))
    parte = ganancia_neta / n_socios

    inv_inicial = await db_thread(db.get_inversion_inicial)
    fondo_total_gastado = await db_thread(db.total_gastado_fondo)
    saldo_fondo = inv_inicial - fondo_total_gastado

    nombre_mes = datetime(anio, mes, 1).strftime("%B %Y").capitalize()

    texto = (
        f"📅 *Balance — {nombre_mes}*\n"
        f"─────────────────────────────\n"
        f"*✈️ Vuelos del mes*\n"
        f"  • Creados:        {r['total']}\n"
        f"  • Completados:    {r['completados']}\n"
        f"  • Caídos:         {r['caidos']} 💥\n"
        f"  • Cancelados:     {r['cancelados']}\n"
        f"  • Pendientes:     {r['pendientes']}\n"
        f"  • En proceso:     {r['en_proceso']}\n"
        f"  • Tasa de éxito:  {_tasa_exito(r):.1f}%\n"
        f"\n"
        f"*💵 Resultado financiero*\n"
        f"  • Ingresos:       *{formato_mxn(ingresos)}*\n"
        f"  • Egresos fondo:  −{formato_mxn(gastos_total)}\n"
        f"  • Ganancia neta:  *{formato_mxn(ganancia_neta)}*\n"
        f"\n"
        f"💥 _Atorado en caídos (no cuenta hasta sacarlos):_ "
        f"{formato_mxn(r['monto_caido'])}\n"
        f"\n"
        f"{_bloque_por_socio(r)}"
        f"*👥 Reparto por socio* ({n_socios})\n"
        f"  • Cada uno: *{formato_mxn(parte)}*\n"
        f"\n"
        f"*🏦 Fondo de inversión*\n"
        f"  • Saldo actual: {formato_mxn(saldo_fondo)}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥  Descargar TXT", callback_data=f"rep_dl_mes:{anio}-{mes:02d}")],
        [InlineKeyboardButton("🗓  Otro mes",       callback_data="rep_otro_mes")],
        [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
    ])
    await q.edit_message_text(texto, parse_mode="Markdown", reply_markup=kb)


# ═════════════════════════════════════════════════════════════════════════════
#  REPORTE SEMANAL
# ═════════════════════════════════════════════════════════════════════════════

def _rango_semana_actual() -> tuple[datetime, datetime, str]:
    """Devuelve (lunes_dt, hoy_dt, desde_iso). desde_iso considera el último
    checkout si es posterior al lunes."""
    hoy_dt = datetime.now()
    lunes_dt = hoy_dt - timedelta(days=hoy_dt.weekday())
    desde_iso = lunes_dt.strftime("%Y-%m-%d 00:00:00")
    ultimo = db.get_ultimo_checkout()
    if ultimo and ultimo > desde_iso:
        desde_iso = ultimo
    return lunes_dt, hoy_dt, desde_iso


def _texto_reporte_semana(r: dict, gastos_total: float, n_socios: int,
                          desde_dt: datetime, hasta_dt: datetime,
                          titulo: str = "📊 *Reporte Semanal*") -> str:
    ingresos = r["ingreso_completados"]
    ganancia_neta = ingresos - gastos_total
    parte = ganancia_neta / n_socios
    return (
        f"{titulo}\n"
        f"_{desde_dt.strftime('%d/%m')} – {hasta_dt.strftime('%d/%m/%Y')}_\n"
        f"─────────────────────────────\n"
        f"*✈️ Actividad*\n"
        f"  • Vuelos creados:  {r['total']}\n"
        f"  • Sacados:          *{r['completados']}* ✅\n"
        f"  • Caídos:           {r['caidos']} 💥\n"
        f"  • Cancelados:       {r['cancelados']} ❌\n"
        f"  • Pendientes:       {r['pendientes']} ⏳\n"
        f"  • En proceso:       {r['en_proceso']} 🔄\n"
        f"  • Tasa de éxito:    {_tasa_exito(r):.1f}%\n"
        f"\n"
        f"{_bloque_por_socio(r)}"
        f"*💵 Resultado*\n"
        f"  • Ingresos:        *{formato_mxn(ingresos)}*\n"
        f"  • Egresos fondo:   −{formato_mxn(gastos_total)}\n"
        f"  • Ganancia neta:   *{formato_mxn(ganancia_neta)}*\n"
        f"  • Por socio:        *{formato_mxn(parte)}*\n"
        f"\n"
        f"💰 _Pendiente por cobrar:_ {formato_mxn(r['monto_pendiente'])}\n"
        f"💥 _Atorado en caídos:_   {formato_mxn(r['monto_caido'])}"
    )


async def rep_semana(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    desde_dt, hasta_dt, desde_iso = _rango_semana_actual()

    vuelos = await db_thread(db.vuelos_semana)
    gastos_todos = await db_thread(db.gastos_fondo)
    _, gastos_total = _gastos_fondo_rango(gastos_todos, desde_iso)

    r = _resumen_vuelos(vuelos)
    socios = await db_thread(db.get_socios)
    n_socios = max(1, len(socios))

    texto = _texto_reporte_semana(r, gastos_total, n_socios, desde_dt, hasta_dt)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥  Descargar TXT", callback_data="rep_dl_semana")],
        [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
    ])
    await q.edit_message_text(texto, parse_mode="Markdown", reply_markup=kb)
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  DESCARGAS TXT
# ═════════════════════════════════════════════════════════════════════════════

def _txt_vuelo(v) -> str:
    aero = v["aerolinea"] or ""
    ori  = v["origen"]    or ""
    des  = v["destino"]   or ""
    fv   = v["fecha_vuelo"] or ""
    hr   = v["horario"]   or ""
    foto_marca = "[con captura] " if (v["foto_file_id"] or "") else ""

    lineas = [f"#{v['id']} · {foto_marca}{v['estado'].upper()}"]
    if aero or ori or des:
        lineas.append(f"  {aero} · {ori} → {des}".rstrip(" ·"))
    if fv or hr:
        lineas.append(f"  {fv}  {hr}".rstrip())
    lineas += [
        f"  Pasajeros: {v['pasajeros']}",
        f"  Extras:    {v['extras'] or '—'}",
        f"  Cobrado:   ${v['monto_cobrado']:,.2f} MXN",
        f"  Alta:      {v['creado_por']}  ({fmt_fecha_corta(v['fecha_creacion'])})",
        f"  Tomado:    {v['aceptado_por'] or '—'}",
        f"  Completado:{fmt_fecha_corta(v['fecha_completado'])}",
        f"  Cancelado: {v['cancelado_por'] or '—'}  ({fmt_fecha_corta(v['fecha_cancelado'])})",
    ]
    return "\n".join(lineas) + "\n"


def _construir_txt(titulo: str, vuelos: list, gastos: list, resumen: dict, gastos_total: float) -> bytes:
    out = io.StringIO()
    out.write("=" * 60 + "\n")
    out.write(f"{titulo}\n")
    out.write("=" * 60 + "\n\n")

    out.write(f"VUELOS ({resumen['total']}):\n")
    out.write(f"  Completados: {resumen['completados']}\n")
    out.write(f"  Caidos:      {resumen['caidos']}\n")
    out.write(f"  Cancelados:  {resumen['cancelados']}\n")
    out.write(f"  Pendientes:  {resumen['pendientes']}\n")
    out.write(f"  En proceso:  {resumen['en_proceso']}\n")
    out.write(f"  Ingresos:    ${resumen['ingreso_completados']:,.2f} MXN\n")
    out.write(f"  Pendiente:   ${resumen['monto_pendiente']:,.2f} MXN\n")
    out.write(f"  Atorado caidos: ${resumen['monto_caido']:,.2f} MXN\n")
    out.write(f"  Egresos fondo: ${gastos_total:,.2f} MXN\n")
    out.write(f"  Ganancia neta: ${resumen['ingreso_completados'] - gastos_total:,.2f} MXN\n\n")

    if resumen.get("por_socio"):
        out.write("VUELOS SACADOS POR SOCIO:\n")
        filas = sorted(
            resumen["por_socio"].items(),
            key=lambda kv: (kv[1]["vuelos"], kv[1]["monto"]),
            reverse=True,
        )
        for nombre, info in filas:
            out.write(f"  {nombre}: {info['vuelos']}  (${info['monto']:,.2f} MXN)\n")
        out.write("\n")

    out.write("-" * 60 + "\n")
    out.write("DETALLE DE VUELOS\n")
    out.write("-" * 60 + "\n")
    for v in vuelos:
        out.write(_txt_vuelo(v) + "\n")

    if gastos:
        out.write("-" * 60 + "\n")
        out.write("GASTOS DEL FONDO\n")
        out.write("-" * 60 + "\n")
        for g in gastos:
            out.write(
                f"#{g['id']}  {fmt_fecha_corta(g['fecha'])}  "
                f"${g['monto']:,.2f}  {g['concepto']}  ({g['registrado_por']})\n"
            )

    return out.getvalue().encode("utf-8")


async def rep_dl_mes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer("Generando…")
    raw = q.data.split(":")[1]  # "AAAA-MM"
    anio, mes = raw.split("-")
    anio, mes = int(anio), int(mes)

    vuelos = await db_thread(db.vuelos_mes, anio, mes)
    gastos_todos = await db_thread(db.gastos_fondo)
    desde = f"{anio}-{mes:02d}-01"
    hasta = f"{anio}-{mes + 1:02d}-01" if mes < 12 else f"{anio + 1}-01-01"
    gastos_mes, gastos_total = _gastos_fondo_rango(gastos_todos, desde, hasta)

    titulo = f"BALANCE — {datetime(anio, mes, 1).strftime('%B %Y').upper()}"
    contenido = _construir_txt(titulo, vuelos, gastos_mes, _resumen_vuelos(vuelos), gastos_total)
    nombre = f"balance_{anio}-{mes:02d}.txt"

    await q.message.reply_document(
        document=InputFile(io.BytesIO(contenido), filename=nombre),
        caption=f"📥 {titulo.title()}",
    )
    return ST_MENU


async def rep_dl_semana(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer("Generando…")

    desde_dt, hasta_dt, desde_iso = _rango_semana_actual()

    vuelos = await db_thread(db.vuelos_semana)
    gastos_todos = await db_thread(db.gastos_fondo)
    gastos_sem, gastos_total = _gastos_fondo_rango(gastos_todos, desde_iso)

    titulo = f"REPORTE SEMANAL — {desde_dt.strftime('%d/%m')} a {hasta_dt.strftime('%d/%m/%Y')}"
    contenido = _construir_txt(titulo, vuelos, gastos_sem, _resumen_vuelos(vuelos), gastos_total)
    nombre = f"semana_{hasta_dt.strftime('%Y-%m-%d')}.txt"

    await q.message.reply_document(
        document=InputFile(io.BytesIO(contenido), filename=nombre),
        caption=f"📥 {titulo}",
    )
    return ST_MENU


# ═════════════════════════════════════════════════════════════════════════════
#  CHECKOUT SEMANAL (solo sábados)
# ═════════════════════════════════════════════════════════════════════════════

def _es_sabado_y_pendiente() -> bool:
    hoy = datetime.now()
    if hoy.weekday() != 5:
        return False
    ultimo = db.get_ultimo_checkout()
    if not ultimo:
        return True
    return ultimo < hoy.strftime("%Y-%m-%d 00:00:00")


async def checkout_inicio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra el reporte semanal final con un botón para confirmar el cierre."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    if not await db_thread(_es_sabado_y_pendiente):
        await q.edit_message_text(
            "ℹ️ El cierre semanal solo está disponible los *sábados* "
            "y solo una vez por semana.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    desde_dt, hasta_dt, desde_iso = _rango_semana_actual()
    vuelos = await db_thread(db.vuelos_semana)
    gastos_todos = await db_thread(db.gastos_fondo)
    _, gastos_total = _gastos_fondo_rango(gastos_todos, desde_iso)

    r = _resumen_vuelos(vuelos)
    socios = await db_thread(db.get_socios)
    n_socios = max(1, len(socios))

    cuerpo = _texto_reporte_semana(
        r, gastos_total, n_socios, desde_dt, hasta_dt,
        titulo="🔒 *CHECKOUT — Cierre semanal*",
    )
    aviso = (
        "\n\n⚠️ _Al confirmar, se cierra la semana: el reporte semanal se "
        "reinicia y los próximos vuelos empezarán a contar para la siguiente._"
    )
    await q.edit_message_text(
        cuerpo + aviso, parse_mode="Markdown",
        reply_markup=kb_checkout_confirmar(),
    )
    return ST_MENU


async def checkout_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirma el cierre semanal: graba timestamp y avisa a los socios."""
    if not autorizado(update):
        await rechazar(update)
        return ConversationHandler.END

    q = update.callback_query
    await q.answer("Cerrando semana…")

    if not await db_thread(_es_sabado_y_pendiente):
        await q.edit_message_text(
            "ℹ️ El cierre ya fue realizado o no es sábado.",
            parse_mode="Markdown", reply_markup=kb_volver(),
        )
        return ST_MENU

    # Construimos el resumen ANTES de marcar el checkout (para incluir todos
    # los vuelos de la semana que cierra).
    desde_dt, hasta_dt, desde_iso = _rango_semana_actual()
    vuelos = await db_thread(db.vuelos_semana)
    gastos_todos = await db_thread(db.gastos_fondo)
    _, gastos_total = _gastos_fondo_rango(gastos_todos, desde_iso)

    r = _resumen_vuelos(vuelos)
    socios = await db_thread(db.get_socios)
    n_socios = max(1, len(socios))
    ingresos = r["ingreso_completados"]
    ganancia_neta = ingresos - gastos_total
    parte = ganancia_neta / n_socios

    ts = await db_thread(db.set_ultimo_checkout)

    quien = nombre_usuario(update.effective_user)
    aviso = (
        f"🔒 *Semana cerrada por {safe(quien)}*\n"
        f"_{desde_dt.strftime('%d/%m')} – {hasta_dt.strftime('%d/%m/%Y')}_\n"
        f"─────────────────────────────\n"
        f"  • Vuelos sacados: *{r['completados']}* ✅\n"
        f"  • Ingresos:       *{formato_mxn(ingresos)}*\n"
        f"  • Egresos fondo:  −{formato_mxn(gastos_total)}\n"
        f"  • Ganancia neta:  *{formato_mxn(ganancia_neta)}*\n"
        f"  • Por socio:      *{formato_mxn(parte)}*\n"
        f"\n"
        f"{_bloque_por_socio(r)}"
        f"💸 _Repartan el dinero y arrancamos semana nueva._"
    )
    try:
        await notificar_a(ctx.bot, ALLOWED_IDS, aviso, parse_mode="Markdown")
    except Exception:
        pass

    await q.edit_message_text(
        f"✅ *Cierre confirmado*\n_{ts}_\n\n"
        f"La semana quedó cerrada. El reporte semanal arranca de cero.\n"
        f"Cada socio: *{formato_mxn(parte)}*",
        parse_mode="Markdown", reply_markup=kb_volver(),
    )
    return ST_MENU
