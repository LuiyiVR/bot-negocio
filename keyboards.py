"""Teclados inline reutilizables."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


# ── Genéricos ────────────────────────────────────────────────────────────────

def kb_menu(mostrar_checkout: bool = False):
    filas = []
    if mostrar_checkout:
        filas.append([InlineKeyboardButton(
            "🔒  CHECKOUT — Cerrar semana", callback_data="checkout_inicio",
        )])
    filas.extend([
        [InlineKeyboardButton("✈️  Nuevo Vuelo",          callback_data="vc_inicio")],
        [
            InlineKeyboardButton("📋  Pendientes",         callback_data="vl_pendientes"),
            InlineKeyboardButton("🎫  Vuelos Sacados",     callback_data="vl_sacados"),
        ],
        [
            InlineKeyboardButton("📅  Balance del Mes",    callback_data="rep_mes"),
            InlineKeyboardButton("📊  Reporte Semanal",    callback_data="rep_semana"),
        ],
        [
            InlineKeyboardButton("🏦  Fondo de Inversión", callback_data="fondo_ver"),
            InlineKeyboardButton("🗂  Bodega de BINs",     callback_data="bin_menu"),
        ],
        [InlineKeyboardButton("⚙️  Configuración",         callback_data="config_menu")],
    ])
    return InlineKeyboardMarkup(filas)


def kb_checkout_confirmar():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Confirmar cierre semanal",
                              callback_data="checkout_ok")],
        [InlineKeyboardButton("⬅️  Cancelar", callback_data="menu")],
    ])


def kb_cancelar():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  Cancelar", callback_data="menu")],
    ])


def kb_volver():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
    ])


def kb_saltar(callback_saltar: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭  Saltar este paso", callback_data=callback_saltar)],
        [InlineKeyboardButton("❌  Cancelar",         callback_data="menu")],
    ])


# ── Vuelos ───────────────────────────────────────────────────────────────────

def kb_aceptar_vuelo(vuelo_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅  Tomar este vuelo (#{vuelo_id})",
                              callback_data=f"vac_tomar:{vuelo_id}")],
    ])


def kb_acciones_vuelo(vuelo, user_id: int):
    """
    Construye los botones disponibles según estado y rol del usuario.
    `vuelo` es sqlite3.Row o dict.
    """
    g = (lambda k: vuelo[k]) if hasattr(vuelo, "keys") else (lambda k: getattr(vuelo, k))
    estado = g("estado")
    creador = g("creado_por_id")
    tomador = g("aceptado_por_id")
    vid     = g("id")

    filas = []

    if estado == "pendiente":
        filas.append([InlineKeyboardButton(f"✅  Tomar (#{vid})",
                                           callback_data=f"vac_tomar:{vid}")])
        filas.append([InlineKeyboardButton(f"❌  Cancelar (#{vid})",
                                           callback_data=f"vac_cancelar:{vid}")])

    elif estado == "en_proceso":
        if tomador == user_id:
            filas.append([
                InlineKeyboardButton(f"✔️  Completar (#{vid})", callback_data=f"vac_completar:{vid}"),
                InlineKeyboardButton(f"🔓  Soltar (#{vid})",     callback_data=f"vac_soltar:{vid}"),
            ])
            filas.append([InlineKeyboardButton(f"💥  Vuelo caído (#{vid})",
                                               callback_data=f"vac_caido:{vid}")])
        if creador == user_id:
            filas.append([InlineKeyboardButton(f"❌  Cancelar (#{vid})",
                                               callback_data=f"vac_cancelar:{vid}")])

    elif estado == "caido":
        if tomador == user_id:
            filas.append([
                InlineKeyboardButton(f"✔️  Completar (#{vid})", callback_data=f"vac_completar:{vid}"),
                InlineKeyboardButton(f"🔓  Liberar (#{vid})",   callback_data=f"vac_caido_liberar:{vid}"),
            ])
        if creador == user_id:
            filas.append([InlineKeyboardButton(f"❌  Cancelar (#{vid})",
                                               callback_data=f"vac_cancelar:{vid}")])

    elif estado == "completado":
        if tomador == user_id:
            filas.append([InlineKeyboardButton(f"✈️  Volado (#{vid})",
                                               callback_data=f"vac_volado:{vid}")])
            filas.append([InlineKeyboardButton(f"💥  Vuelo caído (#{vid})",
                                               callback_data=f"vac_caido:{vid}")])
            filas.append([InlineKeyboardButton(f"❌  Cancelar (#{vid})",
                                               callback_data=f"vac_cancelar:{vid}")])

    return filas


def kb_lista_vuelos(vuelos, user_id: int, *, volver_a: str = "menu"):
    filas = []
    for v in vuelos:
        filas.extend(kb_acciones_vuelo(v, user_id))
    filas.append([InlineKeyboardButton("🏠  Menú Principal", callback_data=volver_a)])
    return InlineKeyboardMarkup(filas)


def kb_confirmar_cancelar(vuelo_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Sí, cancelar", callback_data=f"vac_cancelar_ok:{vuelo_id}")],
        [InlineKeyboardButton("⬅️  No, volver",   callback_data="menu")],
    ])


def kb_duracion_sacado(vuelo_id: int):
    """Opciones que se le presentan al usuario al sacar un vuelo para elegir
    cuánto tiempo permanece visible en 'Vuelos Sacados'."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑  24 horas", callback_data=f"vac_expira:{vuelo_id}:24"),
            InlineKeyboardButton("🗑  3 días",   callback_data=f"vac_expira:{vuelo_id}:72"),
        ],
        [
            InlineKeyboardButton("🗑  5 días",   callback_data=f"vac_expira:{vuelo_id}:120"),
            InlineKeyboardButton("🗑  7 días",   callback_data=f"vac_expira:{vuelo_id}:168"),
        ],
        [
            InlineKeyboardButton("🗑  8 días",   callback_data=f"vac_expira:{vuelo_id}:192"),
            InlineKeyboardButton("🗑  14 días",  callback_data=f"vac_expira:{vuelo_id}:336"),
        ],
        [InlineKeyboardButton("🏠  Menú Principal", callback_data="menu")],
    ])


