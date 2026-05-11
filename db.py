"""Capa de SQLite: vuelos, fondo de inversión, bodega de BINs y config."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from config import (
    DB_PATH, INVERSION_INICIAL_DEFAULT, SOCIOS_DEFAULT,
    ESTADO_PENDIENTE, ESTADO_EN_PROCESO,
    ESTADO_COMPLETADO, ESTADO_CANCELADO, ESTADO_CAIDO,
)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vuelos (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_creacion    TEXT    NOT NULL,
                creado_por        TEXT    NOT NULL,
                creado_por_id     INTEGER NOT NULL,
                aerolinea         TEXT    NOT NULL DEFAULT '',
                origen            TEXT    NOT NULL DEFAULT '',
                destino           TEXT    NOT NULL DEFAULT '',
                fecha_vuelo       TEXT    NOT NULL DEFAULT '',
                horario           TEXT    NOT NULL DEFAULT '',
                foto_file_id      TEXT    NOT NULL DEFAULT '',
                pasajeros         TEXT    NOT NULL,
                extras            TEXT    NOT NULL DEFAULT '',
                monto_cobrado     REAL    NOT NULL,
                estado            TEXT    NOT NULL DEFAULT 'pendiente',
                aceptado_por      TEXT    NOT NULL DEFAULT '',
                aceptado_por_id   INTEGER          DEFAULT NULL,
                fecha_aceptado    TEXT    NOT NULL DEFAULT '',
                fecha_completado  TEXT    NOT NULL DEFAULT '',
                fecha_cancelado   TEXT    NOT NULL DEFAULT '',
                cancelado_por     TEXT    NOT NULL DEFAULT '',
                fecha_caido               TEXT NOT NULL DEFAULT '',
                foto_confirmacion_file_id TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_vuelos_estado ON vuelos(estado);
            CREATE INDEX IF NOT EXISTS idx_vuelos_creado_id ON vuelos(creado_por_id);
            CREATE INDEX IF NOT EXISTS idx_vuelos_aceptado_id ON vuelos(aceptado_por_id);

            CREATE TABLE IF NOT EXISTS gastos_fondo (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha           TEXT    NOT NULL,
                concepto        TEXT    NOT NULL,
                monto           REAL    NOT NULL,
                registrado_por  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS config (
                clave  TEXT PRIMARY KEY,
                valor  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bin_cache (
                bin           TEXT PRIMARY KEY,
                bank          TEXT    NOT NULL DEFAULT '',
                country       TEXT    NOT NULL DEFAULT '',
                country_code  TEXT    NOT NULL DEFAULT '',
                brand         TEXT    NOT NULL DEFAULT '',
                type          TEXT    NOT NULL DEFAULT '',
                fuentes       INTEGER NOT NULL DEFAULT 0,
                confianza     INTEGER NOT NULL DEFAULT 0,
                level         TEXT    NOT NULL DEFAULT '',
                fecha         TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tiendas_bins (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre  TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS bins (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bin           TEXT NOT NULL,
                tienda        TEXT NOT NULL,
                agregado_por  TEXT NOT NULL,
                fecha         TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO config (clave, valor) VALUES ('inversion_inicial', ?)",
            (str(INVERSION_INICIAL_DEFAULT),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO config (clave, valor) VALUES ('socios', ?)",
            (SOCIOS_DEFAULT,),
        )

        # Migraciones: añadir columnas nuevas si la DB es de antes del cambio.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(vuelos)")}
        if "foto_file_id" not in cols:
            conn.execute(
                "ALTER TABLE vuelos ADD COLUMN foto_file_id TEXT NOT NULL DEFAULT ''"
            )
        if "fecha_caido" not in cols:
            conn.execute(
                "ALTER TABLE vuelos ADD COLUMN fecha_caido TEXT NOT NULL DEFAULT ''"
            )
        if "foto_confirmacion_file_id" not in cols:
            conn.execute(
                "ALTER TABLE vuelos ADD COLUMN foto_confirmacion_file_id "
                "TEXT NOT NULL DEFAULT ''"
            )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
#  VUELOS
# ═════════════════════════════════════════════════════════════════════════════

def crear_vuelo(*, creado_por: str, creado_por_id: int,
                foto_file_id: str, pasajeros: str,
                monto_cobrado: float) -> dict:
    # Pasamos '' para los campos heredados (aerolinea/origen/destino/fecha_vuelo/
    # horario/extras) porque en DBs creadas antes de la migración esas columnas
    # están como NOT NULL sin default, y SQLite no soporta ALTER COLUMN.
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO vuelos
            (fecha_creacion, creado_por, creado_por_id,
             aerolinea, origen, destino, fecha_vuelo, horario,
             foto_file_id, pasajeros, extras, monto_cobrado)
            VALUES (?,?,?, ?,?,?,?,?, ?,?,?,?)
        """, (_now(), creado_por, creado_por_id,
              '', '', '', '', '',
              foto_file_id, pasajeros, '', monto_cobrado))
        row = conn.execute("SELECT * FROM vuelos WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_vuelo(vuelo_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone()


def vuelos_pendientes() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM vuelos WHERE estado=? ORDER BY fecha_creacion DESC",
            (ESTADO_PENDIENTE,),
        ).fetchall()


