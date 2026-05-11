"""Estados de la ConversationHandler agrupados por módulo."""

ST_MENU = 0

# ── Crear vuelo ──────────────────────────────────────────────────────────────
ST_VC_FOTO       = 100
ST_VC_PASAJEROS  = 105
ST_VC_COBRADO    = 107
ST_VC_CONFIRMAR  = 108

# ── Acciones sobre vuelos ────────────────────────────────────────────────────
ST_VAC_CANCELAR        = 200
ST_VAC_COMPLETAR_FOTO  = 201

# ── Fondo de inversión ───────────────────────────────────────────────────────
ST_FONDO_CONCEPTO    = 300
ST_FONDO_MONTO       = 301
ST_FONDO_EDITAR_MTO  = 302
ST_FONDO_AGREGAR_MTO = 303

# ── Reportes ─────────────────────────────────────────────────────────────────
ST_REP_OTRO_MES = 400

# ── Configuración ────────────────────────────────────────────────────────────
ST_CONFIG_SOCIOS = 500

# ── Bodega de BINs ───────────────────────────────────────────────────────────
ST_BIN_NUM         = 600
ST_BIN_TIENDA      = 601
ST_BIN_NUEVA_TIENDA = 602
ST_BIN_BUSCAR      = 603
