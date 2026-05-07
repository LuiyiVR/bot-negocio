"""
Bot de Telegram — Negocio de Vuelos
• 100% por botones inline
• Sistema de vuelos: crear → tomar → completar / soltar / cancelar
• Acceso restringido a IDs autorizados (ALLOWED_IDS en .env)
"""
import asyncio
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

import db
from config import BOT_TOKEN, ALLOWED_IDS

# ── Handlers ─────────────────────────────────────────────────────────────────
from handlers.menu import mostrar_menu
from handlers.vuelo_crear import (
    vc_inicio, vc_aerolinea, vc_origen, vc_destino, vc_fecha, vc_horario,
    vc_pasajeros, vc_extras, vc_skip_extras, vc_cobrado, vc_publicar,
)
from handlers.vuelo_acciones import (
    vac_tomar, vac_soltar, vac_completar,
    vac_cancelar_inicio, vac_cancelar_ok,
)
from handlers.vuelo_lista import vl_pendientes, vl_mios, vl_ver
from handlers.reportes import (
    rep_mes, rep_otro_mes_inicio, rep_otro_mes_texto,
    rep_semana, rep_dl_mes, rep_dl_semana,
)
from handlers.inversion import (
    fondo_ver,
    fondo_gasto_inicio, fondo_gasto_concepto, fondo_gasto_monto,
    fondo_editar_inicio, fondo_editar_monto,
    fondo_agregar_inicio, fondo_agregar_monto,
    fondo_del_confirm, fondo_del_ok,
)
from handlers.bins import (
    bin_menu, bin_agregar_inicio, bin_buscar_inicio,
    bin_buscar_resultado, bin_buscar_txt, bin_num,
    bin_tienda_sel, bin_nueva_tienda_inicio, bin_nueva_tienda_texto,
    bin_ver_todos, bin_ver_tiendas, bin_ver_tienda,
    rmv_menu, rmv_sel_tiendas, rmv_confirmar_tienda, rmv_ok_tienda,
    rmv_sel_bins, rmv_confirmar_bin, rmv_ok_bin,
)
from handlers.configuracion import (
    config_menu, config_socios_inicio, config_socios_guardar,
)

from states import (
    ST_MENU,
    ST_VC_AEROLINEA, ST_VC_ORIGEN, ST_VC_DESTINO, ST_VC_FECHA, ST_VC_HORARIO,
    ST_VC_PASAJEROS, ST_VC_EXTRAS, ST_VC_COBRADO, ST_VC_CONFIRMAR,
    ST_FONDO_CONCEPTO, ST_FONDO_MONTO,
    ST_FONDO_EDITAR_MTO, ST_FONDO_AGREGAR_MTO,
    ST_REP_OTRO_MES, ST_CONFIG_SOCIOS,
    ST_BIN_NUM, ST_BIN_TIENDA, ST_BIN_NUEVA_TIENDA, ST_BIN_BUSCAR,
)