def vuelos_de_usuario(user_id: int, estados: list[str] | None = None) -> list:
    with get_conn() as conn:
        if estados:
            placeholders = ",".join("?" * len(estados))
            return conn.execute(
                f"""SELECT * FROM vuelos
                    WHERE aceptado_por_id=? AND estado IN ({placeholders})
                    ORDER BY fecha_creacion DESC""",
                (user_id, *estados),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM vuelos WHERE aceptado_por_id=? ORDER BY fecha_creacion DESC",
            (user_id,),
        ).fetchall()


def vuelos_creados_por(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM vuelos WHERE creado_por_id=? ORDER BY fecha_creacion DESC",
            (user_id,),
        ).fetchall()


def vuelos_mes(anio: int, mes: int) -> list:
    patron = f"{anio}-{mes:02d}-%"
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM vuelos WHERE fecha_creacion LIKE ? ORDER BY fecha_creacion",
            (patron,),
        ).fetchall()


def vuelos_rango(desde_iso: str, hasta_iso: str | None = None) -> list:
    with get_conn() as conn:
        if hasta_iso:
            return conn.execute(
                "SELECT * FROM vuelos WHERE fecha_creacion >= ? AND fecha_creacion <= ? "
                "ORDER BY fecha_creacion DESC",
                (desde_iso, hasta_iso),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM vuelos WHERE fecha_creacion >= ? ORDER BY fecha_creacion DESC",
            (desde_iso,),
        ).fetchall()


def vuelos_hoy() -> list:
    hoy = datetime.now().strftime("%Y-%m-%d")
    return vuelos_rango(hoy)


def vuelos_semana() -> list:
    hace7 = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    return vuelos_rango(hace7)


def todos_los_vuelos() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM vuelos ORDER BY fecha_creacion DESC"
        ).fetchall()


# ── Transiciones de estado (atómicas) ────────────────────────────────────────

def tomar_vuelo(vuelo_id: int, usuario: str, user_id: int) -> dict | None:
    """Pendiente → En proceso. Atómico: solo el primero gana."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE vuelos
            SET estado=?, aceptado_por=?, aceptado_por_id=?, fecha_aceptado=?
            WHERE id=? AND estado=?
        """, (ESTADO_EN_PROCESO, usuario, user_id, _now(), vuelo_id, ESTADO_PENDIENTE))
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone())


def soltar_vuelo(vuelo_id: int, user_id: int) -> dict | None:
    """En proceso → Pendiente. Solo quien lo había tomado puede soltarlo."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE vuelos
            SET estado=?, aceptado_por='', aceptado_por_id=NULL, fecha_aceptado=''
            WHERE id=? AND estado=? AND aceptado_por_id=?
        """, (ESTADO_PENDIENTE, vuelo_id, ESTADO_EN_PROCESO, user_id))
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone())


def completar_vuelo(vuelo_id: int, user_id: int,
                    foto_confirmacion_file_id: str = '') -> dict | None:
    """En proceso o Caído → Completado. Solo quien lo tomó."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE vuelos
            SET estado=?, fecha_completado=?, foto_confirmacion_file_id=?
            WHERE id=? AND estado IN (?, ?) AND aceptado_por_id=?
        """, (ESTADO_COMPLETADO, _now(), foto_confirmacion_file_id,
              vuelo_id, ESTADO_EN_PROCESO, ESTADO_CAIDO, user_id))
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone())


def marcar_caido(vuelo_id: int, user_id: int) -> dict | None:
    """En proceso → Caído (queda reservado al tomador). Solo el tomador."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE vuelos
            SET estado=?, fecha_caido=?
            WHERE id=? AND estado=? AND aceptado_por_id=?
        """, (ESTADO_CAIDO, _now(), vuelo_id, ESTADO_EN_PROCESO, user_id))
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone())


def liberar_caido(vuelo_id: int, user_id: int) -> dict | None:
    """Caído → Pendiente. Solo quien lo tenía reservado."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE vuelos
            SET estado=?, aceptado_por='', aceptado_por_id=NULL,
                fecha_aceptado='', fecha_caido=''
            WHERE id=? AND estado=? AND aceptado_por_id=?
        """, (ESTADO_PENDIENTE, vuelo_id, ESTADO_CAIDO, user_id))
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone())


