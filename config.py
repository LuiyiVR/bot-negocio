"""Configuración global: variables de entorno, constantes, rutas."""
import os
import pathlib
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

_raw = os.getenv("ALLOWED_IDS", "")
ALLOWED_IDS: set[int] = {
    int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()
}

# ── Base de datos ────────────────────────────────────────────────────────────
_data_dir = os.getenv("DATA_DIR", str(pathlib.Path(__file__).parent))
DB_PATH = pathlib.Path(_data_dir) / "bot.db"

# ── Defaults de negocio ──────────────────────────────────────────────────────
INVERSION_INICIAL_DEFAULT = 15000.0
SOCIOS_DEFAULT = "LAVR,FEDE,SPAIDER RATA"

# ── Estados de vuelo ─────────────────────────────────────────────────────────
ESTADO_PENDIENTE  = "pendiente"
ESTADO_EN_PROCESO = "en_proceso"
ESTADO_COMPLETADO = "completado"
ESTADO_CANCELADO  = "cancelado"
ESTADO_CAIDO      = "caido"

# ── UI ───────────────────────────────────────────────────────────────────────
SEP = "─" * 28