logging.basicConfig(
    format="%(asctime)s  %(levelname)s  %(name)s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _menu_callbacks():
    """Callbacks que pueden dispararse desde el estado ST_MENU."""
    return [
        # Volver al menú
        CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),

        # Vuelos
        CallbackQueryHandler(vc_inicio,            pattern=r"^vc_inicio$"),
        CallbackQueryHandler(vl_pendientes,        pattern=r"^vl_pendientes$"),
        CallbackQueryHandler(vl_mios,              pattern=r"^vl_mios$"),
        CallbackQueryHandler(vl_ver,               pattern=r"^vl_ver:\d+$"),
        CallbackQueryHandler(vac_tomar,            pattern=r"^vac_tomar:\d+$"),
        CallbackQueryHandler(vac_soltar,           pattern=r"^vac_soltar:\d+$"),
        CallbackQueryHandler(vac_completar,        pattern=r"^vac_completar:\d+$"),
        CallbackQueryHandler(vac_cancelar_inicio,  pattern=r"^vac_cancelar:\d+$"),
        CallbackQueryHandler(vac_cancelar_ok,      pattern=r"^vac_cancelar_ok:\d+$"),

        # Reportes
        CallbackQueryHandler(rep_mes,              pattern=r"^rep_mes$"),
        CallbackQueryHandler(rep_otro_mes_inicio,  pattern=r"^rep_otro_mes$"),
        CallbackQueryHandler(rep_semana,           pattern=r"^rep_semana$"),
        CallbackQueryHandler(rep_dl_mes,           pattern=r"^rep_dl_mes:"),
        CallbackQueryHandler(rep_dl_semana,        pattern=r"^rep_dl_semana$"),

        # Fondo
        CallbackQueryHandler(fondo_ver,            pattern=r"^fondo_ver$"),
        CallbackQueryHandler(fondo_gasto_inicio,   pattern=r"^fondo_gasto$"),
        CallbackQueryHandler(fondo_editar_inicio,  pattern=r"^fondo_editar$"),
        CallbackQueryHandler(fondo_agregar_inicio, pattern=r"^fondo_agregar$"),
        CallbackQueryHandler(fondo_del_confirm,    pattern=r"^fondo_del:\d+$"),
        CallbackQueryHandler(fondo_del_ok,         pattern=r"^fondo_del_ok:\d+$"),

        # Bodega de BINs
        CallbackQueryHandler(bin_menu,                  pattern=r"^bin_menu$"),
        CallbackQueryHandler(bin_agregar_inicio,        pattern=r"^bin_agregar$"),
        CallbackQueryHandler(bin_buscar_inicio,         pattern=r"^bin_buscar$"),
        CallbackQueryHandler(bin_ver_todos,             pattern=r"^bin_ver_todos$"),
        CallbackQueryHandler(bin_ver_tiendas,           pattern=r"^bin_ver_tiendas$"),
        CallbackQueryHandler(bin_ver_tienda,            pattern=r"^bin_ver:"),
        CallbackQueryHandler(rmv_menu,                  pattern=r"^rmv_menu$"),
        CallbackQueryHandler(rmv_sel_tiendas,           pattern=r"^rmv_modo:"),
        CallbackQueryHandler(rmv_confirmar_tienda,      pattern=r"^rmv_del_tienda:"),
        CallbackQueryHandler(rmv_ok_tienda,             pattern=r"^rmv_ok_tienda:"),
        CallbackQueryHandler(rmv_sel_bins,              pattern=r"^rmv_bins:"),
        CallbackQueryHandler(rmv_confirmar_bin,         pattern=r"^rmv_del_bin:\d+$"),
        CallbackQueryHandler(rmv_ok_bin,                pattern=r"^rmv_ok_bin:\d+$"),

        # Configuración
        CallbackQueryHandler(config_menu,           pattern=r"^config_menu$"),
        CallbackQueryHandler(config_socios_inicio,  pattern=r"^config_socios$"),
    ]


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en .env")
    if not ALLOWED_IDS:
        raise RuntimeError("Falta ALLOWED_IDS en .env (ej: ALLOWED_IDS=123,456,789)")

    db.init_db()
    logger.info("✅ DB inicializada")
    logger.info("✅ IDs autorizados: %s", ALLOWED_IDS)

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", mostrar_menu),
            CommandHandler("rmv",   rmv_menu),
            # Permite tomar/completar/soltar/cancelar desde notificaciones externas
            CallbackQueryHandler(vac_tomar,           pattern=r"^vac_tomar:\d+$"),
            CallbackQueryHandler(vac_completar,       pattern=r"^vac_completar:\d+$"),
            CallbackQueryHandler(vac_soltar,          pattern=r"^vac_soltar:\d+$"),
            CallbackQueryHandler(vac_cancelar_inicio, pattern=r"^vac_cancelar:\d+$"),
            CallbackQueryHandler(vac_cancelar_ok,     pattern=r"^vac_cancelar_ok:\d+$"),
        ],
        states={
            ST_MENU: _menu_callbacks(),

            # ── Crear vuelo ──────────────────────────────────────────────────
            ST_VC_AEROLINEA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_aerolinea),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_ORIGEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_origen),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_DESTINO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_destino),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_FECHA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_fecha),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_HORARIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_horario),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_PASAJEROS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_pasajeros),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_EXTRAS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_extras),
                CallbackQueryHandler(vc_skip_extras, pattern=r"^vc_skip_extras$"),
                CallbackQueryHandler(mostrar_menu,  pattern=r"^menu$"),
            ],
            ST_VC_COBRADO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vc_cobrado),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_VC_CONFIRMAR: [
                CallbackQueryHandler(vc_publicar,  pattern=r"^vc_publicar$"),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],

            # ── Reportes (otro mes) ──────────────────────────────────────────
            ST_REP_OTRO_MES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rep_otro_mes_texto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],

            # ── Fondo ────────────────────────────────────────────────────────
            ST_FONDO_CONCEPTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fondo_gasto_concepto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_FONDO_MONTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fondo_gasto_monto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_FONDO_EDITAR_MTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fondo_editar_monto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_FONDO_AGREGAR_MTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fondo_agregar_monto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],

            # ── Configuración ────────────────────────────────────────────────
            ST_CONFIG_SOCIOS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, config_socios_guardar),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],

            # ── Bodega de BINs ───────────────────────────────────────────────
            ST_BIN_NUM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bin_num),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_BIN_TIENDA: [
                CallbackQueryHandler(bin_tienda_sel,          pattern=r"^bin_tienda:"),
                CallbackQueryHandler(bin_nueva_tienda_inicio, pattern=r"^bin_nueva_tienda$"),
                CallbackQueryHandler(mostrar_menu,            pattern=r"^menu$"),
            ],
            ST_BIN_NUEVA_TIENDA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bin_nueva_tienda_texto),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
            ST_BIN_BUSCAR: [
                MessageHandler(filters.Document.ALL,            bin_buscar_txt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bin_buscar_resultado),
                CallbackQueryHandler(bin_menu,     pattern=r"^bin_menu$"),
                CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", mostrar_menu),
            CallbackQueryHandler(mostrar_menu, pattern=r"^menu$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("✅ Bot iniciado y escuchando…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
