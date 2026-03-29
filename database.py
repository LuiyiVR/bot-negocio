import sqlite3
from datetime import datetime
from pathlib import Path

# En servidor usa /data/negocio.db (volumen persistente), en local usa la carpeta del proyecto
import os
_data_dir = os.getenv("DATA_DIR", str(Path(__file__).parent))
DB_PATH = Path(_data_dir) / "negocio.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                usuario TEXT NOT NULL,
                tarjeta TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                monto_cobrado REAL NOT NULL,
                moneda_cobrado TEXT NOT NULL,
                monto_cobrado_mxn REAL NOT NULL,
                monto_gastado REAL NOT NULL,
                moneda_gastado TEXT NOT NULL,
                monto_gastado_mxn REAL NOT NULL,
                tipo_cambio REAL NOT NULL DEFAULT 1.0,
                pedido_id INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_creacion TEXT NOT NULL,
                creado_por TEXT NOT NULL,
                tipo TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                descripcion TEXT NOT NULL,
                monto_compra REAL NOT NULL,
                moneda_compra TEXT NOT NULL,
                monto_compra_mxn REAL NOT NULL,
                monto_cobrado REAL NOT NULL,
                moneda_cobrado TEXT NOT NULL,
                monto_cobrado_mxn REAL NOT NULL,
                tipo_cambio REAL NOT NULL DEFAULT 1.0,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                aceptado_por TEXT NOT NULL DEFAULT '',
                tarjeta TEXT NOT NULL DEFAULT '',
                fecha_completado TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS inversion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                concepto TEXT NOT NULL,
                monto REAL NOT NULL,
                moneda TEXT NOT NULL,
                monto_mxn REAL NOT NULL,
                tipo_cambio REAL NOT NULL DEFAULT 1.0
            );

            CREATE TABLE IF NOT EXISTS config (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );

            INSERT OR IGNORE INTO config (clave, valor) VALUES ('inversion_inicial', '15000');
            INSERT OR IGNORE INTO config (clave, valor) VALUES ('socios', 'LAVR,FEDE,SPAIDER RATA');
        """)


# ─────────────────────────── VENTAS ──────────────────────────────────────────

def registrar_venta(usuario, tarjeta, descripcion,
                    monto_cobrado, moneda_cobrado, monto_cobrado_mxn,
                    monto_gastado, moneda_gastado, monto_gastado_mxn,
                    tipo_cambio, pedido_id=None):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO ventas
            (fecha, usuario, tarjeta, descripcion,
             monto_cobrado, moneda_cobrado, monto_cobrado_mxn,
             monto_gastado, moneda_gastado, monto_gastado_mxn,
             tipo_cambio, pedido_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (fecha, usuario, tarjeta, descripcion,
              monto_cobrado, moneda_cobrado, monto_cobrado_mxn,
              monto_gastado, moneda_gastado, monto_gastado_mxn,
              tipo_cambio, pedido_id))


def get_venta(venta_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()


def ventas_por_usuario(usuario):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM ventas WHERE usuario=? ORDER BY fecha DESC", (usuario,)
        ).fetchall()


def ventas_mes(anio, mes):
    patron = f"{anio}-{mes:02d}-%"
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM ventas WHERE fecha LIKE ? ORDER BY usuario, fecha", (patron,)
        ).fetchall()


def todas_las_ventas():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM ventas ORDER BY fecha DESC").fetchall()


# ─────────────────────────── PEDIDOS ─────────────────────────────────────────

def crear_pedido(creado_por, tipo, link, descripcion,
                 monto_compra, moneda_compra, monto_compra_mxn,
                 monto_cobrado, moneda_cobrado, monto_cobrado_mxn,
                 tipo_cambio) -> int:
    """Crea un pedido y devuelve su ID."""
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO pedidos
            (fecha_creacion, creado_por, tipo, link, descripcion,
             monto_compra, moneda_compra, monto_compra_mxn,
             monto_cobrado, moneda_cobrado, monto_cobrado_mxn, tipo_cambio)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (fecha, creado_por, tipo, link, descripcion,
              monto_compra, moneda_compra, monto_compra_mxn,
              monto_cobrado, moneda_cobrado, monto_cobrado_mxn,
              tipo_cambio))
        return cur.lastrowid


def get_pedido(pedido_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()


def pedidos_pendientes():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pedidos WHERE estado='pendiente' ORDER BY fecha_creacion DESC"
        ).fetchall()


def pedidos_de_usuario(usuario: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pedidos WHERE aceptado_por=? ORDER BY fecha_creacion DESC",
            (usuario,)
        ).fetchall()


def pedidos_en_proceso_de(usuario: str):
    """Pedidos que el usuario aceptó pero aún no ha completado."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pedidos WHERE aceptado_por=? AND estado='en_proceso' ORDER BY fecha_creacion DESC",
            (usuario,)
        ).fetchall()