def cancelar_vuelo(vuelo_id: int, user_id: int, nombre: str) -> tuple[dict | None, str]:
    """
    Cancelación según reglas:
      • Pendiente o En proceso → solo el creador puede cancelar
      • Completado            → solo quien lo sacó (aceptado_por_id) puede cancelar
      • Cancelado             → no se puede recancelar
    Devuelve (vuelo_actualizado, mensaje_error_o_vacio).
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone()
        if not row:
            return None, "Vuelo no encontrado."

        estado = row["estado"]
        if estado == ESTADO_CANCELADO:
            return None, "Este vuelo ya está cancelado."

        autorizado = False
        if estado in (ESTADO_PENDIENTE, ESTADO_EN_PROCESO, ESTADO_CAIDO):
            autorizado = (row["creado_por_id"] == user_id)
            if not autorizado:
                return None, "Solo quien creó el vuelo puede cancelarlo en este estado."
        elif estado == ESTADO_COMPLETADO:
            autorizado = (row["aceptado_por_id"] == user_id)
            if not autorizado:
                return None, "Solo quien sacó el vuelo puede cancelarlo después de completado."

        conn.execute("""
            UPDATE vuelos
            SET estado=?, fecha_cancelado=?, cancelado_por=?
            WHERE id=?
        """, (ESTADO_CANCELADO, _now(), nombre, vuelo_id))
        nuevo = conn.execute("SELECT * FROM vuelos WHERE id=?", (vuelo_id,)).fetchone()
        return dict(nuevo), ""


def delete_vuelo(vuelo_id: int):
    """Borra permanentemente. Uso administrativo."""
    with get_conn() as conn:
        conn.execute("DELETE FROM vuelos WHERE id=?", (vuelo_id,))


# ═════════════════════════════════════════════════════════════════════════════
#  FONDO DE INVERSIÓN
# ═════════════════════════════════════════════════════════════════════════════

def registrar_gasto_fondo(concepto: str, monto: float, registrado_por: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO gastos_fondo (fecha, concepto, monto, registrado_por)
            VALUES (?,?,?,?)
        """, (_now(), concepto, monto, registrado_por))


def gastos_fondo() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM gastos_fondo ORDER BY fecha DESC"
        ).fetchall()


def get_gasto_fondo(gasto_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM gastos_fondo WHERE id=?", (gasto_id,)).fetchone()


def delete_gasto_fondo(gasto_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM gastos_fondo WHERE id=?", (gasto_id,))


def total_gastado_fondo() -> float:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(monto),0) FROM gastos_fondo"
        ).fetchone()[0]


def update_inversion_inicial(monto: float):
    set_config("inversion_inicial", str(monto))


def agregar_a_inversion(monto_extra: float):
    """Suma atómicamente al fondo inicial."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE config SET valor = CAST(CAST(valor AS REAL) + ? AS TEXT) "
            "WHERE clave='inversion_inicial'",
            (monto_extra,),
        )


# ═════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═════════════════════════════════════════════════════════════════════════════

def get_config(clave: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    return row["valor"] if row else None


def set_config(clave: str, valor):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES (?,?)",
            (clave, str(valor)),
        )


def get_socios() -> list[str]:
    val = get_config("socios")
    return [s.strip() for s in val.split(",")] if val else []


def set_socios(lista: list[str]):
    set_config("socios", ",".join(lista))


def get_inversion_inicial() -> float:
    val = get_config("inversion_inicial")
    try:
        return float(val) if val else 0.0
    except ValueError:
        return 0.0


# ═════════════════════════════════════════════════════════════════════════════
#  BODEGA DE BINs
# ═════════════════════════════════════════════════════════════════════════════

def agregar_tienda_bin(nombre: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute("INSERT INTO tiendas_bins (nombre) VALUES (?)", (nombre.strip(),))
            return True
        except sqlite3.IntegrityError:
            return False


def get_tiendas_bins() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT nombre FROM tiendas_bins ORDER BY nombre").fetchall()


def agregar_bin(bin_num: str, tienda: str, agregado_por: str) -> bool:
    with get_conn() as conn:
        ya = conn.execute(
            "SELECT id FROM bins WHERE bin=? AND tienda=?", (bin_num, tienda),
        ).fetchone()
        if ya:
            return False
        conn.execute(
            "INSERT INTO bins (bin, tienda, agregado_por, fecha) VALUES (?,?,?,?)",
            (bin_num, tienda, agregado_por, _now()),
        )
        return True


def get_bin_existente(bin_num: str, tienda: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM bins WHERE bin=? AND tienda=?", (bin_num, tienda),
        ).fetchone()


def bins_por_tienda(tienda: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM bins WHERE tienda=? ORDER BY bin", (tienda,),
        ).fetchall()


def todos_los_bins() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM bins ORDER BY tienda, bin").fetchall()


def get_bin(bin_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM bins WHERE id=?", (bin_id,)).fetchone()


def get_bin_cache(bin_num: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM bin_cache WHERE bin=?", (bin_num,)).fetchone()


def set_bin_cache(bin_num: str, bank: str, country: str, country_code: str,
                  brand: str, card_type: str, level: str,
                  fuentes: int, confianza: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO bin_cache
            (bin, bank, country, country_code, brand, type, level, fuentes, confianza, fecha)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (bin_num, bank, country, country_code, brand, card_type,
              level, fuentes, confianza, _now()))


def buscar_bin(bin_num: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM bins WHERE bin=? ORDER BY tienda", (bin_num,),
        ).fetchall()


def delete_bin(bin_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM bins WHERE id=?", (bin_id,))


def delete_tienda_bin(nombre: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM bins WHERE tienda=?", (nombre,))
        conn.execute("DELETE FROM tiendas_bins WHERE nombre=?", (nombre,))