def kb_caido_opciones(vuelo_id: int):
    """Pregunta qué hacer cuando se marca un vuelo como caído."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓  Liberar para todos",
                              callback_data=f"vac_caido_soltar:{vuelo_id}")],
        [InlineKeyboardButton("📌  Mantener para mí",
                              callback_data=f"vac_caido_mantener:{vuelo_id}")],
        [InlineKeyboardButton("⬅️  Cancelar", callback_data="menu")],
    ])


# ── Fondo de inversión ───────────────────────────────────────────────────────

def kb_fondo():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Registrar Gasto",  callback_data="fondo_gasto")],
        [
            InlineKeyboardButton("✏️  Editar fondo",  callback_data="fondo_editar"),
            InlineKeyboardButton("➕  Agregar fondo", callback_data="fondo_agregar"),
        ],
        [InlineKeyboardButton("🏠  Menú Principal",   callback_data="menu")],
    ])


# ── Bodega de BINs ───────────────────────────────────────────────────────────

def kb_bin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Agregar BIN",        callback_data="bin_agregar")],
        [InlineKeyboardButton("🔍  Buscar BIN",         callback_data="bin_buscar")],
        [InlineKeyboardButton("📦  Ver por tienda",     callback_data="bin_ver_tiendas")],
        [InlineKeyboardButton("📋  Ver todos",          callback_data="bin_ver_todos")],
        [InlineKeyboardButton("🗑  Eliminar (/rmv)",    callback_data="rmv_menu")],
        [InlineKeyboardButton("🏠  Menú Principal",     callback_data="menu")],
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


# ── Configuración ────────────────────────────────────────────────────────────

def kb_config():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥  Editar socios",     callback_data="config_socios")],
        [InlineKeyboardButton("🏠  Menú Principal",    callback_data="menu")],
    ])