def aceptar_pedido(pedido_id: int, usuario: str) -> dict | None:
    """Reserva el pedido para un usuario (estado: en_proceso). No registra venta aún."""
    p = get_pedido(pedido_id)
    if not p or p["estado"] != "pendiente":
        return None

    fecha_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("""
            UPDATE pedidos
            SET estado='en_proceso', aceptado_por=?, fecha_completado=?
            WHERE id=?
        """, (usuario, fecha_now, pedido_id))
    return dict(p)


def completar_pedido(pedido_id: int, usuario: str, tarjeta: str) -> dict | None:
    """Marca el pedido como completado y registra la venta."""
    p = get_pedido(pedido_id)
    if not p or p["estado"] != "en_proceso" or p["aceptado_por"] != usuario:
        return None

    fecha_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("""
            UPDATE pedidos
            SET estado='completado', tarjeta=?, fecha_completado=?
            WHERE id=?
        """, (tarjeta, fecha_now, pedido_id))

    registrar_venta(
        usuario=usuario,
        tarjeta=tarjeta,
        descripcion=f"[{p['tipo']}] {p['descripcion']}",
        monto_cobrado=p["monto_cobrado"],
        moneda_cobrado=p["moneda_cobrado"],
        monto_cobrado_mxn=p["monto_cobrado_mxn"],
        monto_gastado=p["monto_compra"],
        moneda_gastado=p["moneda_compra"],
        monto_gastado_mxn=p["monto_compra_mxn"],
        tipo_cambio=p["tipo_cambio"],
        pedido_id=pedido_id,
    )
    return dict(p)


def soltar_pedido(pedido_id: int, usuario: str) -> dict | None:
    """Regresa un pedido de en_proceso a pendiente (lo suelta quien lo tenía)."""
    p = get_pedido(pedido_id)
    if not p or p["estado"] != "en_proceso" or p["aceptado_por"] != usuario:
        return None
    with get_conn() as conn:
        conn.execute("""
            UPDATE pedidos
            SET estado='pendiente', aceptado_por='', fecha_completado=''
            WHERE id=?
        """, (pedido_id,))
    return dict(p)


def cancelar_pedido(pedido_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE pedidos SET estado='cancelado' WHERE id=?", (pedido_id,))


def delete_pedido(pedido_id: int):
    """Elimina un pedido permanentemente."""
    with get_conn() as conn:
        conn.execute("DELETE FROM pedidos WHERE id=?", (pedido_id,))


def delete_venta(venta_id: int):
    """Elimina una venta permanentemente."""
    with get_conn() as conn:
        conn.execute("DELETE FROM ventas WHERE id=?", (venta_id,))


def delete_gasto_inversion(gasto_id: int):
    """Elimina un gasto de inversión permanentemente."""
    with get_conn() as conn:
        conn.execute("DELETE FROM inversion WHERE id=?", (gasto_id,))


def update_inversion_inicial(monto: float):
    """Reemplaza el monto total de la inversión inicial."""
    set_config("inversion_inicial", str(monto))


def agregar_a_inversion(monto_extra: float):
    """Suma monto_extra a la inversión inicial actual."""
    actual = float(get_config("inversion_inicial") or 15000)
    set_config("inversion_inicial", str(actual + monto_extra))


# ─────────────────────────── INVERSIÓN ───────────────────────────────────────

def registrar_gasto_inversion(concepto, monto, moneda, monto_mxn, tipo_cambio):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO inversion (fecha, concepto, monto, moneda, monto_mxn, tipo_cambio)
            VALUES (?,?,?,?,?,?)
        """, (fecha, concepto, monto, moneda, monto_mxn, tipo_cambio))


def gastos_inversion():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM inversion ORDER BY fecha DESC").fetchall()


def total_gastado_inversion():
    with get_conn() as conn:
        return conn.execute("SELECT COALESCE(SUM(monto_mxn),0) FROM inversion").fetchone()[0]


# ─────────────────────────── CONFIG ──────────────────────────────────────────

def get_config(clave):
    with get_conn() as conn:
        row = conn.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    return row["valor"] if row else None


def set_config(clave, valor):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO config (clave,valor) VALUES (?,?)", (clave, str(valor)))


def get_socios():
    val = get_config("socios")
    return [s.strip() for s in val.split(",")] if val else []


def set_socios(lista):
    set_config("socios", ",".join(lista))
